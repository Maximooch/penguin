#!/usr/bin/env python3
"""Test script for delegate_explore_task tool."""

import asyncio
import sys
import os

sys.path.insert(0, ".")

async def test_delegate_explore_task():
    """Test the delegate_explore_task functionality."""
    print("=" * 60)
    print("DELEGATE_EXPLORE_TASK TEST")
    print("=" * 60)

    # Test 1: Check ActionType enum has the new type
    print("\n=== Test 1: ActionType enum ===")
    from penguin.utils.parser import ActionType

    assert hasattr(ActionType, 'DELEGATE_EXPLORE_TASK'), "Missing DELEGATE_EXPLORE_TASK in ActionType"
    print(f"✓ ActionType.DELEGATE_EXPLORE_TASK = {ActionType.DELEGATE_EXPLORE_TASK.value}")

    # Test 2: Create PenguinCore and verify executor exists
    print("\n=== Test 2: PenguinCore setup ===")
    from penguin.config import Config
    from penguin.core import PenguinCore

    config = Config.load_config()
    core = PenguinCore(config=config)

    executor = core.action_executor
    assert executor is not None, "ActionExecutor not initialized"
    print(f"✓ ActionExecutor initialized")

    # Check the method exists
    assert hasattr(executor, '_delegate_explore_task'), "Missing _delegate_explore_task method"
    print(f"✓ _delegate_explore_task method exists")

    # Test 3: Test tool execution (requires API key)
    print("\n=== Test 3: Tool execution ===")

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("⚠ OPENROUTER_API_KEY not set, skipping execution test")
        print("\n" + "=" * 60)
        print("TESTS PASSED (execution skipped)")
        print("=" * 60)
        return True

    # Test with a simple task
    test_params = '{"task": "List the files in the current directory and identify what type of project this is", "max_iterations": 3}'

    print(f"Calling delegate_explore_task...")
    print(f"Task: List files and identify project type")
    print(f"Max iterations: 3")
    print()

    try:
        result = await executor._delegate_explore_task(test_params)
        print(f"=== Result ({len(result)} chars) ===")
        print(result[:2000])
        if len(result) > 2000:
            print("... (truncated)")

        assert "[Haiku Explorer]" in result, "Expected [Haiku Explorer] prefix in result"
        print("\n✓ delegate_explore_task executed successfully")

    except Exception as e:
        print(f"\n✗ Execution failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = asyncio.run(test_delegate_explore_task())
    sys.exit(0 if success else 1)
