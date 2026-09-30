from copy import deepcopy

import pytest

from penguin.system.context_epoch import ContextEpoch
from penguin.system.context_window import ContextWindowManager
from penguin.system.state import Message, MessageCategory, Session
from penguin.utils.errors import ContextWindowExceededError


def message(text, category=MessageCategory.DIALOG):
    return Message(role="user", content=text, category=category)


def manager(limit=100):
    result = ContextWindowManager(token_counter=lambda content: len(str(content)))
    result.max_context_window_tokens = limit
    for budget in result._budgets.values():
        budget.max_category_tokens = limit
    return result


def test_selection_does_not_mutate_transcript():
    source = Session(messages=[message("x" * 120), message("latest")])
    original = deepcopy(source)
    packet = ContextEpoch().select(source, manager())
    assert source == original
    assert len(packet.messages) < len(source.messages)


def test_append_preserves_boundaries_and_isolation():
    source = Session(messages=[message("hello")])
    epoch = ContextEpoch()
    first = epoch.select(source, manager())
    first.messages[0].content = "external mutation"
    source.messages.append(message("world"))
    second = epoch.select(source, manager())
    assert [m.content for m in second.messages] == ["hello", "world"]
    assert epoch.generation == 1
    assert epoch.reason == "append"


def test_source_edit_rebases():
    source = Session(messages=[message("old")])
    epoch = ContextEpoch()
    epoch.select(source, manager())
    source.messages[0].content = "revoked"
    packet = epoch.select(source, manager())
    assert packet.messages[0].content == "revoked"
    assert epoch.reason == "source_changed"
    assert epoch.generation == 2


def test_new_system_instruction_rebases():
    source = Session(messages=[message("hello")])
    epoch = ContextEpoch()
    epoch.select(source, manager())
    source.messages.append(message("permission revoked", MessageCategory.SYSTEM))
    epoch.select(source, manager())
    assert epoch.reason == "prefix_changed"


def test_overflow_rebases_without_deleting_history():
    source = Session(messages=[message("a" * 70)])
    epoch = ContextEpoch()
    epoch.select(source, manager())
    source.messages.append(message("b" * 70))
    packet = epoch.select(source, manager())
    assert epoch.reason == "safety_limit"
    assert len(source.messages) == 2
    assert sum(m.tokens for m in packet.messages) <= 100


def test_oversized_system_fails_closed():
    source = Session(messages=[message("x" * 101, MessageCategory.SYSTEM)])
    with pytest.raises(ContextWindowExceededError, match="exceeds"):
        ContextEpoch().select(source, manager())


def test_session_switch_does_not_reuse_selection():
    epoch = ContextEpoch()
    epoch.select(Session(id="a", messages=[message("a")]), manager())
    packet = epoch.select(Session(id="b", messages=[message("b")]), manager())
    assert packet.messages[0].content == "b"
    assert epoch.generation == 2


def test_model_limit_change_rebases():
    source = Session(messages=[message("a" * 60), message("b" * 20)])
    epoch = ContextEpoch()
    epoch.select(source, manager())
    packet = epoch.select(source, manager(50))
    assert epoch.generation == 2
    assert sum(m.tokens for m in packet.messages) <= 50


def test_prefix_diagnostics_do_not_retain_content():
    from penguin.system.request_prefix import RequestPrefix

    prefix = RequestPrefix()
    first = [{"role": "user", "content": "private"}]
    prefix.compare(first, [])
    result = prefix.compare([*first, {"role": "assistant", "content": "tail"}], [])
    assert result["common_items"] == 1
    assert result["first_changed_item"] is None
    assert "private" not in repr(prefix)
    result = prefix.compare([{"role": "user", "content": "changed"}], ["new tool"])
    assert result["first_changed_item"] == 0
    assert result["tools_changed"]


def test_edit_recounts_cached_tokens():
    source = Session(messages=[message("short")])
    epoch = ContextEpoch()
    epoch.select(source, manager())
    source.messages[0].tokens = 5
    source.messages[0].content = "x" * 101
    assert not epoch.select(source, manager()).messages


def test_formatted_selection_preserves_saved_history():
    from penguin.system.conversation import ConversationSystem

    conv = ConversationSystem(context_window_manager=manager())
    conv.add_message("user", "x" * 120)
    conv.add_message("user", "latest")
    original = deepcopy(conv.session)
    assert conv.get_formatted_messages() == [{"role": "user", "content": "latest"}]
    assert conv.session == original


def test_rebase_preserves_source_order_not_timestamps():
    source = Session(messages=[message("first"), message("second")])
    source.messages[0].timestamp = "z"
    source.messages[1].timestamp = "a"
    assert [m.content for m in ContextEpoch().select(source, manager()).messages] == [
        "first",
        "second",
    ]


def test_partial_tool_exchange_is_dropped_as_unit():
    assistant = Message(
        role="assistant",
        content="call",
        category=MessageCategory.DIALOG,
        metadata={"tool_calls": [{"id": "call-1"}]},
    )
    tool = Message(
        role="tool",
        content="x" * 120,
        category=MessageCategory.SYSTEM_OUTPUT,
        metadata={"tool_call_id": "call-1"},
    )
    source = Session(messages=[assistant, tool, message("latest")])
    packet = ContextEpoch().select(source, manager())
    assert [m.content for m in packet.messages] == ["latest"]
    assert len(source.messages) == 3
