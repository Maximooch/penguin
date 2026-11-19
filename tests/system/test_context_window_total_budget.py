"""The context window fits the total budget even when no category is over its own.

Covers SM-55: trimming only touched categories over their own budget. The
default category budgets add up to more than the whole window, so a session
could exceed the window while every category was within budget, and nothing
was trimmed. Trimming keeps the category-priority model: lowest priority
first, oldest first, never SYSTEM.
"""

from __future__ import annotations

from penguin.system.context_window import ContextWindowManager
from penguin.system.state import Message, MessageCategory, Session


def _message(category: MessageCategory, size: int, role: str = "user") -> Message:
    return Message(role=role, content="x" * size, category=category)


def test_a_session_over_the_window_is_trimmed_by_priority() -> None:
    cwm = ContextWindowManager(token_counter=lambda content: len(str(content)))
    cwm.max_context_window_tokens = 1000
    cwm._initialize_token_budgets()
    session = Session()
    system = _message(MessageCategory.SYSTEM, 90, role="system")
    context = _message(MessageCategory.CONTEXT, 290)
    dialog = _message(MessageCategory.DIALOG, 390)
    output = _message(MessageCategory.SYSTEM_OUTPUT, 190, role="tool")
    error = _message(MessageCategory.ERROR, 45, role="system")
    for message in (system, context, dialog, output, error):
        session.add_message(message)
    for category, tokens in cwm.analyze_session(session)["per_category"].items():
        assert tokens <= cwm._budgets[category].max_category_tokens

    trimmed = cwm.process_session(session)

    kept = {message.id for message in trimmed.messages}
    assert cwm.analyze_session(trimmed)["total_tokens"] <= 1000
    assert error.id not in kept  # the lowest-priority category goes first
    assert {system.id, context.id, dialog.id, output.id} <= kept
