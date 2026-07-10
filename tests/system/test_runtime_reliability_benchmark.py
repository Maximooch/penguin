"""Deterministic runtime reliability benchmark harness tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_benchmark_records_fresh_and_large_isolated_cases(tmp_path: Path) -> None:
    """The repeatable harness records attributed 8080 evidence without a server."""

    repository = Path(__file__).resolve().parents[2]
    output_path = tmp_path / "evidence.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/benchmark_runtime_reliability.py",
            "--base-directory",
            str(tmp_path / "runtimes"),
            "--run-id",
            "test-baseline",
            "--output",
            str(output_path),
        ],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["server_role"] == "test"
    assert payload["host"] == "127.0.0.1"
    assert payload["port"] == 8080
    assert payload["live_provider"] is False
    assert payload["network_server_started"] is False
    assert set(payload["cases"]) == {"fresh", "large_persisted"}

    required_stages = {
        "request.end_to_end",
        "request.process",
        "context.process_session",
        "provider.setup",
        "provider.wait_first_event",
        "provider.stream",
        "tool.execution",
        "tool.batch",
        "session.save",
        "ledger.commit",
        "ledger.cleanup",
    }
    for case in payload["cases"].values():
        assert case["status"] == "completed"
        assert case["action_count"] == 1
        assert set(case["diagnostics"]["stages"]) >= required_stages
        assert case["storage_delta_bytes"] >= 0

    assert (
        payload["cases"]["large_persisted"]["message_count_after"]
        > payload["cases"]["fresh"]["message_count_after"]
    )
    assert payload["remaining_uncertainty"]
