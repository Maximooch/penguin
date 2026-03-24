from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest

from penguin.utils.parser import ActionExecutor


class _CaptureToolManager:
    def __init__(self, result: str | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._result = result or json.dumps({"status": "ok"})

    def execute_tool(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        self.calls.append((tool_name, tool_input))
        return self._result


def _build_executor() -> tuple[ActionExecutor, _CaptureToolManager]:
    tool_manager = _CaptureToolManager()
    executor = ActionExecutor(
        tool_manager=cast(Any, tool_manager),
        task_manager=cast(Any, SimpleNamespace()),
    )
    return executor, tool_manager


def test_enhanced_write_handler_parses_trailing_backup_flag() -> None:
    executor, tool_manager = _build_executor()

    result = executor._enhanced_write(
        "README.md:url: http://localhost:3000\nmode: build:false"
    )

    assert json.loads(result)["status"] == "ok"
    assert tool_manager.calls == [
        (
            "write_file",
            {
                "path": "README.md",
                "content": "url: http://localhost:3000\nmode: build",
                "backup": False,
            },
        )
    ]


def test_replace_lines_handler_preserves_colons_in_new_content() -> None:
    executor, tool_manager = _build_executor()

    result = executor._replace_lines(
        'src/main.py:10:12:url = "http://localhost:3000"\nlabel = "x:y":false'
    )

    assert json.loads(result)["status"] == "ok"
    assert tool_manager.calls == [
        (
            "patch_file",
            {
                "path": "src/main.py",
                "operation_type": "replace_lines",
                "start_line": 10,
                "end_line": 12,
                "new_content": 'url = "http://localhost:3000"\nlabel = "x:y"',
                "verify": False,
            },
        )
    ]


def test_edit_with_pattern_handler_preserves_colons_in_replacement() -> None:
    executor, tool_manager = _build_executor()

    result = executor._edit_with_pattern(
        "config.py:DEBUG = False:http://localhost:8000:false"
    )

    assert json.loads(result)["status"] == "ok"
    assert tool_manager.calls == [
        (
            "patch_file",
            {
                "path": "config.py",
                "operation_type": "regex_replace",
                "search_pattern": "DEBUG = False",
                "replacement": "http://localhost:8000",
                "backup": False,
            },
        )
    ]


def test_edit_with_pattern_handler_preserves_colons_in_search_pattern() -> None:
    executor, tool_manager = _build_executor()

    result = executor._edit_with_pattern(
        r"config.py:https?\://example.com\:5000:http://localhost:8000:false"
    )

    assert json.loads(result)["status"] == "ok"
    assert tool_manager.calls == [
        (
            "patch_file",
            {
                "path": "config.py",
                "operation_type": "regex_replace",
                "search_pattern": "https?://example.com:5000",
                "replacement": "http://localhost:8000",
                "backup": False,
            },
        )
    ]


def test_edit_with_pattern_handler_accepts_json_payload() -> None:
    executor, tool_manager = _build_executor()

    result = executor._edit_with_pattern(
        json.dumps(
            {
                "file_path": "config.py",
                "search_pattern": r"https?://example.com:5000",
                "replacement": "http://localhost:8000",
                "backup": False,
            }
        )
    )

    assert json.loads(result)["status"] == "ok"
    assert tool_manager.calls == [
        (
            "patch_file",
            {
                "path": "config.py",
                "operation_type": "regex_replace",
                "search_pattern": r"https?://example.com:5000",
                "replacement": "http://localhost:8000",
                "backup": False,
            },
        )
    ]
