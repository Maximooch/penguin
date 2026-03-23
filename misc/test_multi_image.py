#!/usr/bin/env python3
"""Test script for multi-image support via Penguin web server.

Requires penguin-web to be running on localhost:8000.
"""

import asyncio
import os
import sys
import httpx

# Add the penguin package to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE_URL = "http://localhost:8000"


async def test_health():
    """Check if the server is running."""
    print("Checking server health...")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{BASE_URL}/api/v1/health")
            if resp.status_code == 200:
                print("✓ Server is running")
                return True
            else:
                print(f"✗ Server returned status {resp.status_code}")
                return False
    except httpx.ConnectError:
        print("✗ Cannot connect to server. Is penguin-web running?")
        print("  Start it with: uv run penguin-web")
        return False
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


async def test_multi_image_api():
    """Test multi-image support via REST API."""
    print("\n" + "=" * 60)
    print("TEST: Multi-Image via REST API (/api/v1/chat/message)")
    print("=" * 60)

    # Test images (use absolute paths)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    test_images = [
        os.path.join(base_dir, "context/image.png"),
        os.path.join(base_dir, "penguin/IMG.jpg"),
    ]

    existing_images = [p for p in test_images if os.path.exists(p)]
    if len(existing_images) < 2:
        print(f"\n⚠ Need at least 2 test images, found {len(existing_images)}")
        for img in test_images:
            status = "✓" if os.path.exists(img) else "✗"
            print(f"  {status} {img}")
        return None

    print(f"\nUsing {len(existing_images)} images:")
    for img in existing_images:
        print(f"  - {os.path.basename(img)}")

    payload = {
        "text": "Briefly describe what you see in each image. Just 1-2 sentences per image.",
        "image_paths": existing_images,
        "streaming": False,
        "max_iterations": 1,
    }

    print(f"\nSending request to {BASE_URL}/api/v1/chat/message...")
    print(f"Payload: text='{payload['text'][:50]}...', image_paths=[{len(existing_images)} images]")

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{BASE_URL}/api/v1/chat/message",
                json=payload,
            )

            print(f"\nStatus: {resp.status_code}")

            if resp.status_code == 200:
                data = resp.json()
                response = data.get("response", "")
                print(f"\n=== RESPONSE ===\n{response}")

                if response and len(response) > 20:
                    print("\n✓ Multi-image API test PASSED!")
                    return True
                else:
                    print(f"\n✗ Response too short or empty")
                    return False
            else:
                print(f"✗ Request failed: {resp.text[:500]}")
                return False

    except httpx.ReadTimeout:
        print("✗ Request timed out (120s)")
        return False
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_multi_image_websocket():
    """Test multi-image support via WebSocket streaming."""
    import json

    print("\n" + "=" * 60)
    print("TEST: Multi-Image via WebSocket (/api/v1/chat/stream)")
    print("=" * 60)

    # Test images
    base_dir = os.path.dirname(os.path.abspath(__file__))
    test_images = [
        os.path.join(base_dir, "context/image.png"),
        os.path.join(base_dir, "penguin/IMG.jpg"),
    ]

    existing_images = [p for p in test_images if os.path.exists(p)]
    if len(existing_images) < 2:
        print(f"\n⚠ Skipping WebSocket test - need at least 2 images")
        return None

    print(f"\nUsing {len(existing_images)} images via WebSocket")

    payload = {
        "text": "What do you see in these images? Be brief.",
        "image_paths": existing_images,
        "max_iterations": 1,
    }

    ws_url = BASE_URL.replace("http://", "ws://") + "/api/v1/chat/stream"
    print(f"Connecting to {ws_url}...")

    try:
        import websockets
        async with websockets.connect(ws_url, close_timeout=5) as ws:
            print("Connected. Sending message...")
            await ws.send(json.dumps(payload))

            response_chunks = []
            while True:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=60.0)
                    data = json.loads(msg)
                    event = data.get("event", "")

                    if event == "start":
                        print("  [start]")
                    elif event == "token":
                        token = data.get("data", {}).get("token", "")
                        response_chunks.append(token)
                        print(token, end="", flush=True)
                    elif event == "complete":
                        print("\n  [complete]")
                        break
                    elif event == "error":
                        print(f"\n  [error] {data.get('data', {}).get('message', '')}")
                        return False

                except asyncio.TimeoutError:
                    print("\n✗ WebSocket timeout")
                    return False

            full_response = "".join(response_chunks)
            if full_response and len(full_response) > 20:
                print("\n✓ Multi-image WebSocket test PASSED!")
                return True
            else:
                print(f"\n✗ Response too short: '{full_response}'")
                return False

    except ImportError:
        print("⚠ websockets package not installed, skipping WebSocket test")
        return None
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    print("=" * 60)
    print("Multi-Image Support Test Suite (via Web Server)")
    print("=" * 60)

    # Check server health first
    if not await test_health():
        print("\n⚠ Server not available. Exiting.")
        return

    # Test REST API
    api_ok = await test_multi_image_api()

    # Test WebSocket (optional)
    ws_ok = await test_multi_image_websocket()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  REST API:   {'PASS' if api_ok else 'SKIP' if api_ok is None else 'FAIL'}")
    print(f"  WebSocket:  {'PASS' if ws_ok else 'SKIP' if ws_ok is None else 'FAIL'}")


if __name__ == "__main__":
    asyncio.run(main())
