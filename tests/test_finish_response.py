from pathlib import Path

from penguin.tools.core.task_tools import TaskTools


def test_finish_response_ignores_legacy_summary_text():
    task_tools = TaskTools()

    assert task_tools.finish_response("Hidden final answer") == "Response complete."


def test_finish_response_schema_has_no_summary_field_and_dispatch_ignores_it():
    source = Path("penguin/tools/tool_manager.py").read_text()

    assert '"name": "finish_response"' in source
    assert 'Do not pass summary text here' in source
    assert '"properties": {}' in source
    assert 'self.task_tools.finish_response(tool_input.get("summary"))' not in source
    assert '"finish_response": lambda: self.task_tools.finish_response(),' in source
