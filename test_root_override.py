#!/usr/bin/env python
"""
Test env root override PENGUIN_WRITE_ROOT for guarded writes.
"""

import os
import subprocess
import sys
from pathlib import Path

from penguin.config import WORKSPACE_PATH, load_config


def run_cli_write(relpath: str, body: str, env_override: dict[str, str] | None = None) -> int:
    env = os.environ.copy()
    if env_override:
        env.update(env_override)
    # Use headless write
    cmd = [sys.executable, "-m", "penguin.penguin.cli.cli_new", "context", "write", relpath, "--body", body]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        cwd=Path(__file__).parent,
    )
    if result.returncode != 0 and 'No module named' in (result.stderr or ''):
        alt = [sys.executable, "-m", "penguin.cli.cli_new", "context", "write", relpath, "--body", body]
        result = subprocess.run(
            alt,
            capture_output=True,
            text=True,
            env=env,
            cwd=Path(__file__).parent,
        )
    return result.returncode


def main() -> int:
    print("\n🧪 Testing PENGUIN_WRITE_ROOT override\n")
    cfg = load_config()
    workspace = Path(WORKSPACE_PATH)
    target = workspace / "tmp" / "override.txt"
    if target.exists():
        try:
            target.unlink()
        except Exception:
            pass

    # Force workspace writes
    code = run_cli_write("tmp/override.txt", "data", env_override={"PENGUIN_WRITE_ROOT": "workspace"})
    ok = code == 0 and target.exists()
    print(("✅" if ok else "❌"), "env workspace write")
    if not ok:
        return 1

    print("Env root override test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


