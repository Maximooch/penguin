"""Priority 1 API smoke tests for Penguin web API.

These tests verify basic endpoints that don't require complex setup or API keys.
Run against a live container or local server.
"""

import os
import urllib.request
import urllib.error
import json
from typing import Any, Dict


BASE_URL = os.environ.get("PENGUIN_API_URL", "http://127.0.0.1:8000")


def _get(path: str) -> Dict[str, Any]:
    """GET request helper."""
    url = f"{BASE_URL}{path}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise AssertionError(f"GET {path} failed: {e.code} {e.reason}")


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
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise AssertionError(f"POST {path} failed: {e.code} {e.reason}")


def test_health():
    """Test GET /api/v1/health."""
    resp = _get("/api/v1/health")
    assert resp.get("status") == "healthy", f"Expected healthy status, got {resp}"
    print(f"✓ /api/v1/health: {resp}")


def test_capabilities():
    """Test GET /api/v1/capabilities."""
    resp = _get("/api/v1/capabilities")
    assert "capabilities" in resp, "Missing capabilities field"
    assert "api_version" in resp, "Missing api_version field"
    assert resp["api_version"] == "v1", f"Expected v1, got {resp['api_version']}"
    print(f"✓ /api/v1/capabilities: {len(resp['capabilities'])} capabilities")


def test_system_status():
    """Test GET /api/v1/system/status."""
    resp = _get("/api/v1/system/status")
    assert "status" in resp, "Missing status field"
    print(f"✓ /api/v1/system/status: {resp.get('status')}")


def test_conversations_list():
    """Test GET /api/v1/conversations."""
    resp = _get("/api/v1/conversations")
    # Should return a list (may be empty)
    assert isinstance(resp, (list, dict)), f"Expected list or dict, got {type(resp)}"
    if isinstance(resp, dict) and "conversations" in resp:
        convs = resp["conversations"]
    else:
        convs = resp
    print(f"✓ /api/v1/conversations: {len(convs)} conversation(s)")


def test_create_conversation():
    """Test POST /api/v1/conversations/create."""
    resp = _post("/api/v1/conversations/create", {"name": "test-conv"})
    # Should return conversation_id or similar
    assert (
        "conversation_id" in resp or "id" in resp
    ), f"Missing conversation ID in response: {resp}"
    conv_id = resp.get("conversation_id") or resp.get("id")
    print(f"✓ /api/v1/conversations/create: created {conv_id}")


if __name__ == "__main__":
    import sys

    print(f"\nRunning Priority 1 API smoke tests against {BASE_URL}\n")
    tests = [
        test_health,
        test_capabilities,
        test_system_status,
        test_conversations_list,
        test_create_conversation,
    ]
    failed = 0
    for test_fn in tests:
        try:
            test_fn()
        except Exception as e:
            print(f"✗ {test_fn.__name__}: {e}")
            failed += 1

    print(f"\n{len(tests) - failed}/{len(tests)} tests passed")
    sys.exit(0 if failed == 0 else 1)
