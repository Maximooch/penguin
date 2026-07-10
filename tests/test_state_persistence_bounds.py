from __future__ import annotations

from penguin.system.state import (
    MAX_PERSISTED_LLM_REQUEST_LIFECYCLES,
    MAX_PERSISTED_TOOL_RECORDS,
    Session,
)


def test_session_diagnostic_records_are_bounded() -> None:
    session = Session()

    for index in range(MAX_PERSISTED_LLM_REQUEST_LIFECYCLES + 10):
        session.add_llm_request_lifecycle({"request_id": f"request-{index}"})
    for index in range(MAX_PERSISTED_TOOL_RECORDS + 10):
        session.add_tool_call_record({"call_id": f"call-{index}", "name": "read"})
        session.add_tool_result_record(
            {"call_id": f"call-{index}", "name": "read", "status": "completed"}
        )

    assert len(session.llm_request_lifecycles) == MAX_PERSISTED_LLM_REQUEST_LIFECYCLES
    assert len(session.tool_call_records) == MAX_PERSISTED_TOOL_RECORDS
    assert len(session.tool_result_records) == MAX_PERSISTED_TOOL_RECORDS
    assert session.llm_request_lifecycles[0]["request_id"] == "request-10"
    assert session.tool_call_records[0]["call_id"] == "call-10"


def test_loading_oversized_diagnostic_records_keeps_newest_entries() -> None:
    data = {
        "id": "session-bounded",
        "messages": [],
        "llm_request_lifecycles": [
            {"request_id": f"request-{index}"}
            for index in range(MAX_PERSISTED_LLM_REQUEST_LIFECYCLES + 1)
        ],
        "tool_call_records": [
            {"call_id": f"call-{index}"}
            for index in range(MAX_PERSISTED_TOOL_RECORDS + 1)
        ],
        "tool_result_records": [
            {"call_id": f"call-{index}"}
            for index in range(MAX_PERSISTED_TOOL_RECORDS + 1)
        ],
    }

    loaded = Session.from_dict(data)

    assert loaded.llm_request_lifecycles[-1]["request_id"] == "request-256"
    assert loaded.tool_call_records[-1]["call_id"] == "call-512"
    assert loaded.tool_result_records[-1]["call_id"] == "call-512"
