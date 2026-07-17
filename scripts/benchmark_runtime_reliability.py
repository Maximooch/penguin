#!/usr/bin/env python3
"""Record hermetic fresh/large-session runtime reliability baselines.

The harness installs the supported 127.0.0.1:8080 test-role environment before
importing Penguin runtime modules. It exercises the real chat route, context
assembly, tool scheduler, session writer, and runtime-event ledger with a
deterministic local provider. It never binds a port or calls a live provider.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-directory",
        type=Path,
        default=Path(".runtime-reliability-baselines"),
        help="Parent for the isolated test workspace.",
    )
    parser.add_argument(
        "--run-id",
        default="phase0-baseline",
        help="Deterministic isolated workspace name.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON output path. The result is always written to stdout.",
    )
    return parser.parse_args(argv)


def _install_test_environment(base_directory: Path, run_id: str) -> dict[str, str]:
    """Install the supported isolated 8080 environment before runtime imports."""

    from penguin.web.runtime_storage import build_isolated_test_environment

    environment = build_isolated_test_environment(
        base_directory=base_directory,
        run_id=run_id,
        environ=os.environ,
    )
    for key in (
        "PENGUIN_CONFIG_PATH",
        "PENGUIN_SETUP_ON_IMPORT",
        "PENGUIN_WEB_LOG_FILE",
    ):
        os.environ.pop(key, None)
    os.environ.update(environment)
    return environment


def _directory_bytes(root: Path) -> int:
    """Return recursive regular-file bytes for a small isolated fixture tree."""

    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


async def _run_baselines(workspace: Path) -> dict[str, Any]:
    """Execute fresh and large cases through the instrumented request path."""

    from penguin.llm.runtime import execute_pending_tool_calls
    from penguin.system.context_window import ContextWindowManager
    from penguin.system.runtime_diagnostics import (
        mark_runtime_progress,
        record_runtime_duration,
    )
    from penguin.system.runtime_event_ledger import RuntimeEventLedger
    from penguin.system.runtime_events import build_runtime_event
    from penguin.system.session_manager import SessionManager
    from penguin.system.state import MessageCategory, create_message
    from penguin.web import routes

    conversations = workspace / "conversations"
    manager = SessionManager(base_path=str(conversations), auto_save_interval=0)
    ledger = RuntimeEventLedger(Path(os.environ["PENGUIN_RUNTIME_EVENT_LEDGER_PATH"]))
    context_window = ContextWindowManager(
        token_counter=lambda content: max(1, len(str(content)) // 4)
    )

    class _ProviderHandler:
        """One deterministic native tool call per request."""

        def __init__(self) -> None:
            self.call_index = 0

        def get_and_clear_pending_tool_calls(self) -> list[dict[str, str]]:
            self.call_index += 1
            return [
                {
                    "call_id": f"controlled-call-{self.call_index}",
                    "name": "controlled_read",
                    "arguments": '{"fixture":"runtime-baseline"}',
                }
            ]

    class _ToolManager:
        """Controlled local tool implementation with bounded output."""

        def execute_tool(self, name: str, arguments: object) -> dict[str, str]:
            if name != "controlled_read":
                raise ValueError(f"Unexpected tool: {name}")
            if arguments != {"fixture": "runtime-baseline"}:
                raise ValueError("Unexpected controlled tool arguments")
            return {
                "action": name,
                "status": "completed",
                "result": "controlled-output",
            }

    handler = _ProviderHandler()
    api_client = SimpleNamespace(
        client_handler=handler,
        model_config=SimpleNamespace(provider="fake", model="deterministic-v1"),
    )

    class _BenchmarkCore:
        """Minimal route-compatible core using real local runtime components."""

        def __init__(self) -> None:
            self.runtime_config = SimpleNamespace(
                workspace_root=str(workspace),
                project_root=str(workspace),
                active_root=str(workspace),
            )
            self.model_config = SimpleNamespace(
                provider="fake",
                model="deterministic-v1",
                service_tier=None,
            )
            self.api_client = api_client
            self.conversation_manager = None
            self.current_session = None
            self.request_sequence = 0

        async def process(self, **kwargs: Any) -> dict[str, Any]:
            session = self.current_session
            if session is None:
                raise RuntimeError("Benchmark session was not selected")
            self.request_sequence += 1
            user_text = str(dict(kwargs.get("input_data") or {}).get("text") or "")
            session.add_message(
                create_message(
                    "user",
                    user_text,
                    MessageCategory.DIALOG,
                    tokens=max(1, len(user_text) // 4),
                )
            )

            context_window.process_session(session)

            setup_started = time.perf_counter()
            await asyncio.sleep(0)
            record_runtime_duration(
                "provider.setup",
                (time.perf_counter() - setup_started) * 1000,
            )
            first_event_started = time.perf_counter()
            await asyncio.sleep(0)
            record_runtime_duration(
                "provider.wait_first_event",
                (time.perf_counter() - first_event_started) * 1000,
            )
            mark_runtime_progress("provider")
            stream_started = time.perf_counter()
            assistant_response = "deterministic provider response"
            record_runtime_duration(
                "provider.stream",
                (time.perf_counter() - stream_started) * 1000,
            )

            persisted_actions: list[dict[str, object]] = []
            action_results = await execute_pending_tool_calls(
                api_client=api_client,
                tool_manager=_ToolManager(),
                persist_action_result=lambda result, metadata: persisted_actions.append(
                    {"result": result, "metadata": metadata}
                ),
            )
            session.add_message(
                create_message(
                    "assistant",
                    assistant_response,
                    MessageCategory.DIALOG,
                    tokens=max(1, len(assistant_response) // 4),
                )
            )
            manager.save_session(session)

            event = build_runtime_event(
                event_type="message.updated",
                payload={
                    "id": f"benchmark-message-{self.request_sequence}",
                    "sessionID": session.id,
                    "role": "assistant",
                },
                sequence=self.request_sequence,
                time_ms=1_000 + self.request_sequence,
            )
            ledger.append(event)
            return {
                "assistant_response": assistant_response,
                "action_results": action_results,
                "aborted": False,
                "status": "completed",
                "iterations": 1,
                "usage": {
                    "input_tokens": session.total_tokens,
                    "output_tokens": max(1, len(assistant_response) // 4),
                },
            }

    core = _BenchmarkCore()

    def _seed_large_session() -> Any:
        session = manager.create_session()
        for index in range(200):
            content = f"fixture-{index:03d}:" + ("x" * 1024)
            session.add_message(
                create_message(
                    "user" if index % 2 == 0 else "assistant",
                    content,
                    MessageCategory.DIALOG,
                    tokens=max(1, len(content) // 4),
                )
            )
        manager.save_session(session)
        return session

    cases = {
        "fresh": manager.create_session(),
        "large_persisted": _seed_large_session(),
    }
    results: dict[str, Any] = {}
    for case_name, session in cases.items():
        core.current_session = session
        storage_before = _directory_bytes(workspace)
        response = await routes.handle_chat_message(
            routes.MessageRequest(
                text=f"run deterministic {case_name} baseline",
                streaming=False,
                directory=str(workspace),
                max_iterations=1,
            ),
            core=core,
        )
        storage_after = _directory_bytes(workspace)
        session_path = conversations / f"{session.id}.json"
        diagnostics = response["runtime_diagnostics"]
        results[case_name] = {
            "status": response["status"],
            "response_chars": len(response["response"]),
            "action_count": len(response["action_results"]),
            "message_count_after": len(session.messages),
            "session_bytes_after": session_path.stat().st_size,
            "storage_bytes_before": storage_before,
            "storage_bytes_after": storage_after,
            "storage_delta_bytes": storage_after - storage_before,
            "diagnostics": diagnostics,
        }
    return results


def main(argv: list[str] | None = None) -> int:
    """Install isolation, run the harness, and emit one JSON evidence document."""

    args = _parse_args(argv)
    environment = _install_test_environment(
        args.base_directory.expanduser().resolve(),
        args.run_id,
    )
    workspace = Path(environment["PENGUIN_WORKSPACE"])
    workspace.mkdir(parents=True, exist_ok=True)
    cases = asyncio.run(_run_baselines(workspace))
    payload = {
        "schema_version": 1,
        "harness": "runtime-reliability-deterministic-local-v1",
        "server_role": environment["PENGUIN_SERVER_ROLE"],
        "host": environment["HOST"],
        "port": int(environment["PORT"]),
        "provider": "deterministic-local",
        "live_provider": False,
        "network_server_started": False,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cases": cases,
        "remaining_uncertainty": [
            "The harness calls the production REST handler directly and does not "
            "include HTTP socket overhead.",
            "It uses real local components behind a minimal core, not the full "
            "PenguinCore/Engine reasoning loop.",
            "Provider timings are deterministic local scheduling costs, not "
            "live-provider latency.",
            "Phase 1 and Phase 2 fault, watchdog, reconnect, and queued-writer "
            "paths are not present yet.",
        ],
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
