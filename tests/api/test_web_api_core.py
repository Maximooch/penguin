"""Priority 1 API tests for chat and project management.

These tests require API keys (e.g., OPENAI_API_KEY) to be configured.
Run against a live container or local server with proper env vars.
"""

import os
import time
import urllib.request
import urllib.error
import json
import uuid
from typing import Any, Dict
import pytest


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


# --- Chat Tests ---


def test_chat_message_simple():
    """Test POST /api/v1/chat/message with a simple query."""
    resp = _post("/api/v1/chat/message", {"text": "Hello, what is 2+2?"})
    
    # Should have a response field (or assistant_response)
    assert (
        "response" in resp or "assistant_response" in resp
    ), f"Missing response field: {resp.keys()}"
    
    response_text = resp.get("response") or resp.get("assistant_response")
    assert response_text, "Response text is empty"
    assert len(response_text) > 10, f"Response too short ({len(response_text)} chars), likely not a real LLM response: {response_text}"
    
    # Check if response contains something about 4 (the answer to 2+2)
    response_lower = response_text.lower()
    assert "4" in response_text or "four" in response_lower, f"Expected answer to contain '4', got: {response_text[:200]}"
    
    print(f"✓ /api/v1/chat/message: received {len(response_text)} chars, contains expected answer")


def test_chat_message_with_context():
    """Test POST /api/v1/chat/message with context."""
    resp = _post(
        "/api/v1/chat/message",
        {
            "text": "What is the capital of France?",
            "context": {"user": "test"},
            "max_iterations": 1,
        },
    )
    
    response_text = resp.get("response") or resp.get("assistant_response", "")
    assert len(response_text) > 10, f"Response too short, likely not a real LLM response: {response_text}"
    
    # Check if response mentions Paris
    response_lower = response_text.lower()
    assert "paris" in response_lower, f"Expected 'Paris' in response, got: {response_text[:200]}"
    
    print(f"✓ /api/v1/chat/message (with context): received response mentioning Paris")


# --- Project Management Tests ---


@pytest.fixture
def unique_project_name():
    """Generate a unique project name for each test."""
    return f"test-project-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def created_project(unique_project_name):
    """Create a project and return its ID."""
    resp = _post(
        "/api/v1/projects",
        {
            "name": unique_project_name,
            "description": "A test project",
            "workspace_path": f"/tmp/{unique_project_name}",
        },
    )
    
    project_id = resp.get("project_id") or resp.get("id")
    assert project_id, f"Missing project ID in response: {resp}"
    
    return project_id


def test_projects_list():
    """Test GET /api/v1/projects returns a list."""
    resp = _get("/api/v1/projects")
    
    # Should return projects list (may be empty or wrapped)
    if isinstance(resp, list):
        projects = resp
    elif isinstance(resp, dict) and "projects" in resp:
        projects = resp["projects"]
    else:
        raise AssertionError(f"Unexpected projects response: {resp}")
    
    assert isinstance(projects, list), f"Expected list, got {type(projects)}"
    print(f"✓ /api/v1/projects: {len(projects)} project(s)")


def test_project_create(unique_project_name):
    """Test POST /api/v1/projects to create a project."""
    resp = _post(
        "/api/v1/projects",
        {
            "name": unique_project_name,
            "description": "A test project",
            "workspace_path": f"/tmp/{unique_project_name}",
        },
    )
    
    # Should return project_id or id
    assert (
        "project_id" in resp or "id" in resp
    ), f"Missing project ID in response: {resp}"
    
    project_id = resp.get("project_id") or resp.get("id")
    print(f"✓ /api/v1/projects (create): created {project_id}")


def test_project_get(created_project):
    """Test GET /api/v1/projects/{project_id}."""
    resp = _get(f"/api/v1/projects/{created_project}")
    
    # Should return project details
    assert isinstance(resp, dict), f"Expected dict, got {type(resp)}"
    assert (
        "name" in resp or "project_name" in resp or "id" in resp
    ), f"Missing project fields: {resp.keys()}"
    
    print(f"✓ /api/v1/projects/{created_project}: retrieved project")


def test_projects_list_after_create(created_project):
    """Test GET /api/v1/projects after creating a project."""
    resp = _get("/api/v1/projects")
    
    if isinstance(resp, list):
        projects = resp
    elif isinstance(resp, dict) and "projects" in resp:
        projects = resp["projects"]
    else:
        projects = []
    
    assert len(projects) > 0, "Expected at least one project after creation"
    
    # Verify our created project is in the list
    project_ids = [p.get("id") or p.get("project_id") for p in projects]
    assert created_project in project_ids, f"Created project {created_project} not in list"
    
    print(f"✓ /api/v1/projects (after create): {len(projects)} project(s), includes created project")


if __name__ == "__main__":
    import sys

    print(f"\nRunning Priority 1 core API tests (chat, projects) against {BASE_URL}\n")
    
    # Wait for server to be ready
    try:
        _wait_for_server()
    except RuntimeError as e:
        print(f"✗ {e}")
        sys.exit(1)
    
    print()
    
    # Run chat tests
    chat_tests = [
        test_chat_message_simple,
        test_chat_message_with_context,
    ]
    
    failed = 0
    for test_fn in chat_tests:
        try:
            test_fn()
        except Exception as e:
            print(f"✗ {test_fn.__name__}: {e}")
            failed += 1
    
    # Run project tests (manually generate unique name for standalone mode)
    unique_name = f"test-project-{uuid.uuid4().hex[:8]}"
    project_id = None
    
    # List projects
    try:
        test_projects_list()
    except Exception as e:
        print(f"✗ test_projects_list: {e}")
        failed += 1
    
    # Create project
    try:
        test_project_create(unique_name)
        # Re-create to get project_id for dependent tests
        resp = _post(
            "/api/v1/projects",
            {
                "name": f"test-project-{uuid.uuid4().hex[:8]}",
                "description": "A test project for get/list",
                "workspace_path": f"/tmp/test-project-{uuid.uuid4().hex[:8]}",
            },
        )
        project_id = resp.get("project_id") or resp.get("id")
    except Exception as e:
        print(f"✗ test_project_create: {e}")
        failed += 1
    
    # Test get and list with created project
    if project_id:
        try:
            test_project_get(project_id)
        except Exception as e:
            print(f"✗ test_project_get: {e}")
            failed += 1
        
        try:
            test_projects_list_after_create(project_id)
        except Exception as e:
            print(f"✗ test_projects_list_after_create: {e}")
            failed += 1
    
    total = len(chat_tests) + 4  # 2 chat + 4 project tests
    print(f"\n{total - failed}/{total} tests passed")
    sys.exit(0 if failed == 0 else 1)
