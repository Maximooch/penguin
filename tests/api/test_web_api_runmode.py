"""Phase 1.5 API tests for run mode execution.

Verifies that task execution endpoints work via RunMode and Engine.
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
    """POST request helper."""
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


def test_task_execute_background():
    """Test POST /api/v1/tasks/execute for background task execution."""
    resp = _post(
        "/api/v1/tasks/execute",
        {
            "name": "Simple math task",
            "description": "Calculate 10 + 20 and respond with the answer",
            "continuous": False,
            "time_limit": 60,
        },
    )
    
    # Should return task status
    assert "status" in resp or "task_id" in resp, f"Missing status/task_id: {resp}"
    
    status = resp.get("status", "unknown")
    print(f"✓ /api/v1/tasks/execute: task started with status '{status}'")


def test_task_execute_sync():
    """Test POST /api/v1/tasks/execute-sync for synchronous execution."""
    resp = _post(
        "/api/v1/tasks/execute-sync",
        {
            "name": "Simple greeting",
            "description": "Say hello and nothing else",
            "continuous": False,
            "time_limit": 60,
        },
        timeout=90,
    )
    
    # Should return response
    assert "response" in resp or "status" in resp, f"Missing response/status: {resp.keys()}"
    
    response_text = resp.get("response", "")
    iterations = resp.get("iterations", 0)
    
    assert len(response_text) > 0 or resp.get("status") == "completed", "No response or completion status"
    
    print(f"✓ /api/v1/tasks/execute-sync: completed in {iterations} iteration(s)")
    if response_text:
        print(f"  Response preview: {response_text[:100]}...")


if __name__ == "__main__":
    import sys

    print(f"\nRunning Phase 1.5 run mode tests against {BASE_URL}\n")
    
    # Wait for server
    try:
        _wait_for_server()
    except RuntimeError as e:
        print(f"✗ {e}")
        sys.exit(1)
    
    print()
    tests = [
        test_task_execute_background,
        test_task_execute_sync,
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
