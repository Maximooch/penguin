#!/usr/bin/env python3
"""Tests for command_filter module."""

import sys
sys.path.insert(0, ".")

from penguin.security.command_filter import (
    is_command_safe,
    CommandRisk,
    CommandFilterResult,
)


def test_safe_commands():
    """Test that safe commands are allowed."""
    print("\n=== Test: Safe Commands ===")

    safe_commands = [
        "grep -r 'pattern' src/",
        "find . -name '*.py'",
        "cat README.md",
        "head -n 50 file.txt",
        "tail -f log.txt",
        "ls -la",
        "tree src/",
        "wc -l *.py",
        "git log --oneline -10",
        "git status",
        "git diff HEAD~1",
        "git branch -a",
        "pwd",
        "echo hello",
        "rg 'TODO' --type py",
    ]

    passed = 0
    for cmd in safe_commands:
        result = is_command_safe(cmd)
        status = "✓" if result.allowed else "✗"
        print(f"  {status} {cmd[:50]}")
        if not result.allowed:
            print(f"      Reason: {result.reason}")
        else:
            passed += 1

    print(f"  Passed: {passed}/{len(safe_commands)}")
    return passed == len(safe_commands)


def test_dangerous_commands():
    """Test that dangerous commands are blocked."""
    print("\n=== Test: Dangerous Commands ===")

    dangerous_commands = [
        "rm -rf /",
        "rm file.txt",
        "mv old.txt new.txt",
        "cp src dst",
        "chmod 777 file",
        "sudo apt update",
        "git push origin main",
        "git commit -m 'test'",
        "git reset --hard",
        "git checkout main",
        "> file.txt",
        "echo 'data' > file.txt",
        "cat file >> other",
    ]

    passed = 0
    for cmd in dangerous_commands:
        result = is_command_safe(cmd)
        status = "✓" if not result.allowed else "✗"
        print(f"  {status} {cmd[:50]} -> blocked: {not result.allowed}")
        if result.allowed:
            print(f"      ERROR: Should be blocked!")
        else:
            passed += 1

    print(f"  Passed: {passed}/{len(dangerous_commands)}")
    return passed == len(dangerous_commands)


def test_command_chains():
    """Test pipe and chain handling."""
    print("\n=== Test: Command Chains ===")

    test_cases = [
        # (command, should_be_allowed)
        ("grep pattern | head", True),
        ("find . -name '*.py' | wc -l", True),
        ("cat file | grep pattern | sort | uniq", True),
        ("ls -la | grep test", True),
        ("cat file; rm file", False),  # Dangerous chain
        ("grep pattern && rm file", False),
        ("cat file || rm -rf /", False),
    ]

    passed = 0
    for cmd, should_allow in test_cases:
        result = is_command_safe(cmd)
        correct = result.allowed == should_allow
        status = "✓" if correct else "✗"
        print(f"  {status} {cmd[:50]} -> allowed: {result.allowed} (expected: {should_allow})")
        if not correct:
            print(f"      Reason: {result.reason}")
        else:
            passed += 1

    print(f"  Passed: {passed}/{len(test_cases)}")
    return passed == len(test_cases)


def test_command_substitution():
    """Test that command substitution is blocked."""
    print("\n=== Test: Command Substitution ===")

    dangerous = [
        "echo $(rm -rf /)",
        "cat `rm file`",
        "ls $(cat /etc/passwd)",
        "echo ${PATH}",  # Variable expansion
    ]

    passed = 0
    for cmd in dangerous:
        result = is_command_safe(cmd)
        status = "✓" if not result.allowed else "✗"
        print(f"  {status} {cmd[:50]} -> blocked: {not result.allowed}")
        if not result.allowed:
            passed += 1

    print(f"  Passed: {passed}/{len(dangerous)}")
    return passed == len(dangerous)


def test_dangerous_flags():
    """Test that dangerous flags on safe commands are blocked."""
    print("\n=== Test: Dangerous Flags ===")

    test_cases = [
        ("curl https://example.com", True),  # Safe - just fetch
        ("curl -o file.txt https://example.com", False),  # Writes file
        ("wget https://example.com", True),  # Display only
        ("wget -O file.txt https://example.com", False),  # Writes file
        ("sed 's/a/b/' file.txt", True),  # Outputs to stdout
        ("sed -i 's/a/b/' file.txt", False),  # In-place edit
        ("tar -tf archive.tar", True),  # List contents
        ("tar -xf archive.tar", False),  # Extract
    ]

    passed = 0
    for cmd, should_allow in test_cases:
        result = is_command_safe(cmd)
        correct = result.allowed == should_allow
        status = "✓" if correct else "✗"
        print(f"  {status} {cmd[:50]} -> allowed: {result.allowed} (expected: {should_allow})")
        if not correct:
            print(f"      Reason: {result.reason}")
        else:
            passed += 1

    print(f"  Passed: {passed}/{len(test_cases)}")
    return passed == len(test_cases)


def run_tests():
    """Run all command filter tests."""
    print("=" * 60)
    print("COMMAND FILTER TESTS")
    print("=" * 60)

    tests = [
        ("Safe Commands", test_safe_commands),
        ("Dangerous Commands", test_dangerous_commands),
        ("Command Chains", test_command_chains),
        ("Command Substitution", test_command_substitution),
        ("Dangerous Flags", test_dangerous_flags),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"\n✗ EXCEPTION in {name}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
