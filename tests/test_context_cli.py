#!/usr/bin/env python
"""
Headless tests for `penguin context` Typer subcommands.
"""

import os
import subprocess
import sys
from pathlib import Path


def run_cmd(args: list[str], env=None) -> tuple[int, str, str]:
    # Try both import styles to accommodate different package roots
    cmd = [sys.executable, "-m", "penguin.penguin.cli.cli_new", "context", *args]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env or os.environ.copy(),
        cwd=Path(__file__).parent,
    )
    if result.returncode != 0 and 'No module named' in (result.stderr or ''):
        alt = [sys.executable, "-m", "penguin.cli.cli_new", "context", *args]
        result = subprocess.run(
            alt,
            capture_output=True,
            text=True,
            env=env or os.environ.copy(),
            cwd=Path(__file__).parent,
        )
    return result.returncode, result.stdout, result.stderr


def main() -> int:
    print("\n🧪 Testing penguin context (headless)\n")
    # 1) paths should succeed
    code, out, err = run_cmd(["paths"]) 
    ok = code == 0 and out.strip() != ""
    print(("✅" if ok else "❌"), "context paths")
    if not ok:
        print(out or err)
        return 1

    # 2) write / edit / note / remove
    code, out, err = run_cmd(["write", "tmp/headless.txt", "--body", "hello"])
    ok = code == 0
    print(("✅" if ok else "❌"), "context write")
    if not ok:
        print(out or err); return 1

    code, out, err = run_cmd(["edit", "tmp/headless.txt", "--replace", "hello", "--with", "world"])
    ok = code == 0
    print(("✅" if ok else "❌"), "context edit")
    if not ok:
        print(out or err); return 1

    code, out, err = run_cmd(["note", "Headless", "--body", "note body"])
    ok = code == 0
    print(("✅" if ok else "❌"), "context note")
    if not ok:
        print(out or err); return 1

    code, out, err = run_cmd(["remove", "tmp/headless.txt"]) 
    ok = code == 0
    print(("✅" if ok else "❌"), "context remove")
    if not ok:
        print(out or err); return 1

    print("All headless context tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


