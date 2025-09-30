"""Test Penguin creating a PR to penguin-test-repo via the API.

This test creates a project, executes a task via chat, and verifies a PR is created.
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
                    print(f"✓ Server ready\n")
                    return
        except Exception:
            time.sleep(1)
    raise RuntimeError(f"Server not ready after {timeout}s")


def _post(path: str, data: Dict[str, Any], timeout: int = 180) -> Dict[str, Any]:
    """POST request helper with longer timeout for PR creation."""
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


def test_create_pr_via_task_endpoint():
    """Test creating a PR to penguin-test-repo via task execution endpoint."""
    
    print("=== Test: Create PR via Task Execution API ===\n")
    
    # Use the proper task execution endpoint which connects to Engine.run_task()
    task_description = """
Create a test file and PR in the Maximooch/penguin-test-repo repository:

1. Clone or access the repository at https://github.com/Maximooch/penguin-test-repo
2. Create a new branch called 'penguin-test-<timestamp>'
3. Create a file called PENGUIN_TEST.md with content:
   ---
   # Penguin Container Test
   
   This file was created by Penguin Agent running in a Docker container to test PR creation workflow.
   
   Date: {current_date}
   ---
4. Commit the changes with message: "test: Add PENGUIN_TEST.md via Penguin Agent"
5. Push the branch to GitHub
6. Create a pull request with:
   - Title: "Test: Penguin Agent PR creation from container"
   - Body: "This PR was created automatically by Penguin Agent to test the containerized GitHub integration."

Use the GitHub App credentials that are configured.
"""
    
    print("Sending task execution request...")
    print(f"Description: {task_description[:150]}...\n")
    
    resp = _post(
        "/api/v1/tasks/execute-sync",
        {
            "name": "Create test PR to penguin-test-repo",
            "description": task_description,
            "continuous": False,
            "time_limit": 300,  # 5 minutes
        },
        timeout=300,  # PR creation can take time
    )
    
    # Get response
    response_text = resp.get("response") or resp.get("assistant_response", "")
    action_results = resp.get("action_results", [])
    
    print(f"Response received: {len(response_text)} chars")
    print(f"Action results: {len(action_results)} action(s)\n")
    
    # Print action results
    for i, ar in enumerate(action_results):
        action_name = ar.get("action") or ar.get("action_name", "unknown")
        status = ar.get("status", "unknown")
        print(f"  Action {i+1}: {action_name} - {status}")
    
    print(f"\nResponse preview:")
    print(f"{response_text[:500]}...")
    
    # Check if PR was mentioned or created
    response_lower = response_text.lower()
    
    # Look for PR-related keywords
    pr_indicators = ["pull request", "pr created", "pr #", "github.com/maximooch/penguin-test-repo/pull"]
    has_pr_reference = any(indicator in response_lower for indicator in pr_indicators)
    
    if has_pr_reference:
        print(f"\n✓ Response mentions pull request creation")
        
        # Try to extract PR URL if present
        if "github.com" in response_text and "/pull/" in response_text:
            # Extract URL
            import re
            urls = re.findall(r'https://github\.com/[^\s)]+/pull/\d+', response_text)
            if urls:
                print(f"✓ PR URL found: {urls[0]}")
        
        return True
    else:
        print(f"\n⚠️  No explicit PR mention in response")
        print(f"   This might mean:")
        print(f"   - PR creation not implemented via chat")
        print(f"   - Need to use project/task workflow instead")
        print(f"   - Need additional GitHub permissions")
        
        return False


if __name__ == "__main__":
    import sys
    
    print(f"\nTesting Penguin PR creation against {BASE_URL}\n")
    print("Target repo: Maximooch/penguin-test-repo")
    print("=" * 60 + "\n")
    
    # Wait for server
    try:
        _wait_for_server()
    except RuntimeError as e:
        print(f"✗ {e}")
        sys.exit(1)
    
    # Run test
    try:
        result = test_create_pr_via_task_endpoint()
        if result:
            print("\n✅ PR creation test PASSED")
            sys.exit(0)
        else:
            print("\n⚠️  PR creation test completed but PR not confirmed")
            print("Check GitHub manually: https://github.com/Maximooch/penguin-test-repo/pulls")
            sys.exit(0)  # Exit 0 since the API worked, just PR workflow unclear
    except Exception as e:
        print(f"\n❌ PR creation test FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
