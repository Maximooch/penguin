import os
import sys
import subprocess


def main(argv: list[str]) -> int:
    # Sensible defaults to ensure fast, deterministic runs for new tests
    os.environ.setdefault("PYTEST_ADDOPTS", "-q")
    # Keep timeouts low so timeout tests finish quickly
    os.environ.setdefault("PENGUIN_TOOL_TIMEOUT", "2")
    os.environ.setdefault("PENGUIN_TOOL_TIMEOUT_CODE", "0")
    os.environ.setdefault("PENGUIN_TOOL_TIMEOUT_DIFF", "2")
    os.environ.setdefault("PENGUIN_TOOL_TIMEOUT_ANALYZE", "2")
    os.environ.setdefault("PENGUIN_TOOL_TIMEOUT_EDIT", "2")

    # Target the new tests by default; allow overrides (e.g. -k expr)
    pytest_args = ["-q", "tests/test_parser_and_tools.py"]
    # Pass through any additional args to pytest
    if argv:
        pytest_args = argv

    result = subprocess.run([sys.executable, "-m", "pytest", *pytest_args])
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))


