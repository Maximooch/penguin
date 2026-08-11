"""Validated per-group and per-topic Telegram execution bindings."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, cast

_MISSING = object()
_BINDING_KEYS = {
    "enabled",
    "require_mention",
    "activation",
    "history_limit",
    "prompt",
    "directory",
    "agent_id",
    "mode",
    "skills",
}
_GROUP_KEYS = _BINDING_KEYS | {"topics"}
_SKILL_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
_AGENT_ID = re.compile(r"^[a-z0-9_-]{1,64}$")
_MAX_GROUPS = 1_000
_MAX_TOPICS_PER_GROUP = 1_000
_MAX_HISTORY = 200
_MAX_PROMPT_CHARS = 16_000
_MAX_SKILLS = 16


@dataclass(frozen=True)
class TelegramBinding:
    """Fully resolved settings for one Telegram group or topic."""

    enabled: bool = True
    activation: str = "mention"
    history_limit: int = 20
    prompt: str | None = None
    directory: str | None = None
    agent_id: str | None = None
    mode: str = "build"
    skills: tuple[str, ...] = ()

    def durable_settings(self) -> dict[str, Any]:
        """Return bounded execution settings stored with a new session binding."""

        return {
            "activation": self.activation,
            "history_limit": self.history_limit,
            "prompt": self.prompt,
            "skills": list(self.skills),
        }


@dataclass(frozen=True)
class _BindingOverride:
    enabled: bool | object = _MISSING
    activation: str | object = _MISSING
    history_limit: int | object = _MISSING
    prompt: str | object | None = _MISSING
    directory: str | object | None = _MISSING
    agent_id: str | object | None = _MISSING
    mode: str | object = _MISSING
    skills: tuple[str, ...] | object = _MISSING

    def apply(self, parent: TelegramBinding) -> TelegramBinding:
        """Apply this override without allowing a topic to re-enable its group."""

        enabled = parent.enabled
        if self.enabled is not _MISSING:
            enabled = parent.enabled and bool(self.enabled)
        return TelegramBinding(
            enabled=enabled,
            activation=(
                parent.activation
                if self.activation is _MISSING
                else str(self.activation)
            ),
            history_limit=(
                parent.history_limit
                if self.history_limit is _MISSING
                else int(self.history_limit)
            ),
            prompt=(
                parent.prompt if self.prompt is _MISSING else _optional(self.prompt)
            ),
            directory=(
                parent.directory
                if self.directory is _MISSING
                else _optional(self.directory)
            ),
            agent_id=(
                parent.agent_id
                if self.agent_id is _MISSING
                else _optional(self.agent_id)
            ),
            mode=parent.mode if self.mode is _MISSING else str(self.mode),
            skills=(
                parent.skills
                if self.skills is _MISSING
                else cast("tuple[str, ...]", self.skills)
            ),
        )


@dataclass(frozen=True)
class _GroupRule:
    override: _BindingOverride
    topics: Mapping[int, _BindingOverride]


@dataclass(frozen=True)
class TelegramBindingPolicy:
    """Resolve trusted config overrides using global → group → topic order."""

    default: TelegramBinding
    groups: Mapping[int, _GroupRule]

    def with_default_activation(self, activation: str) -> TelegramBindingPolicy:
        """Return this policy rebased onto the configured global activation."""

        if activation not in {"always", "mention"}:
            raise ValueError("default activation must be always or mention")
        return TelegramBindingPolicy(
            default=replace(self.default, activation=activation),
            groups=self.groups,
        )

    @classmethod
    def from_mapping(
        cls,
        value: Any,
        *,
        default_activation: str = "mention",
    ) -> TelegramBindingPolicy:
        """Parse the ``groups`` config mapping and reject ambiguous input."""

        if value is None:
            raw_groups: Mapping[Any, Any] = {}
        elif isinstance(value, Mapping):
            raw_groups = value
        else:
            raise ValueError("groups must be a mapping keyed by numeric chat ids")
        if len(raw_groups) > _MAX_GROUPS:
            raise ValueError(f"groups must contain at most {_MAX_GROUPS} entries")
        if default_activation not in {"always", "mention"}:
            raise ValueError("default activation must be always or mention")

        groups: dict[int, _GroupRule] = {}
        for raw_group_id, raw_rule in raw_groups.items():
            group_id = _numeric_id(raw_group_id, "groups key", positive_only=False)
            if group_id in groups:
                raise ValueError(f"duplicate Telegram group id: {group_id}")
            if not isinstance(raw_rule, Mapping):
                raise ValueError(f"groups.{group_id} must be a mapping")
            _reject_unknown_keys(raw_rule, _GROUP_KEYS, f"groups.{group_id}")

            raw_topics = raw_rule.get("topics", {})
            if raw_topics is None:
                raw_topics = {}
            if not isinstance(raw_topics, Mapping):
                raise ValueError(f"groups.{group_id}.topics must be a mapping")
            if len(raw_topics) > _MAX_TOPICS_PER_GROUP:
                raise ValueError(
                    f"groups.{group_id}.topics must contain at most "
                    f"{_MAX_TOPICS_PER_GROUP} entries"
                )
            topics: dict[int, _BindingOverride] = {}
            for raw_topic_id, raw_topic in raw_topics.items():
                topic_id = _numeric_id(
                    raw_topic_id,
                    f"groups.{group_id}.topics key",
                    positive_only=True,
                )
                if topic_id in topics:
                    raise ValueError(
                        f"duplicate Telegram topic id {topic_id} in group {group_id}"
                    )
                if not isinstance(raw_topic, Mapping):
                    raise ValueError(
                        f"groups.{group_id}.topics.{topic_id} must be a mapping"
                    )
                _reject_unknown_keys(
                    raw_topic,
                    _BINDING_KEYS,
                    f"groups.{group_id}.topics.{topic_id}",
                )
                topics[topic_id] = _parse_override(
                    raw_topic,
                    f"groups.{group_id}.topics.{topic_id}",
                )

            groups[group_id] = _GroupRule(
                override=_parse_override(raw_rule, f"groups.{group_id}"),
                topics=MappingProxyType(topics),
            )

        return cls(
            default=TelegramBinding(activation=default_activation),
            groups=MappingProxyType(groups),
        )

    def resolve(
        self, chat_id: int | str, topic_id: int | str | None = None
    ) -> TelegramBinding:
        """Return the deterministic binding for a numeric Telegram address."""

        group_id = _numeric_id(chat_id, "chat_id", positive_only=False)
        parsed_topic_id = (
            None
            if topic_id in (None, "")
            else _numeric_id(topic_id, "topic_id", positive_only=True)
        )
        group = self.groups.get(group_id)
        resolved = self.default if group is None else group.override.apply(self.default)
        if parsed_topic_id is None or group is None:
            return resolved
        topic = group.topics.get(parsed_topic_id)
        return resolved if topic is None else topic.apply(resolved)


def _parse_override(value: Mapping[str, Any], path: str) -> _BindingOverride:
    activation = _MISSING
    if "activation" in value:
        activation = _choice(
            value["activation"], {"always", "mention"}, f"{path}.activation"
        )
    if "require_mention" in value:
        require_mention = _bool(value["require_mention"], f"{path}.require_mention")
        alias_activation = "mention" if require_mention else "always"
        if activation is not _MISSING and activation != alias_activation:
            raise ValueError(f"{path}.activation conflicts with {path}.require_mention")
        activation = alias_activation

    return _BindingOverride(
        enabled=(
            _bool(value["enabled"], f"{path}.enabled")
            if "enabled" in value
            else _MISSING
        ),
        activation=activation,
        history_limit=(
            _bounded_int(
                value["history_limit"], 0, _MAX_HISTORY, f"{path}.history_limit"
            )
            if "history_limit" in value
            else _MISSING
        ),
        prompt=(
            _prompt(value["prompt"], f"{path}.prompt")
            if "prompt" in value
            else _MISSING
        ),
        directory=(
            _directory(value["directory"], f"{path}.directory")
            if "directory" in value
            else _MISSING
        ),
        agent_id=(
            _agent(value["agent_id"], f"{path}.agent_id")
            if "agent_id" in value
            else _MISSING
        ),
        mode=(
            _choice(value["mode"], {"build", "plan"}, f"{path}.mode")
            if "mode" in value
            else _MISSING
        ),
        skills=(
            _skills(value["skills"], f"{path}.skills")
            if "skills" in value
            else _MISSING
        ),
    )


def _reject_unknown_keys(
    value: Mapping[str, Any], allowed: set[str], path: str
) -> None:
    unknown = sorted(str(key) for key in value if key not in allowed)
    if unknown:
        raise ValueError(f"{path} contains unknown fields: {', '.join(unknown)}")


def _numeric_id(value: Any, name: str, *, positive_only: bool) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a numeric Telegram id")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a numeric Telegram id") from exc
    if (
        parsed == 0
        or (positive_only and parsed < 0)
        or str(value).strip() != str(parsed)
    ):
        raise ValueError(f"{name} must be a canonical numeric Telegram id")
    return parsed


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def _choice(value: Any, choices: set[str], name: str) -> str:
    if not isinstance(value, str) or value.strip().lower() not in choices:
        raise ValueError(f"{name} must be one of: {', '.join(sorted(choices))}")
    return value.strip().lower()


def _bounded_int(value: Any, minimum: int, maximum: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _prompt(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string or null")
    prompt = value.strip()
    if not prompt or "\x00" in prompt or len(prompt) > _MAX_PROMPT_CHARS:
        raise ValueError(
            f"{name} must contain 1-{_MAX_PROMPT_CHARS} characters without NUL"
        )
    return prompt


def _directory(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be an absolute existing directory or null")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{name} must be an absolute existing directory or null")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError(
            f"{name} must be an absolute existing directory or null"
        ) from exc
    if not resolved.is_dir():
        raise ValueError(f"{name} must be an absolute existing directory or null")
    return str(resolved)


def _agent(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _AGENT_ID.fullmatch(value.strip()) is None:
        raise ValueError(f"{name} must match ^[a-z0-9_-]{{1,64}}$ or be null")
    return value.strip()


def _skills(value: Any, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > _MAX_SKILLS:
        raise ValueError(f"{name} must be a list of at most {_MAX_SKILLS} skill names")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or _SKILL_NAME.fullmatch(item.strip()) is None:
            raise ValueError(f"{name} must contain lowercase kebab-case skill names")
        normalized = item.strip()
        if normalized not in result:
            result.append(normalized)
    return tuple(result)


def _optional(value: object) -> str | None:
    return value if isinstance(value, str) else None


__all__ = ["TelegramBinding", "TelegramBindingPolicy"]
