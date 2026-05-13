from __future__ import annotations

from penguin.system.context_window import ContextWindowManager
from penguin.system.state import Message, MessageCategory, Session


def test_context_window_trim_preserves_llm_request_lifecycle_records() -> None:
    cwm = ContextWindowManager(token_counter=lambda content: len(str(content)))
    cwm.max_context_window_tokens = 1

    session = Session()
    session.add_message(
        Message(
            role="user",
            content="this message is intentionally over budget",
            category=MessageCategory.DIALOG,
        )
    )
    session.add_llm_request_lifecycle(
        {
            "request_id": "req-cwm-1",
            "provider": "openai",
            "model": "gpt-test",
            "status": "completed",
        }
    )

    trimmed = cwm.trim_session(session)

    assert trimmed.llm_request_lifecycles == session.llm_request_lifecycles
