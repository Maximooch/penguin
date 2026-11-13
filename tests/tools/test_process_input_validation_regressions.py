"""Log-derived malformed process requests must fail without launching a child.

No recorded user prompts, command contents, or credentials are included.
"""

from unittest.mock import Mock

import pytest

from penguin.tools.process_tools import ProcessTools


@pytest.mark.parametrize(
    ("operation", "arguments"),
    [
        ("execute_command", {}),
        ("process_start", {}),
        ("execute_command", {"command": "unused", "timeout_seconds": "10"}),
        ("execute_command", {"command": "unused", "yield_time_ms": None}),
        ("execute_command", {"command": "unused", "max_chars": None}),
        ("process_poll", {}),
        ("process_status", {}),
        ("process_stop", {}),
        ("process_write_stdin", {}),
        ("execute_command", {"command": "   "}),
        ("execute_command", {"command": 123}),
        ("execute_command", {"command": "unused", "yield_time_ms": True}),
        ("execute_command", {"command": "unused", "timeout_seconds": float("nan")}),
        ("execute_command", {"command": "unused", "max_chars": 1.5}),
        ("execute_command", {"command": "unused", "timeout_seconds": 10**1000}),
        ("process_poll", {"process_id": 123}),
        ("process_poll", {"process_id": "p", "wait_ms": "1"}),
        ("process_poll", {"process_id": "p", "since_sequence": -1}),
        ("process_stop", {"process_id": "p", "timeout": float("inf")}),
        ("process_stop", {"process_id": "p", "mode": "invalid"}),
        ("process_write_stdin", {"process_id": "p", "text": None}),
        ("process_write_stdin", {"process_id": "p", "timeout_ms": 0}),
    ],
)
def test_invalid_process_request_returns_error_without_starting(operation, arguments):
    runtime = Mock()
    runtime._processes = {}
    runtime._error.side_effect = lambda process_id, message: {
        "status": "error",
        "error": message,
        "process_id": process_id,
    }
    service = ProcessTools(runtime)
    try:
        result = service.execute(operation, arguments, {})
        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error"]
    finally:
        runtime.start.assert_not_called()
        service.close()


@pytest.mark.parametrize(
    "arguments",
    [
        {
            "command": "echo ok",
            "timeout_seconds": None,
            "yield_time_ms": 0,
            "max_chars": 0,
        },
        {"command": "echo ok", "timeout_seconds": 0.5},
    ],
)
def test_valid_launch_boundaries_remain_accepted(arguments):
    assert ProcessTools._validate_arguments("execute_command", arguments) is None


def test_automatic_poll_cursor_remains_accepted():
    assert (
        ProcessTools._validate_arguments(
            "process_poll", {"process_id": "p", "since_sequence": None}
        )
        is None
    )
