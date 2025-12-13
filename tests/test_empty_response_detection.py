"""
Test the empty/trivial response detection logic from engine.py.

This tests the fix for the looping bug where the LLM returns near-empty
responses (3 tokens) that weren't being caught by the original empty check.

Run with: python tests/test_empty_response_detection.py
"""


def is_empty_or_trivial(response: str) -> bool:
    """
    Replicate the detection logic from engine.py.
    Returns True if response should be considered empty/trivial.
    """
    stripped_response = (response or "").strip()
    return not stripped_response or len(stripped_response) < 10


def simulate_engine_loop(responses: list) -> dict:
    """
    Simulate the engine's empty response tracking logic.
    Returns info about when/if the loop would break.
    """
    empty_response_count = 0
    iterations = 0
    break_reason = None

    for response in responses:
        iterations += 1
        stripped_response = (response or "").strip()
        is_trivial = not stripped_response or len(stripped_response) < 10

        if is_trivial:
            empty_response_count += 1
            if empty_response_count >= 3:
                break_reason = "implicit_completion"
                break
        else:
            empty_response_count = 0

    return {
        "iterations": iterations,
        "final_count": empty_response_count,
        "break_reason": break_reason,
    }


def test_truly_empty_responses():
    """Empty strings should be detected."""
    assert is_empty_or_trivial("") is True, "Empty string not detected"
    assert is_empty_or_trivial(None) is True, "None not detected"
    print("  ✓ test_truly_empty_responses")


def test_whitespace_only_responses():
    """Whitespace-only responses should be detected."""
    assert is_empty_or_trivial("   ") is True
    assert is_empty_or_trivial("\n\n") is True
    assert is_empty_or_trivial("\t\t\n") is True
    assert is_empty_or_trivial("  \n  \t  ") is True
    print("  ✓ test_whitespace_only_responses")


def test_trivial_responses_under_10_chars():
    """Short responses (< 10 chars after strip) should be detected."""
    # These are the problematic 3-token responses
    assert is_empty_or_trivial("I") is True
    assert is_empty_or_trivial("Let me") is True
    assert is_empty_or_trivial("\n\nI'm") is True
    assert is_empty_or_trivial("   OK   ") is True  # "OK" = 2 chars
    assert is_empty_or_trivial("Yes") is True
    assert is_empty_or_trivial("Sure") is True
    assert is_empty_or_trivial("Hmm...") is True  # 6 chars
    print("  ✓ test_trivial_responses_under_10_chars")


def test_boundary_at_10_chars():
    """Test the boundary condition at exactly 10 characters."""
    # Exactly 9 chars -> trivial
    assert is_empty_or_trivial("123456789") is True, "9 chars should be trivial"
    # Exactly 10 chars -> NOT trivial
    assert is_empty_or_trivial("1234567890") is False, "10 chars should NOT be trivial"
    # 11 chars -> NOT trivial
    assert is_empty_or_trivial("12345678901") is False
    print("  ✓ test_boundary_at_10_chars")


def test_substantive_responses():
    """Longer responses should NOT be detected as trivial."""
    assert is_empty_or_trivial("This is a real response.") is False
    assert is_empty_or_trivial("Sound good?") is False  # 11 chars
    assert is_empty_or_trivial("Let me check that for you.") is False
    assert is_empty_or_trivial("<finish_response></finish_response>") is False
    print("  ✓ test_substantive_responses")


def test_responses_with_tool_calls():
    """Responses containing tool calls should not be trivial."""
    assert is_empty_or_trivial("<execute>print('hi')</execute>") is False
    assert is_empty_or_trivial("<finish_response>Done</finish_response>") is False
    assert is_empty_or_trivial("<search>pattern</search>") is False
    print("  ✓ test_responses_with_tool_calls")


def test_three_empty_responses_breaks():
    """Three consecutive empty responses should trigger break."""
    responses = ["", "", ""]
    result = simulate_engine_loop(responses)
    assert result["iterations"] == 3, f"Expected 3 iterations, got {result['iterations']}"
    assert result["break_reason"] == "implicit_completion"
    print("  ✓ test_three_empty_responses_breaks")


def test_three_trivial_responses_breaks():
    """Three consecutive trivial responses should trigger break."""
    responses = ["I", "Let me", "Hmm"]
    result = simulate_engine_loop(responses)
    assert result["iterations"] == 3
    assert result["break_reason"] == "implicit_completion"
    print("  ✓ test_three_trivial_responses_breaks")


def test_mixed_trivial_breaks():
    """Mix of empty and trivial should still break at 3."""
    responses = ["\n\n", "I", "   "]
    result = simulate_engine_loop(responses)
    assert result["iterations"] == 3
    assert result["break_reason"] == "implicit_completion"
    print("  ✓ test_mixed_trivial_breaks")


def test_substantive_resets_counter():
    """A substantive response should reset the counter."""
    responses = ["", "", "This is a real response", "", "", ""]
    result = simulate_engine_loop(responses)
    # Should break after responses 4, 5, 6 (the three empties after reset)
    assert result["iterations"] == 6, f"Expected 6 iterations, got {result['iterations']}"
    assert result["break_reason"] == "implicit_completion"
    print("  ✓ test_substantive_resets_counter")


def test_no_break_with_substantive_responses():
    """All substantive responses should not trigger break."""
    responses = [
        "First response here",
        "Second response here",
        "Third response here",
    ]
    result = simulate_engine_loop(responses)
    assert result["iterations"] == 3
    assert result["break_reason"] is None
    assert result["final_count"] == 0
    print("  ✓ test_no_break_with_substantive_responses")


def test_two_empty_then_substantive():
    """Two empties followed by substantive should not break."""
    responses = ["", "", "Real response here"]
    result = simulate_engine_loop(responses)
    assert result["iterations"] == 3
    assert result["break_reason"] is None
    assert result["final_count"] == 0
    print("  ✓ test_two_empty_then_substantive")


def test_realistic_scenario_from_bug():
    """
    Simulate the actual bug scenario:
    - LLM gives real response ending with question
    - User says "Sounds good"
    - LLM has nothing to add, returns trivial responses
    """
    responses = [
        # LLM's real response (would have been in previous iteration)
        "Sound good?",  # This is 11 chars, NOT trivial
        # After user says "Sounds good", LLM has nothing to add
        "\n\n",  # trivial #1
        "I",     # trivial #2
        "",      # trivial #3 -> BREAK
        "",      # would never reach
        "",      # would never reach
    ]
    result = simulate_engine_loop(responses)
    # Should process: "Sound good?" (substantive), then 3 trivials and break
    assert result["iterations"] == 4, f"Expected 4 iterations, got {result['iterations']}"
    assert result["break_reason"] == "implicit_completion"
    print("  ✓ test_realistic_scenario_from_bug")


def test_unicode_handling():
    """Unicode characters should be handled correctly."""
    assert is_empty_or_trivial("🐧") is True  # 1 char (emoji)
    assert is_empty_or_trivial("🐧🐧🐧🐧🐧") is True  # 5 chars
    assert is_empty_or_trivial("🐧 Hello there!") is False  # 15+ chars
    print("  ✓ test_unicode_handling")


def test_newlines_in_middle():
    """Responses with newlines in middle should be handled."""
    assert is_empty_or_trivial("Hi\n\nBye") is True  # 7 chars after strip
    assert is_empty_or_trivial("Hello\n\nWorld!") is False  # 12 chars
    print("  ✓ test_newlines_in_middle")


def test_very_long_whitespace():
    """Long whitespace strings should still be trivial."""
    assert is_empty_or_trivial(" " * 1000) is True
    assert is_empty_or_trivial("\n" * 100) is True
    print("  ✓ test_very_long_whitespace")


def run_all_tests():
    """Run all tests and report results."""
    tests = [
        ("Empty Response Detection", [
            test_truly_empty_responses,
            test_whitespace_only_responses,
            test_trivial_responses_under_10_chars,
            test_boundary_at_10_chars,
            test_substantive_responses,
            test_responses_with_tool_calls,
        ]),
        ("Counter Behavior", [
            test_three_empty_responses_breaks,
            test_three_trivial_responses_breaks,
            test_mixed_trivial_breaks,
            test_substantive_resets_counter,
            test_no_break_with_substantive_responses,
            test_two_empty_then_substantive,
            test_realistic_scenario_from_bug,
        ]),
        ("Edge Cases", [
            test_unicode_handling,
            test_newlines_in_middle,
            test_very_long_whitespace,
        ]),
    ]

    total_passed = 0
    total_failed = 0
    failures = []

    print("\n" + "=" * 60)
    print("Empty/Trivial Response Detection Tests")
    print("=" * 60)

    for category_name, category_tests in tests:
        print(f"\n{category_name}:")
        for test_fn in category_tests:
            try:
                test_fn()
                total_passed += 1
            except AssertionError as e:
                total_failed += 1
                failures.append((test_fn.__name__, str(e)))
                print(f"  ✗ {test_fn.__name__}: {e}")
            except Exception as e:
                total_failed += 1
                failures.append((test_fn.__name__, str(e)))
                print(f"  ✗ {test_fn.__name__}: {e}")

    print("\n" + "=" * 60)
    print(f"Results: {total_passed} passed, {total_failed} failed")
    print("=" * 60)

    if failures:
        print("\nFailures:")
        for name, error in failures:
            print(f"  - {name}: {error}")
        return 1
    else:
        print("\n✓ All tests passed!")
        return 0


if __name__ == "__main__":
    exit(run_all_tests())
