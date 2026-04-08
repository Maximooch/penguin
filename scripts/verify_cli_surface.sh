#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE="${PENGUIN_SURFACE_WORKSPACE:-$ROOT_DIR/tmp_workspace/cli_surface_verification}"
FIXTURE_JSON="${WORKSPACE}.fixture.json"

mkdir -p "$WORKSPACE"

run_penguin() {
  PENGUIN_SURFACE_WORKSPACE="$WORKSPACE" \
  PENGUIN_WORKSPACE="$WORKSPACE" \
  uv run penguin "$@"
}

echo "[1/7] Seeding isolated CLI verification workspace: $WORKSPACE"
PENGUIN_WORKSPACE="$WORKSPACE" uv run python "$ROOT_DIR/scripts/seed_surface_fixture.py" \
  --workspace "$WORKSPACE" --reset > "$FIXTURE_JSON"

PROJECT_ID="$(python - "$FIXTURE_JSON" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1]))
print(data["project"]["id"])
PY
)"

RUNNING_TASK_ID="$(python - "$FIXTURE_JSON" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1]))
print(data["tasks"]["running"])
PY
)"

PENDING_REVIEW_TASK_ID="$(python - "$FIXTURE_JSON" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1]))
print(data["tasks"]["pending_review"])
PY
)"

COMPLETED_TASK_ID="$(python - "$FIXTURE_JSON" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1]))
print(data["tasks"]["completed"])
PY
)"

echo "[2/7] Checking CLI help surface"
PROJECT_HELP="$(run_penguin project --help)"
TASK_HELP="$(run_penguin project task --help)"
python - "$PROJECT_HELP" "$TASK_HELP" <<'PY'
import sys

project_help, task_help = sys.argv[1], sys.argv[2]
assert "create" in project_help and "task" in project_help and "run" in project_help, project_help
assert "list" in task_help and "start" in task_help and "complete" in task_help, task_help
print("CLI help surface exposes expected project/task commands")
PY

echo "[3/7] Checking case-insensitive task status filter"
RUNNING_LIST="$(run_penguin project task list "$PROJECT_ID" --status RUNNING)"
python - "$RUNNING_LIST" <<'PY'
import sys

output = sys.argv[1]
assert "Running task" in output, output
assert "running" in output.lower(), output
print("Uppercase task status filter works")
PY

echo "[4/7] Checking invalid status failure messaging"
set +e
INVALID_OUTPUT="$(run_penguin project task list --status not-a-status 2>&1)"
INVALID_CODE=$?
set -e
python - "$INVALID_OUTPUT" "$INVALID_CODE" <<'PY'
import sys

output, code = sys.argv[1], int(sys.argv[2])
assert code != 0, (code, output)
assert "pending_review" in output, output
assert "running" in output, output
print("Invalid status path reports real lifecycle values")
PY

echo "[5/7] Checking task start wording"
START_OUTPUT="$(run_penguin project task start "$RUNNING_TASK_ID" 2>&1 || true)"
python - "$START_OUTPUT" <<'PY'
import sys

output = sys.argv[1]
assert "active state" in output.lower(), output
print("Task start wording is honest about active state")
PY

echo "[6/7] Checking review-approval completion semantics"
COMPLETE_OUTPUT="$(run_penguin project task complete "$PENDING_REVIEW_TASK_ID" 2>&1)"
ALREADY_OUTPUT="$(run_penguin project task complete "$COMPLETED_TASK_ID" 2>&1)"
python - "$COMPLETE_OUTPUT" "$ALREADY_OUTPUT" <<'PY'
import sys

complete_output, already_output = sys.argv[1], sys.argv[2]
assert "approved" in complete_output.lower(), complete_output
assert "already completed" in already_output.lower(), already_output
print("Task complete command reflects review-approval semantics")
PY

echo "[7/7] Checking execution root consistency across nested help commands"
PROJECT_HELP_ROOT="$(run_penguin project --help)"
TASK_HELP_ROOT="$(run_penguin project task --help)"
python - "$PROJECT_HELP_ROOT" "$TASK_HELP_ROOT" "$ROOT_DIR" <<'PY'
import re
import sys

def extract_root(output: str) -> str:
    match = re.search(r"Execution root:\s+\w+\s+\(([^)]+)\)", output)
    return match.group(1) if match else ""

project_root = extract_root(sys.argv[1])
task_root = extract_root(sys.argv[2])
expected_root = sys.argv[3]
assert project_root, sys.argv[1]
assert task_root, sys.argv[2]
assert project_root == task_root, (project_root, task_root)
assert project_root == expected_root, (project_root, expected_root)
print(f"Execution root is stable and correct across help surfaces: {project_root}")
PY

echo
echo "CLI surface verification passed."
echo "Workspace: $WORKSPACE"
echo
echo "Note:"
echo "- This script verifies the shipped uv-based Typer CLI surface."
echo "- Interactive slash-command verification should be tracked separately if you want pseudo-TTY coverage too."
