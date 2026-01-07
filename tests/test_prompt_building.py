#!/usr/bin/env python3
"""Test script to verify prompt building in all modes."""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def test_prompt_building():
    """Test that prompts build correctly in all modes."""
    print("Testing prompt building...")

    try:
        from penguin.system_prompt import get_system_prompt

        modes = ["direct", "bench_minimal", "terse", "explain", "review", "implement", "test"]

        results = {}
        for mode in modes:
            try:
                prompt = get_system_prompt(mode=mode)
                results[mode] = {
                    "success": True,
                    "length": len(prompt),
                    "has_base": "You are Penguin" in prompt,
                    "has_action_syntax": "## Action Syntax" in prompt or "Action Syntax" in prompt,
                }
                print(f"✓ {mode:12s} - {len(prompt):6d} chars - base: {results[mode]['has_base']} - action: {results[mode]['has_action_syntax']}")
            except Exception as e:
                results[mode] = {
                    "success": False,
                    "error": str(e)
                }
                print(f"✗ {mode:12s} - ERROR: {e}")

        # Check for formatting rules
        print()
        print("Checking for formatting rules...")
        direct_prompt = get_system_prompt(mode="direct")

        checks = {
            "CODE_FORMATTING_RULES": "Language tag on separate line" in direct_prompt,
            "FORBIDDEN_PHRASES": "Let me start by" in direct_prompt,
            "INCREMENTAL_EXECUTION": "Execute ONE" in direct_prompt,
            "SAFETY_RULES": "Check before write" in direct_prompt,
        }

        for check_name, passed in checks.items():
            status = "✓" if passed else "✗"
            print(f"{status} {check_name}: {passed}")

        # Check for deduplication
        print()
        print("Checking for deduplication...")
        direct_lines = direct_prompt.split("\n")

        # Count occurrences of key phrases
        counts = {
            "Code Formatting Standard": direct_prompt.count("**Code Formatting Standard:**"),
            "Language tag on separate line": direct_prompt.count("Language tag on separate line with MANDATORY newline"),
            "Check before write": direct_prompt.count("Check before write: `Path(file).exists()`"),
        }

        print("Phrase occurrence counts:")
        for phrase, count in counts.items():
            status = "✓" if count == 1 else "⚠" if count > 1 else "✗"
            print(f"{status} '{phrase}': {count} occurrence(s)")

        # Summary
        print()
        print("="*60)
        successful = sum(1 for r in results.values() if r["success"])
        print(f"Modes tested: {len(modes)}")
        print(f"Successful: {successful}")
        print(f"Failed: {len(modes) - successful}")

        if successful == len(modes) and all(checks.values()):
            print()
            print("✓ All tests passed!")
            return True
        else:
            print()
            print("✗ Some tests failed")
            return False

    except Exception as e:
        print()
        print(f"✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_prompt_building()
    sys.exit(0 if success else 1)
