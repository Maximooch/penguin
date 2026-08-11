"""Validated configuration for the optional Telegram integration."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from penguin.integrations.telegram.binding_policy import (
    TelegramBinding,
    TelegramBindingPolicy,
)

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}
_PERMISSION_RANK = {"read_only": 0, "workspace": 1, "full_access": 2}
_APPROVAL_ACTIONS = (
    "shell",
    "fileWrite",
    "fileDelete",
    "gitPush",
    "network",
    "secrets",
)


@dataclass(frozen=True)
class TelegramConfig:
    """Fail-closed Telegram settings loaded from Penguin config and the environment."""

    enabled: bool = False
    token: str | None = field(default=None, repr=False)
    expected_username: str = "Penguin_agent_bot"
    transport: str = "polling"
    dm_policy: str = "allowlist"
    allow_from: frozenset[int] = frozenset()
    group_policy: str = "allowlist"
    allowed_group_ids: frozenset[int] = frozenset()
    allowed_group_sender_ids: frozenset[int] = frozenset()
    activation: str = "mention"
    binding_policy: TelegramBindingPolicy = field(
        default_factory=lambda: TelegramBindingPolicy.from_mapping(None)
    )
    streaming_mode: str = "progress"
    edit_interval_ms: int = 750
    include_reasoning: bool = False
    max_download_bytes: int = 20 * 1024 * 1024
    max_document_text_chars: int = 100_000
    permission_mode: str = "workspace"
    approvals: str = "prompt"
    approval_timeout_seconds: float = 300.0
    allow_yolo: bool = False
    retry_attempts: int = 8
    retry_base_seconds: float = 1.0
    retry_max_seconds: float = 300.0
    dead_letter_after_hours: int = 24
    poll_timeout_seconds: float = 30.0
    request_timeout_seconds: float = 30.0
    webhook_timeout_seconds: float = 10.0
    webhook_body_limit_bytes: int = 1024 * 1024
    ingress_workers: int = 2
    delivery_workers: int = 2
    webhook_public_url: str | None = None
    webhook_path: str = "/api/v1/integrations/telegram/webhook"
    webhook_secret: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Keep direct construction consistent with parsed configuration."""

        if self.binding_policy.default.activation != self.activation:
            object.__setattr__(
                self,
                "binding_policy",
                self.binding_policy.with_default_activation(self.activation),
            )

    @classmethod
    def from_mapping(
        cls,
        raw_config: Mapping[str, Any] | None,
        environ: Mapping[str, str] | None = None,
    ) -> TelegramConfig:
        """Load a config without ever accepting an inline bot token."""
        raw = raw_config or {}
        data = _telegram_section(raw)
        env = os.environ if environ is None else environ

        _reject_inline_secrets(data)
        enabled = _as_bool(data.get("enabled"), default=False, name="enabled")
        transport = _choice(
            data.get("transport", "polling"),
            {"polling", "webhook"},
            "transport",
        )
        token = _secret(env.get("TELEGRAM_BOT_TOKEN")) if enabled else None
        if enabled and token is None:
            raise ValueError("Telegram is enabled but TELEGRAM_BOT_TOKEN is not set")

        webhook = _mapping(data.get("webhook"), "webhook")
        secret = (
            _secret(env.get("TELEGRAM_WEBHOOK_SECRET"))
            if enabled and transport == "webhook"
            else None
        )
        if enabled and transport == "webhook" and secret is None:
            raise ValueError("Telegram webhook mode requires TELEGRAM_WEBHOOK_SECRET")

        dm_policy = _choice(
            data.get("dm_policy", "allowlist"),
            {"pairing", "allowlist", "open", "disabled"},
            "dm_policy",
        )
        group_policy = _choice(
            data.get("group_policy", "allowlist"),
            {"allowlist", "open", "disabled"},
            "group_policy",
        )
        open_acknowledged = _as_bool(
            data.get("open_access_acknowledged"),
            default=False,
            name="open_access_acknowledged",
        )
        if "open" in {dm_policy, group_policy} and not open_acknowledged:
            raise ValueError(
                "Open Telegram access requires open_access_acknowledged: true"
            )

        permissions = _mapping(data.get("permissions"), "permissions")
        requested_mode = _choice(
            permissions.get("mode", "workspace"),
            set(_PERMISSION_RANK),
            "permissions.mode",
        )
        permission_mode = _cap_permission_mode(requested_mode, raw)
        approvals = _choice(
            permissions.get("approvals", "prompt"),
            {"prompt", "deny"},
            "permissions.approvals",
        )
        allow_yolo = _as_bool(
            permissions.get("allow_yolo"),
            default=False,
            name="permissions.allow_yolo",
        )
        if allow_yolo:
            raise ValueError("Telegram cannot opt in to PENGUIN_YOLO")
        if enabled and _as_bool(
            env.get("PENGUIN_YOLO"), default=False, name="PENGUIN_YOLO"
        ):
            raise ValueError("Telegram cannot run while PENGUIN_YOLO is enabled")
        security = _mapping(raw.get("security"), "security")
        if enabled and not _as_bool(
            security.get("enabled"), default=True, name="security.enabled"
        ):
            raise ValueError("Telegram requires Penguin security enforcement")

        streaming = _mapping(data.get("streaming"), "streaming")
        media = _mapping(data.get("media"), "media")
        delivery = _mapping(data.get("delivery"), "delivery")
        runtime = _mapping(data.get("runtime"), "runtime")
        activation = _choice(
            data.get("activation", "mention"),
            {"always", "mention"},
            "activation",
        )
        binding_policy = TelegramBindingPolicy.from_mapping(
            data.get("groups"),
            default_activation=activation,
        )

        max_download_mb = _bounded_int(
            media.get("max_download_mb", 20),
            1,
            50,
            "media.max_download_mb",
        )
        retry_base = _bounded_float(
            delivery.get("retry_base_seconds", 1.0),
            0.1,
            60.0,
            "delivery.retry_base_seconds",
        )
        retry_max = _bounded_float(
            delivery.get("retry_max_seconds", 300.0),
            retry_base,
            3600.0,
            "delivery.retry_max_seconds",
        )

        username = str(data.get("expected_username") or "Penguin_agent_bot")
        username = username.removeprefix("@")
        if not re.fullmatch(
            r"[A-Za-z0-9_]{5,32}", username
        ) or not username.lower().endswith("bot"):
            raise ValueError("expected_username is not a valid Telegram bot username")

        webhook_path = str(
            webhook.get("path") or "/api/v1/integrations/telegram/webhook"
        )
        if webhook_path != "/api/v1/integrations/telegram/webhook":
            raise ValueError(
                "webhook.path must be /api/v1/integrations/telegram/webhook"
            )

        return cls(
            enabled=enabled,
            token=token,
            expected_username=username,
            transport=transport,
            dm_policy=dm_policy,
            allow_from=_numeric_ids(data.get("allow_from"), "allow_from"),
            group_policy=group_policy,
            allowed_group_ids=_numeric_ids(
                data.get("allowed_group_ids", data.get("group_allow_from")),
                "group_allow_from",
                positive_only=False,
            ),
            allowed_group_sender_ids=_numeric_ids(
                data.get(
                    "allowed_group_sender_ids",
                    data.get("group_sender_allow_from"),
                ),
                "group_sender_allow_from",
            ),
            activation=activation,
            binding_policy=binding_policy,
            streaming_mode=_choice(
                streaming.get("mode", "progress"),
                {"off", "edit", "progress"},
                "streaming.mode",
            ),
            edit_interval_ms=_bounded_int(
                streaming.get("edit_interval_ms", 750),
                250,
                10_000,
                "streaming.edit_interval_ms",
            ),
            include_reasoning=_as_bool(
                streaming.get("include_reasoning"),
                default=False,
                name="streaming.include_reasoning",
            ),
            max_download_bytes=max_download_mb * 1024 * 1024,
            max_document_text_chars=_bounded_int(
                media.get("max_document_text_chars", 100_000),
                1,
                1_000_000,
                "media.max_document_text_chars",
            ),
            permission_mode=permission_mode,
            approvals=approvals,
            approval_timeout_seconds=_bounded_float(
                permissions.get("timeout_seconds", 300.0),
                30.0,
                3600.0,
                "permissions.timeout_seconds",
            ),
            allow_yolo=False,
            retry_attempts=_bounded_int(
                delivery.get("retry_attempts", 8),
                1,
                20,
                "delivery.retry_attempts",
            ),
            retry_base_seconds=retry_base,
            retry_max_seconds=retry_max,
            dead_letter_after_hours=_bounded_int(
                delivery.get("dead_letter_after_hours", 24),
                1,
                720,
                "delivery.dead_letter_after_hours",
            ),
            poll_timeout_seconds=_bounded_float(
                runtime.get("poll_timeout_seconds", 30.0),
                1.0,
                50.0,
                "runtime.poll_timeout_seconds",
            ),
            request_timeout_seconds=_bounded_float(
                runtime.get("request_timeout_seconds", 30.0),
                1.0,
                120.0,
                "runtime.request_timeout_seconds",
            ),
            webhook_timeout_seconds=_bounded_float(
                webhook.get("timeout_seconds", 10.0),
                1.0,
                30.0,
                "webhook.timeout_seconds",
            ),
            webhook_body_limit_bytes=_bounded_int(
                webhook.get("body_limit_bytes", 1024 * 1024),
                1024,
                10 * 1024 * 1024,
                "webhook.body_limit_bytes",
            ),
            ingress_workers=_bounded_int(
                runtime.get("ingress_workers", 2),
                1,
                16,
                "runtime.ingress_workers",
            ),
            delivery_workers=_bounded_int(
                runtime.get("delivery_workers", 2),
                1,
                16,
                "runtime.delivery_workers",
            ),
            webhook_public_url=_optional_string(webhook.get("public_url")),
            webhook_path=webhook_path,
            webhook_secret=secret,
        )

    @property
    def approval_policy(self) -> dict[str, Any]:
        """Return the request policy consumed by Penguin's permission checks."""
        decision = "ask" if self.approvals == "prompt" else "deny"
        policy = {
            **{action: decision for action in _APPROVAL_ACTIONS},
            "default": decision,
            "allowLists": {},
            "timeout_seconds": self.approval_timeout_seconds,
        }
        if self.approvals == "prompt":
            policy["wait_for_resolution"] = True
        return policy

    def allows_dm(self, user_id: int) -> bool:
        """Return whether policy alone admits a DM; pairing grants live elsewhere."""
        return self.dm_policy == "open" or (
            self.dm_policy == "allowlist" and user_id in self.allow_from
        )

    def allows_group_sender(self, user_id: int) -> bool:
        """Return whether policy alone admits a sender in a group."""
        return self.group_policy == "open" or (
            self.group_policy == "allowlist"
            and user_id in self.allowed_group_sender_ids
        )

    def allows_group(self, chat_id: int) -> bool:
        """Return whether policy alone admits a Telegram group chat."""
        return self.group_policy == "open" or (
            self.group_policy == "allowlist" and chat_id in self.allowed_group_ids
        )

    def binding_for(
        self,
        chat_id: int | str,
        topic_id: int | str | None = None,
    ) -> TelegramBinding:
        """Resolve trusted execution settings for a Telegram group or topic."""

        return self.binding_policy.resolve(chat_id, topic_id)


def _telegram_section(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    channels = raw.get("channels")
    if isinstance(channels, Mapping):
        telegram = channels.get("telegram")
        if isinstance(telegram, Mapping):
            return telegram
    telegram = raw.get("telegram")
    return telegram if isinstance(telegram, Mapping) else {}


def _reject_inline_secrets(data: Mapping[str, Any]) -> None:
    for name in ("token", "bot_token", "token_file", "proxy_url"):
        if data.get(name) not in (None, ""):
            raise ValueError(f"Telegram {name} must not be stored in config")
    token_env = data.get("token_env")
    if token_env not in (None, "", "TELEGRAM_BOT_TOKEN"):
        raise ValueError("Telegram token_env must be TELEGRAM_BOT_TOKEN")
    webhook = _mapping(data.get("webhook"), "webhook")
    for name in ("secret", "secret_token"):
        if webhook.get(name) not in (None, ""):
            raise ValueError("Telegram webhook secret must not be stored in config")
    secret_env = webhook.get("secret_env")
    if secret_env not in (None, "", "TELEGRAM_WEBHOOK_SECRET"):
        raise ValueError("Telegram webhook.secret_env must be TELEGRAM_WEBHOOK_SECRET")


def _cap_permission_mode(requested: str, raw: Mapping[str, Any]) -> str:
    security = _mapping(raw.get("security"), "security")
    instance = str(security.get("mode", "workspace")).strip().lower()
    if instance == "full":
        instance = "full_access"
    if instance not in _PERMISSION_RANK:
        instance = "workspace"
    ceiling = min(_PERMISSION_RANK[requested], _PERMISSION_RANK[instance])
    return next(mode for mode, rank in _PERMISSION_RANK.items() if rank == ceiling)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    return value


def _as_bool(value: Any, *, default: bool, name: str) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in _TRUE:
        return True
    if normalized in _FALSE:
        return False
    raise ValueError(f"{name} must be a boolean")


def _choice(value: Any, choices: set[str], name: str) -> str:
    normalized = str(value).strip().lower()
    if normalized not in choices:
        allowed = ", ".join(sorted(choices))
        raise ValueError(f"{name} must be one of: {allowed}")
    return normalized


def _bounded_int(value: Any, minimum: int, maximum: int, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if isinstance(value, bool) or not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _bounded_float(value: Any, minimum: float, maximum: float, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if isinstance(value, bool) or not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _numeric_ids(
    value: Any, name: str, *, positive_only: bool = True
) -> frozenset[int]:
    if value in (None, ""):
        return frozenset()
    if not isinstance(value, (list, tuple, set, frozenset)):
        raise ValueError(f"{name} must be a list of numeric Telegram user ids")
    parsed: set[int] = set()
    for item in value:
        if isinstance(item, bool):
            raise ValueError(f"{name} must contain only numeric Telegram user ids")
        try:
            user_id = int(item)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{name} must contain only numeric Telegram user ids"
            ) from exc
        if (
            user_id == 0
            or (positive_only and user_id < 0)
            or str(item).strip() != str(user_id)
        ):
            raise ValueError(f"{name} must contain only numeric Telegram user ids")
        parsed.add(user_id)
    return frozenset(parsed)


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _secret(value: Any) -> str | None:
    return _optional_string(value)


__all__ = ["TelegramConfig"]
