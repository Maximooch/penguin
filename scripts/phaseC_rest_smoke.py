"""
Phase C – REST API Smoke Test

Exercises the new REST endpoints end-to-end against a running Penguin web app
(FastAPI). Assumes the server is running locally (default http://localhost:8000).

Run:
  uv run python scripts/phaseC_rest_smoke.py
or
  python scripts/phaseC_rest_smoke.py
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict

import httpx


BASE_URL = os.getenv("PENGUIN_API_BASE", "http://localhost:8000").rstrip("/")


def pretty(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        return str(obj)


async def main() -> int:
    agent_id = "rest_smoke_child"
    parent_id = "default"
    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1) List agents (roster)
        r = await client.get(f"{BASE_URL}/api/v1/agents")
        print("[GET /agents]", r.status_code)
        if r.status_code != 200:
            print(r.text)
            return 1

        # 2) Spawn sub-agent (prefer model id; fallback to overrides)
        model_id = os.getenv("PENGUIN_MODEL_ID", "moonshotai/kimi-k2-0905")
        payload: Dict[str, Any] = {
            "id": agent_id,
            "parent": parent_id,
            "model_config_id": model_id,
            "share_session": False,
            "share_context_window": False,
            "shared_cw_max_tokens": 262000,
            "initial_prompt": "Hello from REST",
        }
        r = await client.post(f"{BASE_URL}/api/v1/agents", json=payload)
        if r.status_code == 400:
            payload.pop("model_config_id", None)
            payload["model_overrides"] = {
                "model": "moonshotai/kimi-k2-0905",
                "provider": "openrouter",
                "client_preference": "openrouter",
            }
            r = await client.post(f"{BASE_URL}/api/v1/agents", json=payload)
        print("[POST /agents]", r.status_code)
        if r.status_code != 200 and r.status_code != 201:
            print(r.text)
            return 1
        print("[agent profile]", pretty(r.json()))

        # 3) Pause
        r = await client.patch(f"{BASE_URL}/api/v1/agents/{agent_id}", json={"paused": True})
        print("[PATCH /agents/{id} paused]", r.status_code)

        # 4) Delegate with channel
        r = await client.post(
            f"{BASE_URL}/api/v1/agents/{agent_id}/delegate",
            json={"content": "status via REST delegate", "channel": "dev-room", "parent": parent_id},
        )
        print("[POST /agents/{id}/delegate]", r.status_code)

        # 5) Resume
        r = await client.patch(f"{BASE_URL}/api/v1/agents/{agent_id}", json={"paused": False})
        print("[PATCH /agents/{id} resume]", r.status_code)

        # 6) Current history for the child
        r = await client.get(f"{BASE_URL}/api/v1/agents/{agent_id}/history", params={"limit": 50})
        print("[GET /agents/{id}/history]", r.status_code)
        if r.status_code == 200:
            tail = r.json()[-5:]
            print(pretty(tail))

        # 7) List sessions and fetch specific session history
        r = await client.get(f"{BASE_URL}/api/v1/agents/{agent_id}/sessions")
        print("[GET /agents/{id}/sessions]", r.status_code)
        sessions = r.json() if r.status_code == 200 else []
        if sessions:
            sid = sessions[-1].get("id")
            r = await client.get(
                f"{BASE_URL}/api/v1/agents/{agent_id}/sessions/{sid}/history",
                params={"include_system": True, "limit": 20},
            )
            print("[GET /agents/{id}/sessions/{sid}/history]", r.status_code)
            if r.status_code == 200:
                print(pretty(r.json()[-5:]))

        # 8) Telemetry
        r = await client.get(f"{BASE_URL}/api/v1/telemetry")
        print("[GET /telemetry]", r.status_code)
        if r.status_code == 200:
            print(pretty(r.json()))

        # 9) Delete agent (preserve conversation)
        r = await client.delete(f"{BASE_URL}/api/v1/agents/{agent_id}")
        print("[DELETE /agents/{id}]", r.status_code, r.text)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
