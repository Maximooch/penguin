"""Phase 1.5 API tests for tool usage.

Verifies that the API correctly invokes tools when needed and returns tool results.
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


def _post(path: str, data: Dict[str, Any], timeout: int = 120) -> Dict[str, Any]:
    """POST request helper with longer timeout for tool-using requests."""
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        raise AssertionError(f"POST {path} failed: {e.code} {e.reason}\n{body}")


def test_chat_with_web_tool():
    """Test that web/browser tools are used when asking about a URL."""
    resp = _post(
        "/api/v1/chat/message",
        {
            "text": "What does the first paragraph say on https://en.wikipedia.org/wiki/Penguin? Be concise.",
            "max_iterations": 5,
        },
        timeout=120,
    )
    
    # Should have response
    response_text = resp.get("response") or resp.get("assistant_response", "")
    assert len(response_text) > 20, f"Response too short: {response_text}"
    
    # Check for tool usage in action_results
    action_results = resp.get("action_results", [])
    print(f"\nReceived {len(action_results)} action results")
    
    # At least one tool should have been used
    assert len(action_results) > 0, "Expected tool usage but got no action_results"
    
    # Check if web-related tools were used (check both "action" and "action_name")
    tool_names = [
        (ar.get("action") or ar.get("action_name", "")).lower() 
        for ar in action_results 
        if isinstance(ar, dict)
    ]
    
    has_web_tool = any(
        "web" in name or "fetch" in name or "browser" in name or "navigate" in name or "screenshot" in name
        for name in tool_names
    )
    
    assert has_web_tool, f"Expected web/fetch/browser tool usage, got: {tool_names}"
    
    # Response should mention something about penguins or birds
    response_lower = response_text.lower()
    assert (
        "penguin" in response_lower or "bird" in response_lower or "flightless" in response_lower
    ), f"Expected penguin-related content in response: {response_text[:300]}"
    
    print(f"✓ Tool usage test: {len(action_results)} tools used, response mentions penguins")
    print(f"  Tools: {tool_names}")
    print(f"  Response preview: {response_text[:200]}...")


def test_chat_with_code_tool():
    """Test that code execution tools work."""
    resp = _post(
        "/api/v1/chat/message",
        {
            "text": "Create a Python variable called test_var with the value 42, then print it. Show me the output.",
            "max_iterations": 3,
        },
        timeout=60,
    )
    
    response_text = resp.get("response") or resp.get("assistant_response", "")
    action_results = resp.get("action_results", [])
    
    print(f"\nReceived {len(action_results)} action results")
    
    # Should have used some tool (execute, write, etc.)
    assert len(action_results) > 0, "Expected tool usage for code execution"
    
    # Response or action results should mention 42
    full_text = response_text + " " + str(action_results)
    assert "42" in full_text, f"Expected '42' in response or results: {full_text[:300]}"
    
    print(f"✓ Code tool test: {len(action_results)} tools used, output contains 42")


if __name__ == "__main__":
    import sys

    print(f"\nRunning Phase 1.5 tool usage tests against {BASE_URL}\n")
    
    # Wait for server
    try:
        _wait_for_server()
    except RuntimeError as e:
        print(f"✗ {e}")
        sys.exit(1)
    
    print()
    tests = [
        test_chat_with_web_tool,
        test_chat_with_code_tool,
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
