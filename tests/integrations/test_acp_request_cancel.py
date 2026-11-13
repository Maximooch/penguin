"""Cancel exact prompt RPCs without cancelling a different active session."""

import asyncio
import json
import os
import sys

import pytest

pytest.importorskip("acp")
from test_acp_wire import _CLI_AGENT


@pytest.mark.asyncio
async def test_real_cli_request_cancel_targets_queued_and_running_turns(tmp_path):
    script = _CLI_AGENT.replace(
        "        print('provider diagnostic')",
        """
        print('provider diagnostic')
        if text == 'slow':
            import asyncio
            await kwargs['stream_callback']('started')
            await asyncio.Event().wait()
""",
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        script,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env={
            **os.environ,
            "PENGUIN_WORKSPACE": str(tmp_path),
            "ACP_TEST_STORE": str(tmp_path / "sessions"),
        },
    )

    async def send(method, params, request_id=None):
        frame = {"jsonrpc": "2.0", "method": method, "params": params}
        if request_id is not None:
            frame["id"] = request_id
        process.stdin.write((json.dumps(frame) + "\n").encode())
        await process.stdin.drain()

    async def receive_id(request_id):
        while True:
            frame = json.loads(await asyncio.wait_for(process.stdout.readline(), 15))
            if frame.get("id") == request_id:
                return frame

    try:
        await send("initialize", {"protocolVersion": 1}, 1)
        await receive_id(1)
        sessions = []
        for rid in (2, 3):
            await send("session/new", {"cwd": str(tmp_path), "mcpServers": []}, rid)
            sessions.append((await receive_id(rid))["result"]["sessionId"])

        def slow(sid):
            return {"sessionId": sid, "prompt": [{"type": "text", "text": "slow"}]}

        await send("session/prompt", slow(sessions[0]), 7)
        while True:
            frame = json.loads(await asyncio.wait_for(process.stdout.readline(), 15))
            if (
                frame.get("params", {}).get("update", {}).get("content", {}).get("text")
                == "started"
            ):
                break
        await send("session/prompt", slow(sessions[1]), 8)
        await send("$/cancel_request", {"requestId": 8})
        assert (await receive_id(8))["result"]["stopReason"] == "cancelled"
        await send("$/cancel_request", {"requestId": 7})
        assert (await receive_id(7))["result"]["stopReason"] == "cancelled"
        await send("$/cancel_request", {"requestId": 7})
        await send(
            "session/prompt",
            {
                "sessionId": sessions[0],
                "prompt": [{"type": "text", "text": "again"}],
            },
            9,
        )
        assert (await receive_id(9))["result"]["stopReason"] == "end_turn"
    finally:
        process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), 10)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
