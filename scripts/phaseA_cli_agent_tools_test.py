"""
Phase A – CLI Agent Tools Test (no pytest)

Programmatically invokes the Typer CLI (penguin/cli/cli.py) using Click's
CliRunner to validate:
 - agent spawn (as sub-agent)
 - agent info --json (profile includes is_sub_agent, parent, paused)
 - agent pause / resume (paused flag flips)

Run:
  python scripts/phaseA_cli_agent_tools_test.py
"""

from __future__ import annotations

import json
import sys
import uuid
from typer.testing import CliRunner

from penguin.cli.cli import app as penguin_app


def _extract_json(output: str):
    """Best-effort JSON extractor from CLI output (handles ANSI + both list/object)."""
    import re, json as _json
    # strip ANSI color codes
    ansi = re.compile(r"\x1b\[[0-9;]*m")
    cleaned = ansi.sub("", output).strip()
    # 1) Try direct parse first (works for pure JSON list/object)
    try:
        return _json.loads(cleaned)
    except Exception:
        pass
    # 2) Try list segment
    try:
        s, e = cleaned.find("["), cleaned.rfind("]")
        if s != -1 and e != -1 and e >= s:
            return _json.loads(cleaned[s : e + 1])
    except Exception:
        pass
    # 3) Try object segment
    try:
        s, e = cleaned.find("{"), cleaned.rfind("}")
        if s != -1 and e != -1 and e >= s:
            return _json.loads(cleaned[s : e + 1])
    except Exception:
        pass
    return None


def _parse_roster_paused(output: str, agent_id: str) -> str | None:
    """Parse Rich table output from `penguin agent list` and return the
    Paused column value for the requested agent (e.g., 'yes' or '').

    The table uses box-drawing characters (│) as column separators. This parser
    strips ANSI codes, finds the header row, maps column indexes, then finds the
    row for agent_id and returns the Paused cell.
    """
    import re

    # Strip ANSI color codes
    ansi = re.compile(r"\x1b\[[0-9;]*m")
    cleaned = ansi.sub("", output)

    # Split lines and find header row
    lines = cleaned.splitlines()
    sep_chars = ["│", "|", "┃"]
    header_idx = -1
    header_cells: list[str] = []
    for i, line in enumerate(lines):
        for sep in sep_chars:
            if "Agent" in line and "Paused" in line and sep in line:
                cells = [c.strip() for c in line.split(sep)]
                # Heuristic: must include both labels
                if any(c == "Agent" for c in cells) and any(c == "Paused" for c in cells):
                    header_idx = i
                    header_cells = cells
                    break
        if header_idx != -1:
            break
    if header_idx == -1:
        return None

    # Build column index map
    col_index: dict[str, int] = {}
    for idx, c in enumerate(header_cells):
        if c:
            col_index[c] = idx

    if "Agent" not in col_index or "Paused" not in col_index:
        return None

    # Scan subsequent lines for the agent row
    for line in lines[header_idx + 1 :]:
        # Skip border rows
        if set(line.strip()) <= {"┏", "┓", "┗", "┛", "━", "┳", "┻", "┣", "┫", "╋", "━", "-", "+"}:
            continue
        if not any(sep in line for sep in sep_chars):
            continue
        # Try both separators
        for sep in sep_chars:
            if sep in line:
                cells = [c.strip() for c in line.split(sep)]
                if len(cells) <= max(col_index.values()):
                    continue
                if cells[col_index["Agent"]] == agent_id:
                    return cells[col_index["Paused"]]
                break
    return None


def main() -> int:
    # Older Click versions don't support mix_stderr; use defaults
    runner = CliRunner()
    agent_id = f"cli_child_{uuid.uuid4().hex[:6]}"
    parent_id = "default"

    print(f"[cli] Spawning sub-agent: {agent_id}")
    # Try preferred model id first, then fall back if unavailable
    preferred_model = "moonshotai/kimi-k2-0905"
    spawn_args_base = [
        "agent",
        "spawn",
        agent_id,
        "--parent",
        parent_id,
        "--isolate-session",
        "--isolate-context",
        "--activate",
    ]

    def _spawn_with(model_id: str | None):
        args = list(spawn_args_base)
        if model_id:
            args.extend(["--model-id", model_id])
        return runner.invoke(penguin_app, args, prog_name="penguin")

    res = _spawn_with(preferred_model)
    if res.exit_code != 0:
        out = res.output.lower()
        # Fallback to common config id if preferred is missing
        if "model id" in out and "not found" in out:
            res = _spawn_with("kimi-lite")
        # Final fallback without explicit model
        if res.exit_code != 0:
            res = _spawn_with(None)
    if res.exit_code != 0:
        print("[cli][ERROR] spawn failed after fallbacks:\n", res.output)
        return 1

    print("[cli] Fetching agent info (JSON)")
    res = runner.invoke(penguin_app, ["agent", "info", agent_id, "--json"], prog_name="penguin")
    if res.exit_code != 0:
        print("[cli][ERROR] info failed:\n", res.output)
        return 1
    profile = _extract_json(res.output)
    if not isinstance(profile, dict):
        print("[cli][ERROR] failed to parse info JSON:")
        print(res.output)
        return 1

    # Basic assertions (soft – prints and returns 1 on failure)
    if not profile.get("is_sub_agent"):
        print("[cli][ERROR] expected is_sub_agent=true in profile")
        print(json.dumps(profile, indent=2))
        return 1
    if profile.get("parent") != parent_id:
        print("[cli][ERROR] expected parent to be", parent_id)
        print(json.dumps(profile, indent=2))
        return 1
    if profile.get("paused"):
        print("[cli][ERROR] expected paused=false after spawn")
        print(json.dumps(profile, indent=2))
        return 1

    # Pause
    print("[cli] Pausing agent")
    res = runner.invoke(penguin_app, ["agent", "pause", agent_id], prog_name="penguin")
    if res.exit_code != 0:
        print("[cli][ERROR] pause failed:\n", res.output)
        return 1

    res = runner.invoke(penguin_app, ["agent", "info", agent_id, "--json"], prog_name="penguin")
    profile = _extract_json(res.output)
    if not isinstance(profile, dict):
        print("[cli][ERROR] info parse after pause failed:\n", res.output)
        return 1
    if not profile.get("paused"):
        print("[cli][ERROR] expected paused=true after pause")
        print(json.dumps(profile, indent=2))
        return 1

    # Validate roster table shows Paused=yes
    print("[cli] Validating roster JSON shows paused=true")
    res = runner.invoke(penguin_app, ["agent", "list", "--json"], prog_name="penguin")
    roster = _extract_json(res.output)
    if not isinstance(roster, list):
        print("[cli][ERROR] list --json did not return a JSON list")
        print(res.output)
        return 1
    row = next((r for r in roster if r.get("id") == agent_id), None)
    if not row or not row.get("paused"):
        print("[cli][ERROR] roster JSON does not show paused=true after pause")
        print(res.output)
        return 1

    # Resume
    print("[cli] Resuming agent")
    res = runner.invoke(penguin_app, ["agent", "resume", agent_id], prog_name="penguin")
    if res.exit_code != 0:
        print("[cli][ERROR] resume failed:\n", res.output)
        return 1

    res = runner.invoke(penguin_app, ["agent", "info", agent_id, "--json"], prog_name="penguin")
    profile = _extract_json(res.output)
    if not isinstance(profile, dict):
        print("[cli][ERROR] info parse after resume failed:\n", res.output)
        return 1
    if profile.get("paused"):
        print("[cli][ERROR] expected paused=false after resume")
        print(json.dumps(profile, indent=2))
        return 1

    # Validate roster table shows Paused cleared
    print("[cli] Validating roster JSON shows paused=false")
    res = runner.invoke(penguin_app, ["agent", "list", "--json"], prog_name="penguin")
    roster = _extract_json(res.output)
    if not isinstance(roster, list):
        print("[cli][ERROR] list --json did not return a JSON list")
        print(res.output)
        return 1
    row = next((r for r in roster if r.get("id") == agent_id), None)
    if not row or row.get("paused"):
        print("[cli][ERROR] roster JSON still shows paused=true after resume")
        print(res.output)
        return 1

    print("[cli] All CLI agent tool checks passed ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
