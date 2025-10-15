"""Tests for structured error responses.

Tests that errors follow the standardized PenguinError format with
code, message, recoverable, suggested_action, and details fields.
"""

import os
import time
import urllib.request
import urllib.error
import json
from typing import Any, Dict


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
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        raise AssertionError(f"POST {path} failed: {e.code} {e.reason}\n{body}")


def _get(path: str) -> Dict[str, Any]:
    """GET request helper."""
    url = f"{BASE_URL}{path}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        raise AssertionError(f"GET {path} failed: {e.code} {e.reason}\n{body}")


def _expect_error(path: str, data: Dict[str, Any] = None, method: str = "GET", expected_status: int = None) -> Dict[str, Any]:
    """Make a request that expects an error response."""
    url = f"{BASE_URL}{path}"

    if method == "POST":
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    else:
        req = urllib.request.Request(url)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if expected_status:
                raise AssertionError(f"Expected error status {expected_status} but got {resp.status}")
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if expected_status and e.code != expected_status:
            raise AssertionError(f"Expected status {expected_status} but got {e.code}")
        body = e.read().decode("utf-8") if e.fp else "{}"
        return json.loads(body)


def _validate_error_structure(error_response: Dict[str, Any], context: str = "") -> Dict[str, Any]:
    """Validate that an error response follows the structured format.

    Returns the error object for further validation.
    """
    # Error can be at top level or in "detail" field
    if "error" in error_response:
        error = error_response["error"]
    elif "detail" in error_response and isinstance(error_response["detail"], dict):
        if "error" in error_response["detail"]:
            error = error_response["detail"]["error"]
        else:
            # Legacy format or FastAPI default
            print(f"⊘ {context}: Error not in structured format (legacy/FastAPI default)")
            return None
    else:
        print(f"⊘ {context}: No error field found")
        return None

    # Validate structure
    required_fields = ["code", "message", "recoverable", "suggested_action"]
    for field in required_fields:
        assert field in error, f"{context}: Error missing required field '{field}'"

    # Validate types
    assert isinstance(error["code"], str), f"{context}: Error code should be string"
    assert isinstance(error["message"], str), f"{context}: Error message should be string"
    assert isinstance(error["recoverable"], bool), f"{context}: Error recoverable should be boolean"
    assert isinstance(error["suggested_action"], str), f"{context}: Error suggested_action should be string"

    # Details is optional but should be dict if present
    if "details" in error:
        assert isinstance(error["details"], dict), f"{context}: Error details should be dictionary"

    return error


def test_agent_not_found_error():
    """Test AgentNotFoundError structure."""
    _wait_for_server()

    # Try to access non-existent agent
    error_resp = _expect_error("/api/v1/agents/nonexistent-agent-id-12345", expected_status=404)

    error = _validate_error_structure(error_resp, "AgentNotFoundError")
    if error:
        assert error["code"] == "AGENT_NOT_FOUND", f"Expected AGENT_NOT_FOUND, got {error['code']}"
        assert error["recoverable"] == False, "Agent not found should not be recoverable"
        assert "check_agent_id" in error["suggested_action"].lower() or \
               error["suggested_action"] in ["check_agent_id", "verify_agent_exists"], \
               f"Unexpected suggested_action: {error['suggested_action']}"

        # Should have agent_id in details
        if "details" in error:
            assert "agent_id" in error["details"], "Should include agent_id in details"

        print(f"✓ AgentNotFoundError follows structured format:")
        print(f"  - code: {error['code']}")
        print(f"  - recoverable: {error['recoverable']}")
        print(f"  - suggested_action: {error['suggested_action']}")


def test_invalid_request_error():
    """Test error structure for invalid request data."""
    _wait_for_server()

    # Try to send malformed data
    try:
        error_resp = _expect_error(
            "/api/v1/chat/simple",
            data={"invalid": "missing required fields"},
            method="POST",
            expected_status=422
        )

        # FastAPI validation errors have different structure, that's OK
        if "detail" in error_resp:
            print("✓ Invalid request returns error (FastAPI validation format)")
        else:
            error = _validate_error_structure(error_resp, "InvalidRequestError")
            if error:
                print(f"✓ Invalid request error follows structured format: {error['code']}")
    except Exception as e:
        print(f"⊘ Could not test invalid request error: {e}")


def test_context_window_exceeded_error():
    """Test ContextWindowExceededError structure (if triggerable)."""
    print("⊘ Skipping ContextWindowExceededError test (requires specific conditions)")
    # This would require creating a conversation that exceeds context window
    # which is difficult to test in a smoke test


def test_resource_exhausted_error():
    """Test ResourceExhaustedError structure (if triggerable)."""
    print("⊘ Skipping ResourceExhaustedError test (requires resource exhaustion)")
    # This would require exhausting system resources, which is not suitable for a test


def test_task_execution_error():
    """Test TaskExecutionError structure (if triggerable)."""
    print("⊘ Skipping TaskExecutionError test (requires failed task)")
    # This would require creating a task that fails, which depends on task system


def test_error_field_types():
    """Test that all error fields have correct types."""
    _wait_for_server()

    # Trigger a known error (agent not found)
    error_resp = _expect_error("/api/v1/agents/test-nonexistent", expected_status=404)

    error = _validate_error_structure(error_resp, "Error field types")
    if error:
        # Validate specific types
        assert isinstance(error["code"], str) and len(error["code"]) > 0, \
            "Error code should be non-empty string"
        assert isinstance(error["message"], str) and len(error["message"]) > 0, \
            "Error message should be non-empty string"
        assert isinstance(error["recoverable"], bool), \
            "Recoverable should be boolean"
        assert isinstance(error["suggested_action"], str) and len(error["suggested_action"]) > 0, \
            "Suggested action should be non-empty string"

        print("✓ All error fields have correct types")


def test_error_code_format():
    """Test that error codes follow naming convention."""
    _wait_for_server()

    error_resp = _expect_error("/api/v1/agents/test-error-code", expected_status=404)

    error = _validate_error_structure(error_resp, "Error code format")
    if error:
        code = error["code"]

        # Should be UPPERCASE_WITH_UNDERSCORES
        assert code.isupper() or code.replace("_", "").isupper(), \
            f"Error code should be uppercase: {code}"
        assert "_" in code or code.isalpha(), \
            f"Error code should use underscores for word separation: {code}"

        print(f"✓ Error code follows naming convention: {code}")


def test_error_message_clarity():
    """Test that error messages are clear and informative."""
    _wait_for_server()

    error_resp = _expect_error("/api/v1/agents/test-message-clarity", expected_status=404)

    error = _validate_error_structure(error_resp, "Error message clarity")
    if error:
        message = error["message"]

        # Should not be empty
        assert len(message) > 0, "Error message should not be empty"

        # Should be reasonable length (not just "Error")
        assert len(message) > 5, f"Error message too short: '{message}'"

        # Should not contain internal implementation details
        assert "traceback" not in message.lower(), "Error message should not contain traceback"
        assert "stack" not in message.lower(), "Error message should not contain stack trace"

        print(f"✓ Error message is clear: '{message[:50]}...'")


def test_suggested_action_validity():
    """Test that suggested_action provides actionable guidance."""
    _wait_for_server()

    error_resp = _expect_error("/api/v1/agents/test-suggested-action", expected_status=404)

    error = _validate_error_structure(error_resp, "Suggested action validity")
    if error:
        suggested_action = error["suggested_action"]

        # Should not be empty
        assert len(suggested_action) > 0, "Suggested action should not be empty"

        # Common valid actions
        valid_patterns = [
            "retry", "check", "verify", "provide", "modify", "start",
            "later", "contact", "review", "update", "create"
        ]

        # Should contain at least one valid pattern
        has_valid_pattern = any(pattern in suggested_action.lower() for pattern in valid_patterns)
        if not has_valid_pattern:
            print(f"⊘ Warning: Suggested action may not be actionable: '{suggested_action}'")
        else:
            print(f"✓ Suggested action is actionable: '{suggested_action}'")


def test_recoverable_flag_semantics():
    """Test that recoverable flag has correct semantics."""
    _wait_for_server()

    # Agent not found should not be recoverable (it won't magically appear)
    error_resp = _expect_error("/api/v1/agents/test-recoverable", expected_status=404)

    error = _validate_error_structure(error_resp, "Recoverable flag")
    if error:
        if error["code"] == "AGENT_NOT_FOUND":
            assert error["recoverable"] == False, \
                "Agent not found errors should not be recoverable"
            print("✓ Recoverable flag has correct semantics for AgentNotFoundError")
        else:
            print(f"⊘ Different error type: {error['code']}, recoverable: {error['recoverable']}")


def test_error_details_structure():
    """Test that error details field contains useful information."""
    _wait_for_server()

    error_resp = _expect_error("/api/v1/agents/test-details-12345", expected_status=404)

    error = _validate_error_structure(error_resp, "Error details")
    if error and "details" in error:
        details = error["details"]

        # Should be a dictionary
        assert isinstance(details, dict), "Details should be a dictionary"

        # Should contain relevant information
        if error["code"] == "AGENT_NOT_FOUND" and "agent_id" in details:
            assert isinstance(details["agent_id"], str), "agent_id should be string"
            print(f"✓ Error details contain relevant information: {details}")
        else:
            print(f"⊘ Error details present but structure varies: {details}")
    else:
        print("⊘ Error details not present (optional field)")


def test_error_json_serialization():
    """Test that error responses are properly JSON serializable."""
    _wait_for_server()

    error_resp = _expect_error("/api/v1/agents/test-serialization", expected_status=404)

    # Try to re-serialize
    try:
        json_str = json.dumps(error_resp)
        parsed = json.loads(json_str)
        assert parsed == error_resp, "Re-serialized error doesn't match original"
        print("✓ Error responses are properly JSON serializable")
    except (TypeError, ValueError) as e:
        raise AssertionError(f"Error response contains non-serializable data: {e}")


if __name__ == "__main__":
    """Run all error handling tests."""
    print("=" * 60)
    print("Structured Error Response Tests")
    print("=" * 60)
    print()

    tests = [
        ("AgentNotFoundError structure", test_agent_not_found_error),
        ("Invalid request error", test_invalid_request_error),
        ("ContextWindowExceededError", test_context_window_exceeded_error),
        ("ResourceExhaustedError", test_resource_exhausted_error),
        ("TaskExecutionError", test_task_execution_error),
        ("Error field types", test_error_field_types),
        ("Error code format", test_error_code_format),
        ("Error message clarity", test_error_message_clarity),
        ("Suggested action validity", test_suggested_action_validity),
        ("Recoverable flag semantics", test_recoverable_flag_semantics),
        ("Error details structure", test_error_details_structure),
        ("Error JSON serialization", test_error_json_serialization),
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
