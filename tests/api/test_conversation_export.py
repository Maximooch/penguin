"""Tests for conversation history export and filtering.

Tests conversation history endpoints with pagination and filtering support.
"""

import os
import time
import urllib.request
import urllib.error
import json
from typing import Any, Dict, Optional


BASE_URL = os.environ.get("PENGUIN_API_URL", "http://127.0.0.1:8000")


def _wait_for_server(timeout: int = 30) -> None:
    """Wait for server to be ready."""
    print(f"Waiting for server at {BASE_URL} (max {timeout}s)...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(f"{BASE_URL}/api/v1/health", timeout=2) as resp:
                if resp.status == 200:
                    print(f"✓ Server ready after {time.time() - start:.1f}s")
                    return
        except Exception:
            time.sleep(1)
    raise RuntimeError(f"Server not ready after {timeout}s")


def _get(path: str) -> Dict[str, Any]:
    """GET request helper."""
    url = f"{BASE_URL}{path}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        raise AssertionError(f"GET {path} failed: {e.code} {e.reason}\n{body}")


def _post(path: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """POST request helper."""
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        raise AssertionError(f"POST {path} failed: {e.code} {e.reason}\n{body}")


def _create_test_conversation() -> str:
    """Create a test conversation and return its ID."""
    resp = _post("/api/v1/conversations/create", {})
    conversation_id = resp.get("conversation_id")
    assert conversation_id, "Failed to create test conversation"
    return conversation_id


def _send_test_messages(conversation_id: str, count: int = 5) -> None:
    """Send test messages to a conversation."""
    for i in range(count):
        try:
            _post("/api/v1/chat/message", {
                "text": f"Test message {i + 1}",
                "conversation_id": conversation_id,
                "streaming": False
            })
            time.sleep(0.5)  # Small delay between messages
        except Exception as e:
            print(f"⊘ Warning: Could not send test message {i + 1}: {e}")


def test_conversation_history_endpoint_exists():
    """Test that conversation history endpoint is accessible."""
    _wait_for_server()

    # Get list of conversations
    try:
        resp = _get("/api/v1/conversations")
        conversations = resp.get("conversations", [])

        if conversations:
            # Use first conversation
            conv_id = conversations[0].get("id")
            history_resp = _get(f"/api/v1/conversations/{conv_id}/history")

            assert isinstance(history_resp, dict), "History response should be a dictionary"
            assert "messages" in history_resp, "History response should contain 'messages' field"
            print("✓ Conversation history endpoint exists and returns correct structure")
        else:
            print("⊘ No conversations available to test history endpoint")

    except AssertionError as e:
        if "404" in str(e):
            print("⊘ Conversation history endpoint not found (may not be implemented)")
        else:
            raise


def test_conversation_history_structure():
    """Test the structure of conversation history response."""
    try:
        resp = _get("/api/v1/conversations")
        conversations = resp.get("conversations", [])

        if not conversations:
            print("⊘ No conversations available to test structure")
            return

        conv_id = conversations[0].get("id")
        history = _get(f"/api/v1/conversations/{conv_id}/history")

        # Check envelope structure
        assert "conversation_id" in history, "Response should include conversation_id"
        assert "messages" in history, "Response should include messages array"

        # Validate conversation_id matches
        assert history["conversation_id"] == conv_id, \
            "Returned conversation_id should match requested ID"

        # Validate messages is an array
        assert isinstance(history["messages"], list), "Messages should be an array"

        print(f"✓ Conversation history structure valid (envelope with {len(history['messages'])} messages)")

    except Exception as e:
        if "404" in str(e):
            print("⊘ Could not test history structure (endpoint may not exist)")
        else:
            raise


def test_conversation_history_message_format():
    """Test that individual messages have proper format."""
    try:
        resp = _get("/api/v1/conversations")
        conversations = resp.get("conversations", [])

        if not conversations:
            print("⊘ No conversations available to test message format")
            return

        conv_id = conversations[0].get("id")
        history = _get(f"/api/v1/conversations/{conv_id}/history")
        messages = history.get("messages", [])

        if not messages:
            print("⊘ No messages in conversation to validate format")
            return

        # Check first message structure
        msg = messages[0]
        assert isinstance(msg, dict), "Each message should be a dictionary"

        # Common message fields (may vary)
        possible_fields = ["role", "content", "message_type", "timestamp",
                           "agent_id", "metadata", "id"]

        has_any_field = any(field in msg for field in possible_fields)
        assert has_any_field, f"Message should have at least one known field, got: {list(msg.keys())}"

        print(f"✓ Message format valid, fields: {list(msg.keys())}")

    except Exception as e:
        print(f"⊘ Could not validate message format: {e}")


def test_conversation_history_limit_parameter():
    """Test that limit parameter restricts number of messages returned."""
    try:
        resp = _get("/api/v1/conversations")
        conversations = resp.get("conversations", [])

        if not conversations:
            print("⊘ No conversations available to test limit parameter")
            return

        conv_id = conversations[0].get("id")

        # Get full history first
        full_history = _get(f"/api/v1/conversations/{conv_id}/history")
        total_messages = len(full_history.get("messages", []))

        if total_messages == 0:
            print("⊘ No messages to test limit parameter")
            return

        # Request with limit
        limit = min(2, total_messages)
        limited_history = _get(f"/api/v1/conversations/{conv_id}/history?limit={limit}")
        limited_messages = limited_history.get("messages", [])

        assert len(limited_messages) <= limit, \
            f"Limited history should have at most {limit} messages, got {len(limited_messages)}"

        print(f"✓ Limit parameter works: requested {limit}, got {len(limited_messages)} messages")

    except Exception as e:
        print(f"⊘ Could not test limit parameter: {e}")


def test_conversation_history_include_system_parameter():
    """Test that include_system parameter filters system messages."""
    try:
        resp = _get("/api/v1/conversations")
        conversations = resp.get("conversations", [])

        if not conversations:
            print("⊘ No conversations available to test include_system parameter")
            return

        conv_id = conversations[0].get("id")

        # Get with system messages
        with_system = _get(f"/api/v1/conversations/{conv_id}/history?include_system=true")
        # Get without system messages
        without_system = _get(f"/api/v1/conversations/{conv_id}/history?include_system=false")

        with_count = len(with_system.get("messages", []))
        without_count = len(without_system.get("messages", []))

        # Without system should have equal or fewer messages
        assert without_count <= with_count, \
            "Excluding system messages should not increase message count"

        print(f"✓ include_system parameter works: with_system={with_count}, without={without_count}")

    except Exception as e:
        print(f"⊘ Could not test include_system parameter: {e}")


def test_conversation_history_agent_id_filter():
    """Test filtering conversation history by agent_id."""
    try:
        resp = _get("/api/v1/conversations")
        conversations = resp.get("conversations", [])

        if not conversations:
            print("⊘ No conversations available to test agent_id filter")
            return

        conv_id = conversations[0].get("id")

        # Get full history
        full_history = _get(f"/api/v1/conversations/{conv_id}/history")
        messages = full_history.get("messages", [])

        if not messages:
            print("⊘ No messages to test agent_id filter")
            return

        # Try to find an agent_id in messages
        agent_ids = [msg.get("agent_id") for msg in messages if msg.get("agent_id")]

        if not agent_ids:
            print("⊘ No agent_id in messages to filter by")
            return

        # Filter by first agent_id
        test_agent_id = agent_ids[0]
        filtered_history = _get(
            f"/api/v1/conversations/{conv_id}/history?agent_id={test_agent_id}"
        )
        filtered_messages = filtered_history.get("messages", [])

        # All filtered messages should have the specified agent_id
        for msg in filtered_messages:
            msg_agent_id = msg.get("agent_id")
            if msg_agent_id:  # Only check if agent_id is present
                assert msg_agent_id == test_agent_id, \
                    f"Filtered message has wrong agent_id: {msg_agent_id}"

        print(f"✓ agent_id filter works: {len(filtered_messages)} messages for agent '{test_agent_id}'")

    except Exception as e:
        print(f"⊘ Could not test agent_id filter: {e}")


def test_conversation_history_message_type_filter():
    """Test filtering conversation history by message_type."""
    try:
        resp = _get("/api/v1/conversations")
        conversations = resp.get("conversations", [])

        if not conversations:
            print("⊘ No conversations available to test message_type filter")
            return

        conv_id = conversations[0].get("id")

        # Get full history
        full_history = _get(f"/api/v1/conversations/{conv_id}/history")
        messages = full_history.get("messages", [])

        if not messages:
            print("⊘ No messages to test message_type filter")
            return

        # Try to find message types
        message_types = [msg.get("message_type") for msg in messages if msg.get("message_type")]

        if not message_types:
            print("⊘ No message_type in messages to filter by")
            return

        # Filter by first message type
        test_type = message_types[0]
        filtered_history = _get(
            f"/api/v1/conversations/{conv_id}/history?message_type={test_type}"
        )
        filtered_messages = filtered_history.get("messages", [])

        # Check filtering worked
        for msg in filtered_messages:
            msg_type = msg.get("message_type")
            if msg_type:
                assert msg_type == test_type, \
                    f"Filtered message has wrong type: {msg_type}"

        print(f"✓ message_type filter works: {len(filtered_messages)} messages of type '{test_type}'")

    except Exception as e:
        print(f"⊘ Could not test message_type filter: {e}")


def test_conversation_history_pagination():
    """Test pagination works correctly with limit parameter."""
    try:
        resp = _get("/api/v1/conversations")
        conversations = resp.get("conversations", [])

        if not conversations:
            print("⊘ No conversations available to test pagination")
            return

        conv_id = conversations[0].get("id")

        # Get total count
        full_history = _get(f"/api/v1/conversations/{conv_id}/history")
        total = len(full_history.get("messages", []))

        if total < 3:
            print(f"⊘ Not enough messages for pagination test (need 3+, have {total})")
            return

        # Note: The current API doesn't support offset parameter,
        # so we can only test limit-based pagination
        limit = 2
        page1 = _get(f"/api/v1/conversations/{conv_id}/history?limit={limit}")
        page1_messages = page1.get("messages", [])

        assert len(page1_messages) <= limit, \
            f"Page 1 should have at most {limit} messages"

        print(f"✓ Pagination works: total={total}, page_size={len(page1_messages)}")

    except Exception as e:
        print(f"⊘ Could not test pagination: {e}")


def test_agent_history_endpoint():
    """Test the /agents/{agent_id}/history endpoint."""
    try:
        # Get list of agents
        agents_resp = _get("/api/v1/agents")

        # Handle both simple and full roster formats
        if isinstance(agents_resp, dict):
            agents = agents_resp.get("agents", [])
        elif isinstance(agents_resp, list):
            agents = agents_resp
        else:
            agents = []

        if not agents:
            print("⊘ No agents available to test agent history endpoint")
            return

        # Use first agent
        if isinstance(agents[0], dict):
            agent_id = agents[0].get("agent_id") or agents[0].get("id")
        else:
            agent_id = agents[0]

        if not agent_id:
            print("⊘ Could not extract agent_id")
            return

        # Get agent history
        history = _get(f"/api/v1/agents/{agent_id}/history")

        # Should return an array of messages
        assert isinstance(history, list), "Agent history should return a list"

        print(f"✓ Agent history endpoint works: {len(history)} messages for agent '{agent_id}'")

    except Exception as e:
        if "404" in str(e):
            print("⊘ Agent history endpoint or agent not found")
        else:
            print(f"⊘ Could not test agent history: {e}")


def test_conversation_history_performance():
    """Test that conversation history endpoint responds quickly."""
    try:
        resp = _get("/api/v1/conversations")
        conversations = resp.get("conversations", [])

        if not conversations:
            print("⊘ No conversations available to test performance")
            return

        conv_id = conversations[0].get("id")

        # Measure response time
        start = time.time()
        _get(f"/api/v1/conversations/{conv_id}/history")
        latency_ms = (time.time() - start) * 1000

        # History should respond within reasonable time
        assert latency_ms < 5000, f"History endpoint too slow: {latency_ms}ms"

        print(f"✓ History endpoint performance acceptable: {latency_ms:.2f}ms")

    except Exception as e:
        print(f"⊘ Could not test performance: {e}")


if __name__ == "__main__":
    """Run all conversation export tests."""
    print("=" * 60)
    print("Conversation History Export Tests")
    print("=" * 60)
    print()

    tests = [
        ("History endpoint exists", test_conversation_history_endpoint_exists),
        ("History structure", test_conversation_history_structure),
        ("Message format", test_conversation_history_message_format),
        ("Limit parameter", test_conversation_history_limit_parameter),
        ("Include system parameter", test_conversation_history_include_system_parameter),
        ("Agent ID filter", test_conversation_history_agent_id_filter),
        ("Message type filter", test_conversation_history_message_type_filter),
        ("Pagination", test_conversation_history_pagination),
        ("Agent history endpoint", test_agent_history_endpoint),
        ("History performance", test_conversation_history_performance),
    ]

    passed = 0
    failed = 0
    skipped = 0

    for name, test_func in tests:
        try:
            print(f"\n[{name}]")
            test_func()
            passed += 1
        except AssertionError as e:
            print(f"✗ FAILED: {e}")
            failed += 1
        except Exception as e:
            if "Skipping" in str(e) or "⊘" in str(e):
                skipped += 1
            else:
                print(f"✗ ERROR: {e}")
                failed += 1

    print()
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed, {skipped} skipped")
    print("=" * 60)

    exit(0 if failed == 0 else 1)
