"""Resolved questions are kept for lookups, but not without limit.

Covers SM-74: QuestionManager kept every answered or rejected question for the
life of the process.
"""

from __future__ import annotations

from penguin.security import question as question_module
from penguin.security.question import QuestionManager


def test_resolved_question_history_is_bounded(monkeypatch) -> None:
    monkeypatch.setattr(question_module, "MAX_RESOLVED_QUESTIONS", 3, raising=False)
    manager = QuestionManager()
    manager.reset()
    ids = []
    try:
        for index in range(5):
            request = manager.create_request(
                session_id="session", questions=[{"question": f"q{index}"}]
            )
            ids.append(request.id)
            manager.reply(request.id, [["yes"]])

        assert len(manager._resolved) == 3
        assert manager.get_request(ids[-1]) is not None
        assert manager.get_request(ids[0]) is None
    finally:
        manager.reset()
