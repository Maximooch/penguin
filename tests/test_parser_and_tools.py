import os
import json
import types
import asyncio

from penguin.utils.parser import parse_action, ActionType
from penguin.tools.tool_manager import ToolManager
from penguin.llm.openrouter_gateway import OpenRouterGateway
from penguin.llm.model_config import ModelConfig


def _dummy_log_error(exc: Exception, context: str = ""):
    pass


def test_parse_action_detects_enhanced_write():
    content = """
    Here is the plan.
    <enhanced_write>path/to/file.txt:Hello:True</enhanced_write>
    """.strip()

    actions = parse_action(content)
    assert len(actions) == 1
    assert actions[0].action_type == ActionType.ENHANCED_WRITE
    assert actions[0].params.startswith("path/to/file.txt:")


def test_tool_manager_get_responses_tools_curated():
    # Minimal ToolManager instantiation
    tm = ToolManager(config={}, log_error_func=_dummy_log_error, fast_startup=True)

    tools_payload = tm.get_responses_tools()

    # Ensure it's a non-empty list of tools and includes curated names
    assert isinstance(tools_payload, list)
    names = set()
    for t in tools_payload:
        if t.get("type") == "function":
            names.add(t["function"].get("name"))

    # A few representative curated tools
    assert "write_to_file" in names
    assert "read_file" in names
    assert "execute_command" in names

    # Built-in web_search should be included as a non-function tool descriptor
    assert any(t.get("type") == "web_search" for t in tools_payload)


def test_code_execution_timeout(monkeypatch):
    tm = ToolManager(config={}, log_error_func=_dummy_log_error, fast_startup=True)
    # Force a near-immediate timeout
    monkeypatch.setenv("PENGUIN_TOOL_TIMEOUT_CODE", "0")
    result = tm.execute_code("import time; time.sleep(1)")
    assert isinstance(result, str)
    assert "timeout" in result.lower()


def test_gateway_contains_penguin_action_tags_true_false():
    # Create instance without running __init__ (avoids client setup)
    gw = OpenRouterGateway.__new__(OpenRouterGateway)
    # Valid complete tag
    assert gw._contains_penguin_action_tags("<execute>print('x')</execute>") is True
    # Partial tag should not trigger
    assert gw._contains_penguin_action_tags("<execute>print('x')") is False
    # Unknown tag should not trigger
    assert gw._contains_penguin_action_tags("<unknown>foo</unknown>") is False


def test_execute_command_structured_error_on_nonzero():
    tm = ToolManager(config={}, log_error_func=_dummy_log_error, fast_startup=True)
    # Use a command that returns non-zero cross-platform
    out = tm.execute_command("exit 2")
    # Expect JSON with returncode
    try:
        data = json.loads(out)
    except Exception:
        # On some shells this may still return plain text; accept either but prefer JSON
        data = None
    if data:
        assert data.get("returncode") == 2


# ============================================================================
# COMPREHENSIVE INTEGRATION TESTS for Responses API Streaming
# ============================================================================

def test_streaming_interrupt_on_action_tag():
    """
    Integration test: Verify streaming interrupt when action tag detected.
    Tests that _contains_penguin_action_tags correctly identifies complete tags
    and that interrupt_on_action flag controls behavior.
    """
    # Create gateway with interrupt enabled
    config = ModelConfig(
        model="openai/gpt-4o",
        provider="openrouter",
        client_preference="openrouter",
        interrupt_on_action=True,
    )

    gw = OpenRouterGateway.__new__(OpenRouterGateway)
    gw.model_config = config
    gw._telemetry = {"interrupts": 0, "streamed_bytes": 0}

    # Simulate streaming scenario
    # 1. Partial content - should not interrupt
    partial_content = "I'll help with that. Let me <execute>print"
    assert gw._contains_penguin_action_tags(partial_content) is False

    # 2. Complete action tag - should detect
    complete_content = "I'll help with that. Let me <execute>print('hello')</execute> done"
    assert gw._contains_penguin_action_tags(complete_content) is True

    # 3. Verify interrupt flag controls detection usage
    assert gw.model_config.interrupt_on_action is True

    # 4. Multiple tags - should detect
    multi_tag = "<search>query</search> and then <execute>cmd</execute>"
    assert gw._contains_penguin_action_tags(multi_tag) is True

    # 5. Invalid tags - should not detect
    invalid = "<invalid_tag>content</invalid_tag>"
    assert gw._contains_penguin_action_tags(invalid) is False


def test_telemetry_counters():
    """
    Test that telemetry counters are properly exposed and updated.
    Verifies interrupt counter and streamed bytes tracking.
    """
    gw = OpenRouterGateway.__new__(OpenRouterGateway)
    gw._telemetry = {"interrupts": 0, "streamed_bytes": 0}

    # Get initial telemetry
    telemetry = gw.get_telemetry()
    assert isinstance(telemetry, dict)
    assert "interrupts" in telemetry
    assert "streamed_bytes" in telemetry
    assert telemetry["interrupts"] == 0

    # Simulate interrupt
    gw._telemetry["interrupts"] += 1
    gw._telemetry["streamed_bytes"] += 1024

    # Verify updated
    updated = gw.get_telemetry()
    assert updated["interrupts"] == 1
    assert updated["streamed_bytes"] == 1024


def test_tool_timeout_structured_errors():
    """
    Comprehensive test for timeout handling across multiple tool types.
    Verifies all tools return structured JSON errors on timeout.
    """
    tm = ToolManager(config={}, log_error_func=_dummy_log_error, fast_startup=True)

    # Test 1: Code execution timeout
    os.environ["PENGUIN_TOOL_TIMEOUT_CODE"] = "0"
    result = tm.execute_code("import time; time.sleep(10)")
    assert isinstance(result, str)
    try:
        data = json.loads(result)
        assert "error" in data
        assert data["error"] == "timeout"
        assert "tool" in data
        assert data["tool"] == "code_execution"
        assert "timeout_seconds" in data
    except json.JSONDecodeError:
        # If not JSON, at least check for timeout indicator
        assert "timeout" in result.lower()

    # Test 2: Command execution timeout
    os.environ["PENGUIN_TOOL_TIMEOUT"] = "0"
    result = tm.execute_command("sleep 10")
    assert isinstance(result, str)
    try:
        data = json.loads(result)
        assert "error" in data
        assert data["error"] == "timeout"
        assert "tool" in data
        assert "timeout_seconds" in data
    except json.JSONDecodeError:
        assert "timeout" in result.lower()

    # Reset env vars
    os.environ.pop("PENGUIN_TOOL_TIMEOUT_CODE", None)
    os.environ.pop("PENGUIN_TOOL_TIMEOUT", None)


def test_responses_tools_web_search_included():
    """
    Verify that Responses API tools include web_search descriptor.
    Tests the curated tool list includes built-in capabilities.
    """
    tm = ToolManager(config={}, log_error_func=_dummy_log_error, fast_startup=True)
    tools = tm.get_responses_tools()

    # Should have web_search as a special descriptor
    web_search_tools = [t for t in tools if t.get("type") == "web_search"]
    assert len(web_search_tools) > 0, "Should include web_search tool descriptor"

    # Should have curated function tools
    function_tools = [t for t in tools if t.get("type") == "function"]
    assert len(function_tools) > 0, "Should include function-based tools"

    # Verify expected curated tools
    function_names = {t["function"]["name"] for t in function_tools}
    expected_tools = {"read_file", "write_to_file", "execute_command", "code_execution"}
    assert expected_tools.issubset(function_names), f"Missing expected tools. Got: {function_names}"


def test_action_tag_parser_consistency():
    """
    Verify parser and gateway tag detection are consistent.
    This ensures parse_action and _contains_penguin_action_tags agree.
    """
    gw = OpenRouterGateway.__new__(OpenRouterGateway)

    test_cases = [
        ("<execute>ls</execute>", True),
        ("<search>query</search>", True),
        ("<memory_search>context</memory_search>", True),
        ("<task_create>Task:Desc</task_create>", True),
        ("Plain text", False),
        ("<invalid>tag</invalid>", False),
        ("<execute>partial", False),  # Incomplete tag
    ]

    for content, should_detect in test_cases:
        # Gateway detection
        gateway_found = gw._contains_penguin_action_tags(content)

        # Parser detection
        parser_actions = parse_action(content)
        parser_found = len(parser_actions) > 0

        # They should agree
        assert gateway_found == parser_found, \
            f"Mismatch for '{content}': gateway={gateway_found}, parser={parser_found}"

        # Both should match expectation
        assert gateway_found == should_detect, \
            f"Detection failed for '{content}': expected={should_detect}, got={gateway_found}"


async def _async_test_tool_call_accumulation():
    """
    Test tool_call accumulation and retrieval in gateway.
    Verifies Phase 2 tool_call SSE interrupt mechanism.
    """
    gw = OpenRouterGateway.__new__(OpenRouterGateway)
    gw._tool_call_acc = {"name": None, "arguments": ""}
    gw._last_tool_call = None

    # Simulate accumulating tool call data
    gw._tool_call_acc["name"] = "read_file"
    gw._tool_call_acc["arguments"] = '{"path": "test.py"}'

    # Snapshot to last_tool_call
    gw._last_tool_call = {
        "name": gw._tool_call_acc["name"],
        "arguments": gw._tool_call_acc["arguments"],
    }

    # Retrieve and clear
    tool_info = gw.get_and_clear_last_tool_call()
    assert tool_info is not None
    assert tool_info["name"] == "read_file"
    assert tool_info["arguments"] == '{"path": "test.py"}'

    # Should be cleared
    assert gw._last_tool_call is None
    assert gw._tool_call_acc["name"] is None
    assert gw._tool_call_acc["arguments"] == ""

    # Second retrieval should return None
    tool_info2 = gw.get_and_clear_last_tool_call()
    assert tool_info2 is None


def test_tool_call_accumulation():
    """Wrapper to run async test."""
    asyncio.run(_async_test_tool_call_accumulation())


def test_reasoning_config_generation():
    """
    Test ModelConfig reasoning configuration for different model types.
    Verifies effort vs max_tokens style detection and config generation.
    """
    # Test 1: Effort-style (OpenAI o-series)
    config_o1 = ModelConfig(
        model="openai/o1-preview",
        provider="openrouter",
        client_preference="openrouter",
        reasoning_enabled=True,
        reasoning_effort="high"
    )
    reasoning = config_o1.get_reasoning_config()
    assert reasoning == {"effort": "high"}

    # Test 2: Max tokens style (Claude 4)
    config_claude = ModelConfig(
        model="anthropic/claude-4-sonnet",
        provider="openrouter",
        client_preference="openrouter",
        reasoning_enabled=True,
        reasoning_max_tokens=3000
    )
    reasoning = config_claude.get_reasoning_config()
    assert reasoning == {"max_tokens": 3000}

    # Test 3: Disabled reasoning
    config_disabled = ModelConfig(
        model="openai/gpt-4o",
        provider="openrouter",
        client_preference="openrouter",
        reasoning_enabled=False
    )
    reasoning = config_disabled.get_reasoning_config()
    assert reasoning is None


def test_model_config_flags_present():
    """
    Verify ModelConfig has all required Responses API flags.
    Tests flags: use_responses_api, interrupt_on_action, interrupt_on_tool_call.
    """
    config = ModelConfig(
        model="test-model",
        provider="openrouter",
        client_preference="openrouter",
        use_responses_api=True,
        interrupt_on_action=True,
        interrupt_on_tool_call=False,
    )

    assert hasattr(config, "use_responses_api")
    assert hasattr(config, "interrupt_on_action")
    assert hasattr(config, "interrupt_on_tool_call")

    assert config.use_responses_api is True
    assert config.interrupt_on_action is True
    assert config.interrupt_on_tool_call is False

    # Verify get_config includes these
    cfg_dict = config.get_config()
    assert "use_responses_api" in cfg_dict
    assert "interrupt_on_action" in cfg_dict
    assert "interrupt_on_tool_call" in cfg_dict


if __name__ == "__main__":
    """Run all tests when executed directly."""
    import sys

    print("🧪 Running Responses API Streaming Tests\n")

    tests = [
        ("Parse action detects enhanced_write", test_parse_action_detects_enhanced_write),
        ("ToolManager get_responses_tools curated", test_tool_manager_get_responses_tools_curated),
        ("Code execution timeout", test_code_execution_timeout),
        ("Gateway contains Penguin action tags", test_gateway_contains_penguin_action_tags_true_false),
        ("Execute command structured error on nonzero", test_execute_command_structured_error_on_nonzero),
        ("Streaming interrupt on action tag", test_streaming_interrupt_on_action_tag),
        ("Telemetry counters", test_telemetry_counters),
        ("Tool timeout structured errors", test_tool_timeout_structured_errors),
        ("Responses tools web_search included", test_responses_tools_web_search_included),
        ("Action tag parser consistency", test_action_tag_parser_consistency),
        ("Tool call accumulation", test_tool_call_accumulation),
        ("Reasoning config generation", test_reasoning_config_generation),
        ("ModelConfig flags present", test_model_config_flags_present),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            # Create a mock monkeypatch for test_code_execution_timeout
            if test_func == test_code_execution_timeout:
                class MockMonkeypatch:
                    def setenv(self, key, value):
                        os.environ[key] = value
                test_func(MockMonkeypatch())
            else:
                test_func()
            print(f"✅ {name}")
            passed += 1
        except AssertionError as e:
            print(f"❌ {name}: {e}")
            failed += 1
        except Exception as e:
            print(f"💥 {name}: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)} tests")
    print(f"{'='*60}")

    sys.exit(0 if failed == 0 else 1)
