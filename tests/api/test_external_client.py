"""Test external client interaction with Penguin web API.

This simulates how an external chat application (like Link) would interact
with the Penguin API running in a Docker container.
"""

import os
import time
import urllib.request
import urllib.error
import json
from typing import Any, Dict, List


BASE_URL = os.environ.get("PENGUIN_API_URL", "http://127.0.0.1:8000")


def _wait_for_server(timeout: int = 30) -> None:
    """Wait for server to be ready."""
    print(f"Waiting for Penguin API at {BASE_URL}...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(f"{BASE_URL}/api/v1/health", timeout=2) as resp:
                if resp.status == 200:
                    print(f"✓ Penguin API ready ({time.time() - start:.1f}s)\n")
                    return
        except Exception:
            time.sleep(1)
    raise RuntimeError(f"Penguin API not ready after {timeout}s")


def _get(path: str) -> Dict[str, Any]:
    """GET request."""
    url = f"{BASE_URL}{path}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post(path: str, data: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
    """POST request."""
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class LinkChatClient:
    """Simulates Link chat app interacting with Penguin API."""
    
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.conversation_id = None
    
    def get_capabilities(self) -> Dict[str, Any]:
        """Discover what Penguin can do."""
        return _get("/api/v1/capabilities")
    
    def start_conversation(self, name: str = "Link conversation") -> str:
        """Start a new conversation."""
        resp = _post("/api/v1/conversations/create", {"name": name})
        self.conversation_id = resp.get("conversation_id") or resp.get("id")
        return self.conversation_id
    
    def send_message(self, text: str, max_iterations: int = 5) -> Dict[str, Any]:
        """Send a message and get response."""
        payload = {
            "text": text,
            "max_iterations": max_iterations,
        }
        if self.conversation_id:
            payload["conversation_id"] = self.conversation_id
        
        return _post("/api/v1/chat/message", payload, timeout=90)
    
    def get_conversation_history(self) -> List[Dict[str, Any]]:
        """Get conversation messages."""
        if not self.conversation_id:
            return []
        return _get(f"/api/v1/conversations/{self.conversation_id}")


def test_external_client_workflow():
    """Simulate Link app workflow: capabilities → conversation → chat."""
    
    print("=== Simulating Link Chat App Workflow ===\n")
    
    client = LinkChatClient(BASE_URL)
    
    # 1. Discover capabilities
    print("1. Discovering Penguin capabilities...")
    caps = client.get_capabilities()
    print(f"   ✓ Vision: {caps.get('vision_enabled')}")
    print(f"   ✓ Streaming: {caps.get('streaming_enabled')}")
    print(f"   ✓ Model: {caps.get('model')}\n")
    
    # 2. Start conversation
    print("2. Starting conversation...")
    conv_id = client.start_conversation("Link test conversation")
    print(f"   ✓ Conversation ID: {conv_id}\n")
    
    # 3. Send messages
    print("3. Sending test messages...\n")
    
    # Simple greeting
    resp1 = client.send_message("Hello! Can you help me?", max_iterations=1)
    response1 = resp1.get("response") or resp1.get("assistant_response", "")
    print(f"   User: Hello! Can you help me?")
    print(f"   Penguin: {response1[:100]}...\n")
    
    # Math question
    resp2 = client.send_message("What is 15 * 7?", max_iterations=1)
    response2 = resp2.get("response") or resp2.get("assistant_response", "")
    print(f"   User: What is 15 * 7?")
    print(f"   Penguin: {response2[:100]}...")
    
    # Verify answer
    if "105" in response2:
        print(f"   ✓ Correct answer!\n")
    
    # 4. Get conversation history
    print("4. Retrieving conversation history...")
    history = client.get_conversation_history()
    if isinstance(history, dict):
        messages = history.get("messages", [])
    elif isinstance(history, list):
        messages = history
    else:
        messages = []
    print(f"   ✓ History has {len(messages)} message(s)\n")
    
    print("✅ External client workflow test PASSED")
    print("\nThis demonstrates how Link (or any chat app) can:")
    print("  - Discover Penguin's capabilities")
    print("  - Create and maintain conversations")
    print("  - Send/receive messages with context")
    print("  - Retrieve conversation history")
    
    return True


if __name__ == "__main__":
    import sys
    
    print(f"\nTesting external client integration with Penguin API\n")
    print("=" * 60 + "\n")
    
    try:
        _wait_for_server()
        result = test_external_client_workflow()
        sys.exit(0 if result else 1)
    except Exception as e:
        print(f"\n❌ Test FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
