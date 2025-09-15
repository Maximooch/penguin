#!/usr/bin/env python3
"""
Penguin test suite runner (print + exit code scripts).

Discovers and runs all test_*.py scripts under penguin/tests recursively.
Runs in a stable order (prompt → system → tools → runmode → other), with
optional stress skipping via env PENGUIN_SKIP_STRESS=1.

Usage: python run_all_tests.py
"""

import os
import subprocess
import sys
import time
from pathlib import Path


def run_test_script(script_path: Path):
    print(f"🏃 Running {script_path.relative_to(ROOT)}")
    print("=" * 60)
    start_time = time.time()
    try:
        result = subprocess.run(
            [sys.executable, str(script_path.name)],
            capture_output=True,
            text=True,
            cwd=str(script_path.parent),
        )
        duration = time.time() - start_time
        if result.stdout:
            print(result.stdout)
        if result.stderr and result.returncode != 0:
            print("STDERR:")
            print(result.stderr)
        status = "✅ PASSED" if result.returncode == 0 else f"❌ FAILED (exit {result.returncode})"
        print(f"\n{status} - {script_path.name} in {duration:.2f}s")
        return result.returncode == 0, duration
    except Exception as e:
        duration = time.time() - start_time
        print(f"💥 ERROR running {script_path.name}: {e}")
        return False, duration


def discover_tests(root: Path) -> list[Path]:
    tests = []
    for p in root.rglob("test_*.py"):
        if p.name == "run_all_tests.py":
            continue
        # Optionally skip stress tests
        if os.environ.get("PENGUIN_SKIP_STRESS", "0") in ("1", "true", "yes"):
            if "stress" in p.name:
                continue
        tests.append(p)
    # Stable ordering by domain
    def sort_key(path: Path):
        parts = path.parts
        # .../tests/<domain>/file
        dom = parts[-2] if len(parts) >= 2 else "z"
        order = {"prompt": 0, "system": 1, "tools": 2, "runmode": 3}
        return (order.get(dom, 9), str(path))
    tests.sort(key=sort_key)
    return tests


def main() -> int:
    global ROOT
    ROOT = Path(__file__).parent
    print("🧪 Running Penguin Tests\n")
    tests = discover_tests(ROOT)
    if not tests:
        print("❌ No tests found")
        return 1

    results = {}
    total_duration = 0.0

    for script in tests:
        ok, dur = run_test_script(script)
        results[str(script.relative_to(ROOT))] = (ok, dur)
        total_duration += dur
        print("\n" + "=" * 80 + "\n")

    print("📊 TEST SUMMARY")
    print("=" * 60)
    passed = sum(1 for ok, _ in results.values() if ok)
    total = len(results)
    for name, (ok, dur) in results.items():
        status = "✅" if ok else "❌"
        print(f"{status} {name:<45} {dur:.2f}s")
    print(f"\nOverall: {passed}/{total} passed")
    print(f"Total runtime: {total_duration:.2f}s")
    return 0 if passed == total else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n⏹️  Tests interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"💥 Unexpected error in test runner: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
