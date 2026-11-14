"""Penguin does not answer comments written by a bot, including its own (SM-11)."""

from __future__ import annotations

from typing import Any

import pytest

from penguin.web.integrations import github_webhook


def _payload(user: dict[str, Any], body: str) -> dict[str, Any]:
    return {
        "action": "created",
        "comment": {"body": body, "user": user},
        "issue": {"number": 7, "pull_request": {}},
        "repository": {"full_name": "owner/repo"},
        "sender": user,
    }


@pytest.fixture
def handled(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def record(name: str):
        async def handler(*_args: Any, **_kwargs: Any) -> None:
            calls.append(name)

        return handler

    for name in (
        "handle_review_command",
        "handle_fix_command",
        "handle_plan_command",
        "handle_summarize_command",
        "handle_followup_question",
    ):
        monkeypatch.setattr(github_webhook, name, record(name))
    return calls


OWN_COMMENT = (
    "✅ **Review complete!**\n\nLooks fine.\n\n---\n"
    "*💡 You can ask follow-up questions like: `@Penguin explain the security "
    "concern` or `@Penguin how would you fix line 407?`*"
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user",
    [
        {"login": "penguin-agent[bot]", "type": "Bot"},
        {"login": "some-app[bot]", "type": "User"},
        {"login": "dependabot", "type": "Bot"},
    ],
)
async def test_bot_comments_are_ignored(
    handled: list[str], user: dict[str, Any]
) -> None:
    await github_webhook.handle_issue_comment(_payload(user, OWN_COMMENT), core=None)

    assert handled == []


@pytest.mark.asyncio
async def test_human_mentions_are_still_handled(handled: list[str]) -> None:
    user = {"login": "maintainer", "type": "User"}

    await github_webhook.handle_issue_comment(
        _payload(user, "@Penguin review"), core=None
    )

    assert handled == ["handle_review_command"]
