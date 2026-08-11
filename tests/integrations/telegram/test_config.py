from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from penguin.integrations.telegram.config import TelegramConfig

if TYPE_CHECKING:
    from pathlib import Path


def _config(**telegram: object) -> dict[str, object]:
    return {"channels": {"telegram": telegram}}


def test_defaults_are_disabled_and_fail_closed() -> None:
    config = TelegramConfig.from_mapping(
        {"enabled": True, "allow_from": [123]},
        {},
    )

    assert config.enabled is False
    assert config.token is None
    assert config.expected_username == "Penguin_agent_bot"
    assert config.transport == "polling"
    assert config.allows_dm(123) is False
    assert config.allows_group(-100123) is False
    assert config.allows_group_sender(123) is False
    assert config.activation == "mention"
    assert config.permission_mode == "workspace"
    assert config.approval_policy["shell"] == "ask"
    assert config.approval_policy["default"] == "ask"
    assert config.approval_policy["allowLists"] == {}


def test_direct_config_construction_rebases_binding_activation() -> None:
    config = TelegramConfig(activation="always")

    assert config.binding_for(-100).activation == "always"


def test_token_comes_only_from_fixed_environment_variable_and_is_redacted() -> None:
    disabled = TelegramConfig.from_mapping(
        {}, {"TELEGRAM_BOT_TOKEN": "unused-test-token"}
    )
    config = TelegramConfig.from_mapping(
        _config(enabled=True), {"TELEGRAM_BOT_TOKEN": "test-token"}
    )

    assert disabled.token is None
    assert config.token == "test-token"
    assert "test-token" not in repr(config)

    with pytest.raises(ValueError, match="must not be stored"):
        TelegramConfig.from_mapping(_config(token="inline"), {})
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        TelegramConfig.from_mapping(_config(token_env="SOME_OTHER_ENV"), {})


def test_enabled_bot_requires_token() -> None:
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        TelegramConfig.from_mapping(_config(enabled=True), {})


def test_numeric_allowlists_are_normalized_and_default_deny() -> None:
    config = TelegramConfig.from_mapping(
        _config(
            allow_from=[123, "456"],
            group_allow_from=[-100789],
            group_sender_allow_from=[789],
        ),
        {},
    )

    assert config.allow_from == frozenset({123, 456})
    assert config.allowed_group_ids == frozenset({-100789})
    assert config.allowed_group_sender_ids == frozenset({789})
    assert config.allows_dm(123) is True
    assert config.allows_dm(999) is False
    assert config.allows_group(-100789) is True
    assert config.allows_group(-100999) is False
    assert config.allows_group_sender(789) is True

    with pytest.raises(ValueError, match="numeric"):
        TelegramConfig.from_mapping(_config(allow_from=["username"]), {})


def test_open_access_requires_explicit_acknowledgement() -> None:
    with pytest.raises(ValueError, match="open_access_acknowledged"):
        TelegramConfig.from_mapping(_config(dm_policy="open"), {})

    config = TelegramConfig.from_mapping(
        _config(dm_policy="open", open_access_acknowledged=True), {}
    )
    assert config.allows_dm(999) is True


def test_webhook_mode_requires_secret_and_validates_transport() -> None:
    env = {"TELEGRAM_BOT_TOKEN": "test-token"}
    with pytest.raises(ValueError, match="TELEGRAM_WEBHOOK_SECRET"):
        TelegramConfig.from_mapping(_config(enabled=True, transport="webhook"), env)

    config = TelegramConfig.from_mapping(
        _config(enabled=True, transport="webhook"),
        {**env, "TELEGRAM_WEBHOOK_SECRET": "test-secret"},
    )
    assert config.transport == "webhook"
    assert config.webhook_secret == "test-secret"
    assert "test-secret" not in repr(config)

    with pytest.raises(ValueError, match="transport"):
        TelegramConfig.from_mapping(_config(transport="both"), {})

    with pytest.raises(ValueError, match=r"webhook\.path"):
        TelegramConfig.from_mapping(
            _config(webhook={"path": "/api/v1/integrations/telegram/"}),
            {},
        )


def test_remote_permissions_are_prompted_and_capped_by_instance() -> None:
    config = TelegramConfig.from_mapping(
        {
            "security": {"mode": "read_only"},
            "channels": {"telegram": {"permissions": {"mode": "full_access"}}},
        },
        {},
    )

    assert config.permission_mode == "read_only"
    assert config.approval_policy["shell"] == "ask"
    assert config.approval_policy["wait_for_resolution"] is True
    assert config.approval_policy["timeout_seconds"] == 300.0


def test_granular_remote_permissions_preserve_instance_ceiling() -> None:
    config = TelegramConfig.from_mapping(
        {
            "security": {"mode": "workspace"},
            "channels": {
                "telegram": {
                    "permissions": {
                        "mode": "full_access",
                        "approvals": {
                            "shell": "ask",
                            "fileWrite": "allow",
                            "fileDelete": "deny",
                            "gitPush": "deny",
                            "network": "allow",
                            "secrets": "deny",
                            "default": "deny",
                        },
                        "timeout_seconds": 90,
                    }
                }
            },
        },
        {},
    )

    assert config.permission_mode == "workspace"
    assert config.approval_policy == {
        "shell": "ask",
        "fileWrite": "allow",
        "fileDelete": "deny",
        "gitPush": "deny",
        "network": "allow",
        "secrets": "deny",
        "default": "deny",
        "allowLists": {},
        "timeout_seconds": 90.0,
        "wait_for_resolution": True,
    }


def test_granular_remote_permissions_fall_back_to_secure_default() -> None:
    config = TelegramConfig.from_mapping(
        _config(permissions={"approvals": {"network": "allow"}}),
        {},
    )

    assert config.approval_policy["network"] == "allow"
    assert config.approval_policy["shell"] == "ask"
    assert config.approval_policy["default"] == "ask"
    assert config.approval_policy["wait_for_resolution"] is True


def test_legacy_scalar_deny_remains_supported() -> None:
    config = TelegramConfig.from_mapping(
        _config(permissions={"approvals": "deny"}),
        {},
    )

    assert config.approvals == "deny"
    assert config.approval_policy["shell"] == "deny"
    assert config.approval_policy["default"] == "deny"
    assert "wait_for_resolution" not in config.approval_policy


@pytest.mark.parametrize(
    ("approvals", "message"),
    [
        ({"shell": "prompt"}, r"approvals\.shell"),
        ({"futureCategory": "ask"}, "unknown categories"),
        ("allow", "permissions.approvals"),
    ],
)
def test_remote_permissions_reject_ambiguous_decisions(
    approvals: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        TelegramConfig.from_mapping(
            _config(permissions={"approvals": approvals}),
            {},
        )


def test_permissions_summary_is_effective_and_credential_free() -> None:
    config = TelegramConfig.from_mapping(
        _config(
            permissions={
                "mode": "read_only",
                "approvals": {"shell": "deny", "default": "allow"},
                "timeout_seconds": 45,
            }
        ),
        {},
    )

    assert config.permissions_summary == (
        "Telegram permission policy\n"
        "Mode cap: read_only (cannot exceed Penguin security.mode)\n"
        "Approval timeout: 45 seconds\n"
        "Telegram category decisions:\n"
        "- shell: deny\n"
        "- fileWrite: allow\n"
        "- fileDelete: allow\n"
        "- gitPush: allow\n"
        "- network: allow\n"
        "- secrets: allow\n"
        "- default: allow\n"
        "allow means Telegram adds no prompt; Penguin instance or agent policy "
        "can still ASK, and any instance, agent, or workspace DENY still blocks. "
        "YOLO is unavailable."
    )


@pytest.mark.parametrize(
    ("telegram", "message"),
    [
        ({"streaming": {"edit_interval_ms": 10}}, "edit_interval_ms"),
        ({"media": {"max_download_mb": 500}}, "max_download_mb"),
        ({"runtime": {"ingress_workers": 0}}, "ingress_workers"),
        ({"delivery": {"retry_attempts": 100}}, "retry_attempts"),
        (
            {
                "delivery": {
                    "retry_base_seconds": 20,
                    "retry_max_seconds": 10,
                }
            },
            "retry_max_seconds",
        ),
    ],
)
def test_runtime_and_delivery_values_are_bounded(
    telegram: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        TelegramConfig.from_mapping(_config(**telegram), {})


def test_remote_bot_rejects_yolo_and_disabled_security() -> None:
    env = {"TELEGRAM_BOT_TOKEN": "test-token", "PENGUIN_YOLO": "true"}
    with pytest.raises(ValueError, match="PENGUIN_YOLO"):
        TelegramConfig.from_mapping(_config(enabled=True), env)

    with pytest.raises(ValueError, match="security enforcement"):
        TelegramConfig.from_mapping(
            {
                "security": {"enabled": False},
                "channels": {"telegram": {"enabled": True}},
            },
            {"TELEGRAM_BOT_TOKEN": "test-token"},
        )

    with pytest.raises(ValueError, match="cannot opt in"):
        TelegramConfig.from_mapping(_config(permissions={"allow_yolo": True}), {})


def test_group_and_topic_bindings_inherit_deterministically(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    config = TelegramConfig.from_mapping(
        _config(
            activation="mention",
            groups={
                "-100123": {
                    "enabled": True,
                    "require_mention": False,
                    "history_limit": 50,
                    "prompt": "Keep group answers concise.",
                    "directory": str(project),
                    "agent_id": "research_agent",
                    "mode": "plan",
                    "skills": ["ponytail", "browser", "ponytail"],
                    "topics": {
                        "42": {
                            "activation": "mention",
                            "history_limit": 5,
                            "prompt": None,
                            "directory": None,
                            "agent_id": None,
                            "mode": "build",
                            "skills": [],
                        }
                    },
                },
                "-100456": {
                    "enabled": False,
                    "topics": {"7": {"enabled": True}},
                },
            },
        ),
        {},
    )

    group = config.binding_for("-100123")
    assert group.activation == "always"
    assert group.history_limit == 50
    assert group.prompt == "Keep group answers concise."
    assert group.directory == str(project.resolve())
    assert group.agent_id == "research_agent"
    assert group.mode == "plan"
    assert group.skills == ("ponytail", "browser")

    inherited_topic = config.binding_for(-100123, 99)
    assert inherited_topic == group

    topic = config.binding_for(-100123, "42")
    assert topic.enabled is True
    assert topic.activation == "mention"
    assert topic.history_limit == 5
    assert topic.prompt is None
    assert topic.directory is None
    assert topic.agent_id is None
    assert topic.mode == "build"
    assert topic.skills == ()

    assert config.binding_for(-100456, 7).enabled is False
    assert config.binding_for(-100999).activation == "mention"


@pytest.mark.parametrize(
    ("groups", "message"),
    [
        ({"group-name": {}}, "numeric Telegram"),
        ({"-1001": {"topics": {"topic-name": {}}}}, "numeric Telegram"),
        ({"-1001": {"history_limit": 201}}, "history_limit"),
        ({"-1001": {"require_mention": "yes"}}, "boolean"),
        ({"-1001": {"unexpected": True}}, "unknown fields"),
        ({"-1001": {"agent_id": "Upper Case"}}, "agent_id"),
        ({"-1001": {"skills": ["Not-A-Skill"]}}, "kebab-case"),
        (
            {"-1001": {"activation": "always", "require_mention": True}},
            "conflicts",
        ),
    ],
)
def test_group_binding_config_rejects_ambiguous_values(
    groups: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        TelegramConfig.from_mapping(_config(groups=groups), {})


def test_group_binding_rejects_invalid_directory(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(ValueError, match="existing directory"):
        TelegramConfig.from_mapping(
            _config(groups={"-1001": {"directory": str(missing)}}),
            {},
        )

    with pytest.raises(ValueError, match="absolute existing directory"):
        TelegramConfig.from_mapping(
            _config(groups={"-1001": {"directory": "relative/project"}}),
            {},
        )
