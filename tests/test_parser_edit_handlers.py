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
                "_warnings": [
                    "Deprecated write_file payload: use JSON object payloads instead of colon-delimited strings"
                ],
            },
        )
    ]


def test_read_file_handler_accepts_canonical_json_payload() -> None:
    executor, tool_manager = _build_executor()

    result = executor._read_file(
        json.dumps(
            {
                "path": "src/main.py",
                "show_line_numbers": True,
                "max_lines": 25,
            }
        )
    )

    assert json.loads(result)["status"] == "ok"
    assert tool_manager.calls == [
        (
            "read_file",
            {
                "path": "src/main.py",
                "show_line_numbers": True,
                "max_lines": 25,
            },
        )
    ]


def test_write_file_handler_accepts_canonical_json_payload() -> None:
    executor, tool_manager = _build_executor()

    result = executor._write_file(
        json.dumps(
            {
                "path": "README.md",
                "content": "# Title\n",
                "backup": False,
            }
        )
    )

    assert json.loads(result)["status"] == "ok"
    assert tool_manager.calls == [
        (
            "write_file",
            {
                "path": "README.md",
                "content": "# Title\n",
                "backup": False,
                "_warnings": [],
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
                "operation": {
                    "type": "replace_lines",
                    "start_line": 10,
                    "end_line": 12,
                    "new_content": 'url = "http://localhost:3000"\nlabel = "x:y"',
                    "verify": False,
                },
                "backup": True,
                "_warnings": [
                    "Deprecated patch_file payload: legacy replace_lines strings are deprecated; use JSON payloads"
                ],
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
                "operation": {
                    "type": "regex_replace",
                    "search_pattern": "DEBUG = False",
                    "replacement": "http://localhost:8000",
                },
                "backup": False,
                "_warnings": [
                    "Deprecated patch_file payload: legacy edit_with_pattern strings are deprecated; use JSON payloads"
                ],
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
                "operation": {
                    "type": "regex_replace",
                    "search_pattern": "https?://example.com:5000",
                    "replacement": "http://localhost:8000",
                },
                "backup": False,
                "_warnings": [
                    "Deprecated patch_file payload: legacy edit_with_pattern strings are deprecated; use JSON payloads"
                ],
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
                "operation": {
                    "type": "regex_replace",
                    "search_pattern": r"https?://example.com:5000",
                    "replacement": "http://localhost:8000",
                },
                "backup": False,
                "_warnings": [
                    "Deprecated patch_file payload: flat JSON payloads are deprecated; use a nested operation object",
                    "Deprecated patch_file payload: use 'path' instead of legacy 'file_path'",
                ],
            },
        )
    ]


def test_patch_file_handler_accepts_canonical_nested_json_payload() -> None:
    executor, tool_manager = _build_executor()

    result = executor._patch_file(
        json.dumps(
            {
                "path": "src/main.py",
                "backup": False,
                "operation": {
                    "type": "replace_lines",
                    "start_line": 1,
                    "end_line": 1,
                    "new_content": "print('hi')",
                    "verify": True,
                },
            }
        )
    )

    assert json.loads(result)["status"] == "ok"
    assert tool_manager.calls == [
        (
            "patch_file",
            {
                "path": "src/main.py",
                "operation": {
                    "type": "replace_lines",
                    "start_line": 1,
                    "end_line": 1,
                    "new_content": "print('hi')",
                    "verify": True,
                },
                "backup": False,
                "_warnings": [],
            },
        )
    ]


def test_patch_files_handler_accepts_structured_operations_json() -> None:
    executor, tool_manager = _build_executor()

    result = executor._patch_files(
        json.dumps(
            {
                "apply": True,
                "operations": [
                    {
                        "path": "src/a.py",
                        "operation": {
                            "type": "replace_lines",
                            "start_line": 1,
                            "end_line": 1,
                            "new_content": "print('a')",
                            "verify": False,
                        },
                    },
                    {
                        "path": "src/b.py",
                        "operation": {
                            "type": "delete_lines",
                            "start_line": 2,
                            "end_line": 3,
                        },
                    },
                ],
            }
        )
    )

    assert json.loads(result)["status"] == "ok"
    assert tool_manager.calls == [
        (
            "patch_files",
            {
                "apply": True,
                "backup": True,
                "_warnings": [],
                "operations": [
                    {
                        "path": "src/a.py",
                        "operation": {
                            "type": "replace_lines",
                            "start_line": 1,
                            "end_line": 1,
                            "new_content": "print('a')",
                            "verify": False,
                        },
                        "backup": True,
                        "_warnings": [],
                    },
                    {
                        "path": "src/b.py",
                        "operation": {
                            "type": "delete_lines",
                            "start_line": 2,
                            "end_line": 3,
                        },
                        "backup": True,
                        "_warnings": [],
                    },
                ],
            },
        )
    ]
