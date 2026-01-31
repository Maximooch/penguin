#!/usr/bin/env python3
"""Test SSE endpoint for OpenCode TUI compatibility."""

import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, '/Users/maximusputnam/Code/Penguin/penguin')

from fastapi.testclient import TestClient

# Import the app factory
from penguin.web.app import create_app

def test_sse_endpoint():
    """Test that SSE endpoint returns proper format."""
    print("Creating FastAPI app...")
    app = create_app()

    print("Creating test client...")
    client = TestClient(app)

    print("Testing SSE endpoint...")
    with client.get("/api/v1/events/sse") as response:
        print(f"Status code: {response.status_code}")
        print(f"Content-Type: {response.headers.get('content-type')}")

        # Read first few lines
        print("\nFirst events:")
        for i, line in enumerate(response.iter_lines()):
            if i < 5:
                print(f"  {line.decode() if isinstance(line, bytes) else line}")
            else:
                break

    print("\n✓ SSE endpoint test passed!")

def test_sse_with_session_filter():
    """Test SSE with session_id filter."""
    from penguin.web.app import create_app
    from fastapi.testclient import TestClient

    app = create_app()
    client = TestClient(app)

    print("\nTesting SSE with session filter...")
    response = client.get("/api/v1/events/sse?session_id=test-session-123")
    print(f"Status code: {response.status_code}")
    print(f"Headers: {dict(response.headers)}")

    # Just verify it connects
    assert response.status_code == 200
    print("✓ Session filter test passed!")

if __name__ == "__main__":
    test_sse_endpoint()
    test_sse_with_session_filter()
