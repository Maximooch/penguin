#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE="${PENGUIN_SURFACE_WORKSPACE:-$ROOT_DIR/tmp_workspace/web_surface_verification}"
PREFERRED_PORT="${PENGUIN_SURFACE_PORT:-9000}"
PORT=""
BASE_URL=""
SERVER_LOG="${PENGUIN_SURFACE_SERVER_LOG:-$WORKSPACE/penguin-web.log}"
FIXTURE_JSON="${WORKSPACE}.fixture.json"

mkdir -p "$WORKSPACE"

cleanup() {
  if [[ -n "${SERVER_PID:-}" ]]; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
    wait "$SERVER_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

choose_port() {
  python - "$PREFERRED_PORT" <<'PY'
import socket
import sys

preferred = int(sys.argv[1])
candidates = [preferred] + list(range(max(9000, preferred + 1), max(9000, preferred + 40)))
for port in candidates:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("0.0.0.0", port))
        except OSError:
            continue
        print(port)
        break
else:
    raise SystemExit("no free port found in verification range")
PY
}

read_fixture_value() {
  python - "$FIXTURE_JSON" "$1" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1]))
keys = sys.argv[2].split(".")
value = data
for key in keys:
    value = value[key]
print(value)
PY
}

echo "[1/8] Seeding isolated verification workspace: $WORKSPACE"
PENGUIN_WORKSPACE="$WORKSPACE" uv run python "$ROOT_DIR/scripts/seed_surface_fixture.py" \
  --workspace "$WORKSPACE" --reset > "$FIXTURE_JSON"

PROJECT_ID="$(read_fixture_value project.id)"
RICH_TASK_ID="$(read_fixture_value tasks.rich_payload)"
PENDING_REVIEW_TASK_ID="$(read_fixture_value tasks.pending_review)"
ACTIVE_TASK_ID="$(read_fixture_value tasks.active)"

PORT="$(choose_port)"
BASE_URL="http://127.0.0.1:${PORT}"

echo "[2/8] Starting penguin-web on port $PORT"
PENGUIN_WORKSPACE="$WORKSPACE" PORT="$PORT" uv run penguin-web >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!

echo "[3/8] Waiting for Penguin health endpoint"
for _ in {1..30}; do
  if ! kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    echo "penguin-web exited early; server log follows:" >&2
    tail -n 120 "$SERVER_LOG" >&2 || true
    exit 1
  fi

  HEALTH_BODY="$(curl -sS "$BASE_URL/api/v1/health" || true)"
  if [[ -n "$HEALTH_BODY" ]] && python - "$HEALTH_BODY" <<'PY' >/dev/null 2>&1
import json
import sys

payload = json.loads(sys.argv[1])
assert payload.get("status") in {"healthy", "degraded", "at_capacity"}
PY
  then
    break
  fi
  sleep 1
done

HEALTH_JSON="$(curl -fsS "$BASE_URL/api/v1/health")"
python - "$HEALTH_JSON" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
assert payload.get("status") in {"healthy", "degraded", "at_capacity"}, payload
print(f"Health check passed with status={payload['status']}")
PY

echo "[4/8] Verifying list endpoint accepts case-insensitive status filters"
RUNNING_JSON="$(curl -fsS "$BASE_URL/api/v1/tasks?project_id=$PROJECT_ID&status=RUNNING")"
python - "$RUNNING_JSON" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
assert "tasks" in payload, payload
assert isinstance(payload["tasks"], list), payload
print(f"RUNNING filter returned {len(payload['tasks'])} tasks")
PY

INVALID_OUTPUT="$(mktemp)"
curl -sS -o "$INVALID_OUTPUT" -w '%{http_code}' "$BASE_URL/api/v1/tasks?status=not-a-status" > "$INVALID_OUTPUT.code"
HTTP_CODE="$(cat "$INVALID_OUTPUT.code")"
python - "$HTTP_CODE" "$INVALID_OUTPUT" <<'PY'
import sys

status = sys.argv[1]
body = open(sys.argv[2]).read()
assert status == "400", (status, body)
assert "pending_review" in body, body
assert "running" in body, body
print("Invalid status path returned honest 400 payload")
PY
rm -f "$INVALID_OUTPUT" "$INVALID_OUTPUT.code"

echo "[5/8] Verifying richer task payload truth"
TASK_JSON="$(curl -fsS "$BASE_URL/api/v1/tasks/$RICH_TASK_ID")"
python - "$TASK_JSON" <<'PY'
import json
import sys

task = json.loads(sys.argv[1])
required = [
    "status",
    "phase",
    "dependencies",
    "dependency_specs",
    "artifact_evidence",
    "recipe",
    "metadata",
    "clarification_requests",
]
missing = [key for key in required if key not in task]
assert not missing, missing
assert task["dependency_specs"], task
assert task["artifact_evidence"], task
assert task["clarification_requests"], task
print("Rich task payload exposes lifecycle and clarification truth")
PY

echo "[6/8] Verifying project payload embeds richer task payloads"
PROJECT_JSON="$(curl -fsS "$BASE_URL/api/v1/projects/$PROJECT_ID")"
python - "$PROJECT_JSON" "$RICH_TASK_ID" <<'PY'
import json
import sys

project = json.loads(sys.argv[1])
task_id = sys.argv[2]
task = next(item for item in project["tasks"] if item["id"] == task_id)
assert "phase" in task, task
assert "clarification_requests" in task, task
print("Project payload embeds enriched task payloads")
PY

echo "[7/8] Verifying task start/complete routes tell the truth"
START_JSON="$(curl -fsS -X POST "$BASE_URL/api/v1/tasks/$ACTIVE_TASK_ID/start")"
python - "$START_JSON" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
assert payload["status"] == "active", payload
assert "active state" in payload["message"].lower(), payload
print("Task start route uses active-state language")
PY

COMPLETE_JSON="$(curl -fsS -X POST "$BASE_URL/api/v1/tasks/$PENDING_REVIEW_TASK_ID/complete")"
python - "$COMPLETE_JSON" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
assert payload["status"] == "completed", payload
assert "approved" in payload["message"].lower(), payload
print("Task complete route behaves as review approval")
PY

echo "[8/8] Verifying clarification resume missing-task path fails honestly"
MISSING_OUTPUT="$(mktemp)"
curl -sS -o "$MISSING_OUTPUT" -w '%{http_code}' \
  -X POST "$BASE_URL/api/v1/tasks/missing-task-id/clarification/resume" \
  -H 'Content-Type: application/json' \
  -d '{"answer":"Use rotating refresh tokens","answered_by":"surface-script"}' \
  > "$MISSING_OUTPUT.code"
HTTP_CODE="$(cat "$MISSING_OUTPUT.code")"
python - "$HTTP_CODE" "$MISSING_OUTPUT" <<'PY'
import sys

status = sys.argv[1]
body = open(sys.argv[2]).read()
assert status == "404", (status, body)
assert "not found" in body.lower(), body
print("Clarification resume missing-task path returns honest 404")
PY
rm -f "$MISSING_OUTPUT" "$MISSING_OUTPUT.code"

echo
echo "Web/API surface verification passed."
echo "Workspace: $WORKSPACE"
echo "Server log: $SERVER_LOG"
echo "Port: $PORT"
echo
echo "Optional follow-up:"
echo "- For full clarification resume and execute-route waiting_input checks, use a live model-backed task that actually reaches clarification_needed."
