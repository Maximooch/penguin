"""One grammar for action tags: what is stripped is exactly what is executed."""

from __future__ import annotations

import pytest

from penguin.utils.parser import (
    parse_action,
    strip_action_tags,
    strip_incomplete_action_tags,
)


@pytest.mark.parametrize(
    "content",
    [
        "<execute>print(1)</execute>",
        "<EXECUTE>print(1)</EXECUTE>",
        "<Execute>print(1)</Execute>",
        "<execute>print(1)</EXECUTE>",
    ],
)
def test_a_tag_removed_from_history_is_also_executed(content: str) -> None:
    actions = parse_action(f"before {content} after")

    assert strip_action_tags(f"before {content} after") == "before  after"
    assert [action.params for action in actions] == ["print(1)"]


@pytest.mark.parametrize(
    "content",
    [
        "check whether a < b and continue",
        "the loop runs while i <= 3",
        "use a List<int for the buffer",
        "compare x<y",
    ],
)
def test_prose_with_a_less_than_sign_is_kept(content: str) -> None:
    assert strip_incomplete_action_tags(content) == content


@pytest.mark.parametrize(
    "content,expected",
    [
        ("done <exec", "done"),
        ("done <", "done"),
        ("done </finish_resp", "done"),
        ("done <finish_response>half written", "done"),
        ("done <FINISH_RESPONSE>half written", "done"),
    ],
)
def test_interrupted_action_tag_is_removed(content: str, expected: str) -> None:
    assert strip_incomplete_action_tags(content) == expected
