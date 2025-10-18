#!/usr/bin/env python3
"""
Test script for CLI formatting improvements.

Tests:
1. Internal marker filtering (<execute>, <system-reminder>)
2. Message deduplication
3. Blank line control
4. Configuration loading
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from rich.console import Console
from penguin.cli.renderer import UnifiedRenderer, RenderStyle


def test_internal_marker_filtering():
    """Test that internal markers are filtered from content."""
    print("\n=== Test 1: Internal Marker Filtering ===")

    renderer = UnifiedRenderer(
        console=Console(),
        style=RenderStyle.STANDARD,
        filter_internal_markers=True
    )

    # Test content with internal markers
    test_content = """
    Here is some code:
    <execute>
    print("This should be hidden")
    </execute>

    <system-reminder>
    This is an internal reminder that should not be shown to users.
    </system-reminder>

    This text should be visible.
    """

    filtered = renderer.filter_content(test_content)

    print(f"Original length: {len(test_content)}")
    print(f"Filtered length: {len(filtered)}")
    print(f"\nFiltered content:\n{filtered}")

    # Check that markers are removed
    assert "<execute>" not in filtered, "[FAIL] <execute> tag still present"
    assert "<system-reminder>" not in filtered, "[FAIL] <system-reminder> tag still present"
    assert "This text should be visible" in filtered, "[FAIL] Visible text was removed"

    print("[PASS] Internal markers successfully filtered")


def test_message_deduplication():
    """Test that duplicate messages are detected."""
    print("\n=== Test 2: Message Deduplication ===")

    renderer = UnifiedRenderer(
        console=Console(),
        style=RenderStyle.STANDARD,
        deduplicate_messages=True
    )

    message1 = "This is a test message"
    message2 = "This is a test message"  # Duplicate
    message3 = "This is a different message"

    # First message should not be duplicate
    is_dup1 = renderer.is_duplicate(message1)
    print(f"Message 1 is duplicate: {is_dup1}")
    assert not is_dup1, "[FAIL] First message incorrectly marked as duplicate"

    # Second message (duplicate) should be detected
    is_dup2 = renderer.is_duplicate(message2)
    print(f"Message 2 is duplicate: {is_dup2}")
    assert is_dup2, "[FAIL] Duplicate message not detected"

    # Third message (different) should not be duplicate
    is_dup3 = renderer.is_duplicate(message3)
    print(f"Message 3 is duplicate: {is_dup3}")
    assert not is_dup3, "[FAIL] Different message incorrectly marked as duplicate"

    print("[PASS] Message deduplication working correctly")


def test_blank_line_control():
    """Test that excessive blank lines are controlled."""
    print("\n=== Test 3: Blank Line Control ===")

    renderer = UnifiedRenderer(
        console=Console(),
        style=RenderStyle.STANDARD,
        max_blank_lines=2
    )

    # Content with many blank lines
    test_content = """
Line 1


Line 2




Line 3





Line 4
    """

    filtered = renderer.filter_content(test_content)

    print(f"Original content:\n{repr(test_content)}")
    print(f"\nFiltered content:\n{repr(filtered)}")

    # Check that no more than 3 consecutive newlines (max_blank_lines + 1)
    assert "\n\n\n\n" not in filtered, "[FAIL] More than max_blank_lines consecutive newlines found"

    print("[PASS] Blank line control working correctly")


def test_config_loading():
    """Test that CLI display config can be loaded."""
    print("\n=== Test 4: Configuration Loading ===")

    try:
        from penguin.cli.ui import CLIRenderer

        # CLIRenderer loads config in _load_cli_display_config
        # We can't easily test this without mocking, but we can verify the method exists
        assert hasattr(CLIRenderer, '_load_cli_display_config'), "[FAIL] _load_cli_display_config method not found"

        print("[PASS] Configuration loading method exists")
    except Exception as e:
        print(f"[FAIL] Configuration loading test failed: {e}")
        raise


def test_separator_logic():
    """Test that separator logic works correctly."""
    print("\n=== Test 5: Separator Logic ===")

    renderer = UnifiedRenderer(
        console=Console(),
        style=RenderStyle.STANDARD
    )

    # Test different role transitions
    test_cases = [
        (None, "user", False, "No separator for first message"),
        ("system", "system", False, "No separator between consecutive system messages"),
        ("tool", "tool", False, "No separator between consecutive tool messages"),
        ("assistant", "system", True, "Separator from assistant to system"),
        ("system", "user", True, "Separator from system to user"),
        ("assistant", "user", True, "Separator from assistant to user"),
    ]

    for prev_role, curr_role, expected, description in test_cases:
        result = renderer.should_add_separator(prev_role, curr_role)
        status = "[PASS]" if result == expected else "[FAIL]"
        print(f"{status} {description}: {prev_role} -> {curr_role} = {result} (expected {expected})")
        assert result == expected, f"Separator logic failed for {description}"

    print("[PASS] Separator logic working correctly")


def main():
    """Run all tests."""
    print("=" * 60)
    print("CLI Formatting Improvements Test Suite")
    print("=" * 60)

    try:
        test_internal_marker_filtering()
        test_message_deduplication()
        test_blank_line_control()
        test_config_loading()
        test_separator_logic()

        print("\n" + "=" * 60)
        print("[SUCCESS] ALL TESTS PASSED")
        print("=" * 60)
        return 0

    except AssertionError as e:
        print("\n" + "=" * 60)
        print(f"[FAIL] TEST FAILED: {e}")
        print("=" * 60)
        return 1
    except Exception as e:
        print("\n" + "=" * 60)
        print(f"[ERROR] UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
