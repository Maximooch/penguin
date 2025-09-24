"""
Phase C – WebSocket Message Stream Smoke Test

Connects to `/api/v1/ws/messages` (agent/channel filters) and, in parallel,
hits key REST endpoints to generate traffic so you can observe live events.

Environment variables:
  PENGUIN_WS_BASE   (default `ws://localhost:8000`)
  PENGUIN_HTTP_BASE (default `http://localhost:8000`)
  PENGUIN_WS_CHANNEL (optional channel filter, default `ws-room`)

Run:
  uv run python scripts/phaseC_ws_smoke.py
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid

import contextlib

import httpx
import websockets

BASE_WS = os.getenv("PENGUIN_WS_BASE", "ws://localhost:8000").rstrip("/")
BASE_HTTP = os.getenv("PENGUIN_HTTP_BASE", "http://localhost:8000").rstrip("/")
CHANNEL = os.getenv("PENGUIN_WS_CHANNEL", "ws-room")


def pretty(obj):
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        return str(obj)


async def trigger_events(agent_id: str) -> None:
    """Exercise REST endpoints to generate activity for the WS stream."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        spawn_payload = {
            "id": agent_id,
            "parent": "default",
            "model_config_id": "moonshotai/kimi-k2-0905",
            "share_session": False,
            "share_context_window": False,
            "shared_cw_max_tokens": 262000,
            "initial_prompt": "WS smoke hello",
        }
        r = await client.post(f"{BASE_HTTP}/api/v1/agents", json=spawn_payload)
        if r.status_code == 400:
            spawn_payload.pop("model_config_id", None)
            spawn_payload["model_overrides"] = {
                "model": "moonshotai/kimi-k2-0905",
                "provider": "openrouter",
                "client_preference": "openrouter",
            }
            await client.post(f"{BASE_HTTP}/api/v1/agents", json=spawn_payload)

        await asyncio.sleep(0.5)
        await client.patch(f"{BASE_HTTP}/api/v1/agents/{agent_id}", json={"paused": True})
        await asyncio.sleep(0.5)
        await client.post(
            f"{BASE_HTTP}/api/v1/agents/{agent_id}/delegate",
            json={"content": "WS smoke delegate", "channel": CHANNEL},
        )
        await asyncio.sleep(0.5)
        await client.patch(f"{BASE_HTTP}/api/v1/agents/{agent_id}", json={"paused": False})
        await asyncio.sleep(0.5)
        await client.delete(f"{BASE_HTTP}/api/v1/agents/{agent_id}")


async def consume(ws, limit: int = 20):
    idx = 0
    try:
        while True:
            raw = await ws.recv()
            idx += 1
            print(f"[{idx}]", pretty(json.loads(raw)))
            if idx >= limit:
                break
    except asyncio.CancelledError:
        pass
    except websockets.exceptions.ConnectionClosed:
        pass


async def main() -> int:
    agent_id = f"ws_smoke_{uuid.uuid4().hex[:6]}"
    params = [f"agent_id={agent_id}"]
    if CHANNEL:
        params.append(f"channel={CHANNEL}")
    url = f"{BASE_WS}/api/v1/ws/messages?{'&'.join(params)}"

    print(f"Connecting to {url}")
    try:
        async with websockets.connect(url) as ws:
            consumer = asyncio.create_task(consume(ws))
            await trigger_events(agent_id)
            await asyncio.sleep(5)
            consumer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await consumer
    except Exception as exc:
        print("[error]", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
