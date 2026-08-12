"""Curated, session-scoped Telegram runtime controls."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from penguin.channels.store import CompareAndSwapError
from penguin.core_runtime import process_lifecycle
from penguin.integrations.telegram._session_runtime import (
    SessionRuntimePreferences,
    load_session_runtime_preferences,
    service_tier_for_fast_mode,
    update_session_runtime_preferences,
)
from penguin.integrations.telegram._sessions import (
    SessionAccessError,
    SessionBusyError,
    list_recent_sessions,
    rebind_session,
    with_recent_session,
)

if TYPE_CHECKING:
    from penguin.channels.schema import InboundEnvelope

__all__ = [
    "CONTROL_COMMANDS",
    "ControlResolution",
    "binding_streaming_mode",
    "handle_control_command",
    "resolve_control_callback",
]

logger = logging.getLogger(__name__)

CONTROL_COMMANDS = frozenset(
    {"fast", "mode", "model", "reasoning", "sessions", "settings"}
)
_STREAMING_KEY = "streaming_mode"
_STREAMING_MODES = ("off", "edit", "progress")
_MAX_CHOICES = 40
_MAX_CHOICE_VALUE_CHARS = 512
_MODEL_PAGE_SIZE = 25
_SESSION_CONTROLS = frozenset({"fast", "model", "reasoning"})


class SessionControlStaleError(RuntimeError):
    """Raised when a picker targets superseded session preferences."""


@dataclass(frozen=True)
class ModelChoice:
    """One connected provider model safe to expose in Telegram."""

    provider_id: str
    model_id: str
    name: str
    reasoning_variants: tuple[str, ...]

    @property
    def selector(self) -> str:
        return f"{self.provider_id}/{self.model_id}"


@dataclass(frozen=True)
class PickerChoice:
    """One bounded callback choice."""

    label: str
    value: str


@dataclass(frozen=True)
class ControlResolution:
    """Result of consuming a durable control callback."""

    resolved: bool
    label: str
    answer: str


def _build_provider_payload(core: Any) -> Mapping[str, Any]:
    from penguin.web.services.opencode_provider import build_provider_list_payload

    payload = build_provider_list_payload(core)
    return payload if isinstance(payload, Mapping) else {}


def _model_choices(payload: Mapping[str, Any]) -> tuple[ModelChoice, ...]:
    """Extract active models from connected provider entries."""

    connected_raw = payload.get("connected")
    connected = (
        {str(item) for item in connected_raw if isinstance(item, str) and item.strip()}
        if isinstance(connected_raw, (list, tuple, set, frozenset))
        else set()
    )
    choices: list[ModelChoice] = []
    providers = payload.get("all")
    if not isinstance(providers, list):
        return ()
    for provider in providers:
        if not isinstance(provider, Mapping):
            continue
        provider_id = str(provider.get("id") or "").strip()
        if not provider_id or (
            not bool(provider.get("connected")) and provider_id not in connected
        ):
            continue
        models = provider.get("models")
        if not isinstance(models, Mapping):
            continue
        for raw_model_id, raw_model in models.items():
            if not isinstance(raw_model_id, str) or not raw_model_id.strip():
                continue
            model = raw_model if isinstance(raw_model, Mapping) else {}
            if str(model.get("status") or "active").lower() != "active":
                continue
            variants = model.get("variants")
            variant_names = (
                tuple(str(item) for item in variants if str(item).strip())
                if isinstance(variants, Mapping)
                else ()
            )
            choices.append(
                ModelChoice(
                    provider_id=provider_id,
                    model_id=raw_model_id.strip(),
                    name=str(model.get("name") or raw_model_id).strip(),
                    reasoning_variants=variant_names,
                )
            )
    return tuple(choices)


def _resolve_model(selector: str, choices: Sequence[ModelChoice]) -> ModelChoice | None:
    normalized = selector.strip()
    qualified = [choice for choice in choices if choice.selector == normalized]
    if len(qualified) == 1:
        return qualified[0]
    unqualified = [choice for choice in choices if choice.model_id == normalized]
    return unqualified[0] if len(unqualified) == 1 else None


def _global_model(core: Any) -> tuple[str | None, str | None]:
    getter = getattr(core, "get_current_model", None)
    current = getter() if callable(getter) else None
    if isinstance(current, Mapping):
        provider = str(current.get("provider") or "").strip() or None
        model = str(current.get("model") or "").strip() or None
    else:
        config = getattr(core, "model_config", None)
        provider = str(getattr(config, "provider", "") or "").strip() or None
        model = str(getattr(config, "model", "") or "").strip() or None
    provider = provider.lower() if provider else None
    if provider and model and model.lower().startswith(f"{provider}/"):
        model = model[len(provider) + 1 :]
    return provider, model


def _effective_model(
    core: Any, preferences: SessionRuntimePreferences | None
) -> tuple[str | None, str | None]:
    if preferences and preferences.provider_id and preferences.model_id:
        return preferences.provider_id, preferences.model_id
    return _global_model(core)


def binding_streaming_mode(manager: Any, binding: Any) -> str:
    settings = getattr(binding, "settings", {})
    value = settings.get(_STREAMING_KEY) if isinstance(settings, Mapping) else None
    return value if value in _STREAMING_MODES else manager.config.streaming_mode


async def _preferences(manager: Any, session_id: str) -> SessionRuntimePreferences:
    loaded = await asyncio.to_thread(
        load_session_runtime_preferences, manager.core, session_id
    )
    return loaded or SessionRuntimePreferences()


async def _catalog(manager: Any) -> tuple[ModelChoice, ...]:
    payload = await asyncio.to_thread(_build_provider_payload, manager.core)
    return _model_choices(payload)


def _preferences_revision(preferences: SessionRuntimePreferences) -> str:
    values = (
        preferences.provider_id or "",
        preferences.model_id or "",
        preferences.reasoning_variant or "",
        preferences.service_tier or "",
    )
    digest = hashlib.sha256("\x1f".join(values).encode("utf-8")).hexdigest()
    return digest[:16]


async def _session_revision(manager: Any, session_id: str) -> str:
    preferences = await _preferences(manager, session_id)
    return _preferences_revision(preferences)


async def _assert_session_revision(
    manager: Any,
    session_id: str,
    expected_revision: str | None,
) -> None:
    if expected_revision is None:
        return
    if await _session_revision(manager, session_id) != expected_revision:
        raise SessionControlStaleError(
            "Session settings changed. Reopen the control and try again."
        )


async def _assert_callback_binding(
    manager: Any,
    address_key: str | None,
    session_id: str,
    expected_version: int | None,
) -> None:
    if address_key is None:
        return
    current = await asyncio.to_thread(manager.store.get_binding, address_key)
    if (
        current is None
        or current.session_id != session_id
        or current.version != expected_version
    ):
        raise SessionControlStaleError(
            "Settings changed. Reopen the control and try again."
        )


async def _thread_write(operation: Any, /, *args: Any, **kwargs: Any) -> Any:
    """Finish an in-flight SQLite/session write before propagating cancellation."""

    task = asyncio.create_task(asyncio.to_thread(operation, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError as cancellation:
        try:
            await task
        except Exception:
            logger.exception("Telegram control write failed during cancellation")
        raise cancellation


async def _set_model_preferences(
    manager: Any,
    session_id: str,
    choice: ModelChoice | None,
    *,
    expected_revision: str | None = None,
    expected_address_key: str | None = None,
    expected_binding_version: int | None = None,
) -> None:
    """Validate a fresh request runtime, then persist under the session gate."""

    gate = process_lifecycle.get_session_request_gate(manager.core, session_id)
    if gate.locked():
        raise SessionBusyError("The current session is busy. Use /stop or retry later.")
    await gate.acquire()
    try:
        await _assert_callback_binding(
            manager,
            expected_address_key,
            session_id,
            expected_binding_version,
        )
        await _assert_session_revision(manager, session_id, expected_revision)
        if choice is not None:
            resolver = getattr(manager.core, "resolve_request_runtime", None)
            if not callable(resolver):
                raise ValueError("Penguin cannot validate model changes right now.")
            resolved = resolver(choice.selector)
            if inspect.isawaitable(resolved):
                resolved = await resolved
            if not isinstance(resolved, tuple) or len(resolved) != 2:
                raise ValueError(
                    "Penguin could not build a request runtime for that model."
                )
            model_config, api_client = resolved
            if model_config is getattr(
                manager.core, "model_config", None
            ) or api_client is getattr(manager.core, "api_client", None):
                raise ValueError("Penguin returned a shared runtime for that model.")
        updated = await _thread_write(
            update_session_runtime_preferences,
            manager.core,
            session_id,
            provider_id=choice.provider_id if choice is not None else None,
            model_id=choice.model_id if choice is not None else None,
            reasoning_variant=None,
            service_tier=None,
        )
        if updated is None:
            raise ValueError("The Penguin session is no longer available.")
    finally:
        gate.release()


async def _set_model(
    manager: Any,
    binding: Any,
    value: str,
    *,
    expected_revision: str | None = None,
    expected_address_key: str | None = None,
    expected_binding_version: int | None = None,
) -> str:
    if value.strip().lower() in {"inherit", "reset"}:
        await _set_model_preferences(
            manager,
            binding.session_id,
            None,
            expected_revision=expected_revision,
            expected_address_key=expected_address_key,
            expected_binding_version=expected_binding_version,
        )
        return "Session model reset to the Penguin default."
    choice = _resolve_model(value, await _catalog(manager))
    if choice is None:
        raise ValueError(
            "Unknown or ambiguous model. Use /model to choose a connected "
            "provider model, or provide an exact provider/model ID."
        )
    await _set_model_preferences(
        manager,
        binding.session_id,
        choice,
        expected_revision=expected_revision,
        expected_address_key=expected_address_key,
        expected_binding_version=expected_binding_version,
    )
    return f"Session model set to {choice.selector}. Reasoning and fast mode reset."


async def _set_reasoning(
    manager: Any,
    binding: Any,
    value: str,
    *,
    expected_revision: str | None = None,
    expected_address_key: str | None = None,
    expected_binding_version: int | None = None,
) -> str:
    normalized = value.strip().lower()
    gate = process_lifecycle.get_session_request_gate(manager.core, binding.session_id)
    if gate.locked():
        raise SessionBusyError("The current session is busy. Use /stop or retry later.")
    await gate.acquire()
    try:
        await _assert_callback_binding(
            manager,
            expected_address_key,
            binding.session_id,
            expected_binding_version,
        )
        await _assert_session_revision(manager, binding.session_id, expected_revision)
        if normalized in {"inherit", "reset"}:
            reasoning_variant = None
        else:
            preferences = await _preferences(manager, binding.session_id)
            provider_id, model_id = _effective_model(manager.core, preferences)
            model = _resolve_model(
                f"{provider_id}/{model_id}" if provider_id and model_id else "",
                await _catalog(manager),
            )
            if model is None or normalized not in model.reasoning_variants:
                supported = ", ".join(model.reasoning_variants) if model else "none"
                raise ValueError(
                    f"Unsupported reasoning effort. Available: {supported}."
                )
            reasoning_variant = normalized
        updated = await _thread_write(
            update_session_runtime_preferences,
            manager.core,
            binding.session_id,
            reasoning_variant=reasoning_variant,
        )
        if updated is None:
            raise ValueError("The Penguin session is no longer available.")
    finally:
        gate.release()
    if reasoning_variant is None:
        return "Session reasoning reset to the model default."
    return f"Session reasoning set to {normalized}."


async def _set_fast(
    manager: Any,
    binding: Any,
    value: str,
    *,
    expected_revision: str | None = None,
    expected_address_key: str | None = None,
    expected_binding_version: int | None = None,
) -> str:
    normalized = value.strip().lower()
    values = {"on": True, "off": False, "inherit": None, "reset": None}
    if normalized not in values:
        raise ValueError("Usage: /fast on|off|reset")
    gate = process_lifecycle.get_session_request_gate(manager.core, binding.session_id)
    if gate.locked():
        raise SessionBusyError("The current session is busy. Use /stop or retry later.")
    await gate.acquire()
    try:
        await _assert_callback_binding(
            manager,
            expected_address_key,
            binding.session_id,
            expected_binding_version,
        )
        await _assert_session_revision(manager, binding.session_id, expected_revision)
        preferences = await _preferences(manager, binding.session_id)
        provider_id, _model_id = _effective_model(manager.core, preferences)
        if values[normalized] is not None and provider_id != "openai":
            raise ValueError("Fast mode is available only for OpenAI models.")
        tier = service_tier_for_fast_mode(values[normalized])
        updated = await _thread_write(
            update_session_runtime_preferences,
            manager.core,
            binding.session_id,
            service_tier=tier,
        )
        if updated is None:
            raise ValueError("The Penguin session is no longer available.")
    finally:
        gate.release()
    state = "inherited" if values[normalized] is None else normalized
    return f"Session fast mode set to {state}."


async def _set_mode(
    manager: Any,
    envelope: InboundEnvelope,
    binding: Any,
    value: str,
) -> str:
    normalized = value.strip().lower()
    if normalized not in {"plan", "build"}:
        raise ValueError("Usage: /mode plan|build")
    gate = process_lifecycle.get_session_request_gate(manager.core, binding.session_id)
    if gate.locked():
        raise SessionBusyError("The current session is busy. Use /stop or retry later.")
    await gate.acquire()
    try:
        updated = await _thread_write(
            manager.store.upsert_binding,
            envelope.address.lane_key,
            binding.session_id,
            directory=getattr(binding, "directory", None),
            agent_id=getattr(binding, "agent_id", None),
            agent_mode=normalized,
            settings=getattr(binding, "settings", {}),
            expected_version=binding.version,
        )
    finally:
        gate.release()
    return f"Mode set to {updated.agent_mode}."


async def _set_streaming(
    manager: Any, envelope: InboundEnvelope, binding: Any, value: str
) -> str:
    normalized = value.strip().lower()
    if normalized not in _STREAMING_MODES:
        raise ValueError("Streaming must be off, edit, or progress.")
    gate = process_lifecycle.get_session_request_gate(manager.core, binding.session_id)
    if gate.locked():
        raise SessionBusyError("The current session is busy. Use /stop or retry later.")
    settings = dict(getattr(binding, "settings", {}) or {})
    settings[_STREAMING_KEY] = normalized
    await gate.acquire()
    try:
        await _thread_write(
            manager.store.upsert_binding,
            envelope.address.lane_key,
            binding.session_id,
            directory=getattr(binding, "directory", None),
            agent_id=getattr(binding, "agent_id", None),
            agent_mode=getattr(binding, "agent_mode", None),
            settings=settings,
            expected_version=binding.version,
        )
    finally:
        gate.release()
    return f"Telegram streaming set to {normalized}."


async def _rebind(manager: Any, binding: Any, session_id: str) -> str:
    updated = await rebind_session(
        manager.core, manager.store, binding, session_id.strip()
    )
    return f"Telegram is now bound to Penguin session {updated.session_id}."


def _choice(label: str, value: str) -> PickerChoice:
    return PickerChoice(label=label[:40], value=value[:_MAX_CHOICE_VALUE_CHARS])


async def _settings_text(manager: Any, binding: Any) -> str:
    preferences = await _preferences(manager, binding.session_id)
    provider_id, model_id = _effective_model(manager.core, preferences)
    model = f"{provider_id}/{model_id}" if provider_id and model_id else "unavailable"
    fast = {
        "priority": "on",
        "default": "off",
    }.get(preferences.service_tier, "inherit")
    return (
        "Penguin Telegram settings\n"
        f"Session: {binding.session_id}\n"
        f"Model: {model}"
        f"{' (session)' if preferences.qualified_model_id else ' (default)'}\n"
        f"Reasoning: {preferences.reasoning_variant or 'inherit'}\n"
        f"Fast mode: {fast}\n"
        f"Mode: {getattr(binding, 'agent_mode', None) or 'build'}\n"
        f"Streaming: {binding_streaming_mode(manager, binding)}\n"
        f"Permissions: {manager.config.permission_mode} cap; use /permissions"
    )


async def _picker(
    manager: Any,
    envelope: InboundEnvelope,
    binding: Any,
    control: str,
    *,
    page: int = 0,
) -> tuple[str, tuple[PickerChoice, ...]]:
    if control == "settings":
        return await _settings_text(manager, binding), tuple(
            _choice(label, f"open:{value}")
            for label, value in (
                ("Model", "model"),
                ("Reasoning", "reasoning"),
                ("Fast mode", "fast"),
                ("Plan / build", "mode"),
                ("Sessions", "sessions"),
                ("Streaming", "streaming"),
                ("Permissions", "permissions"),
            )
        )
    if control == "model":
        models = await _catalog(manager)
        page_count = max(1, (len(models) + _MODEL_PAGE_SIZE - 1) // _MODEL_PAGE_SIZE)
        if page < 0 or page >= page_count:
            raise ValueError("Model catalog changed. Reopen /model.")
        start = page * _MODEL_PAGE_SIZE
        choices = [_choice("Use Penguin default", "reset")]
        choices.extend(
            _choice(f"{model.name} · {model.provider_id}", model.selector)
            for model in models[start : start + _MODEL_PAGE_SIZE]
        )
        if page:
            choices.append(_choice("Previous", f"page:{page - 1}"))
        if page + 1 < page_count:
            choices.append(_choice("Next", f"page:{page + 1}"))
        return (
            f"Choose a session model (page {page + 1}/{page_count}):",
            tuple(choices),
        )
    if control == "reasoning":
        preferences = await _preferences(manager, binding.session_id)
        provider_id, model_id = _effective_model(manager.core, preferences)
        models = await _catalog(manager)
        model = _resolve_model(
            f"{provider_id}/{model_id}" if provider_id and model_id else "", models
        )
        variants = model.reasoning_variants if model else ()
        choices = [_choice("Use model default", "reset")]
        choices.extend(_choice(value, value) for value in variants)
        return "Choose session reasoning effort:", tuple(choices)
    if control == "fast":
        return "Choose OpenAI fast mode:", (
            _choice("On (priority)", "on"),
            _choice("Off (default tier)", "off"),
            _choice("Inherit", "reset"),
        )
    if control == "mode":
        return "Choose plan or build mode:", (
            _choice("Plan", "plan"),
            _choice("Build", "build"),
        )
    if control == "streaming":
        return "Choose Telegram streaming:", tuple(
            _choice(value.title(), value) for value in _STREAMING_MODES
        )
    if control == "sessions":
        sessions = await asyncio.to_thread(list_recent_sessions, manager.core, binding)
        choices = tuple(
            _choice(
                ("✓ " if session.current else "")
                + (session.title or session.session_id),
                session.session_id,
            )
            for session in sessions[:_MAX_CHOICES]
        )
        return "Choose a recent Telegram-owned session:", choices
    if control == "permissions":
        return manager.config.permissions_summary, (
            _choice("Back to settings", "open:settings"),
        )
    raise ValueError("Unknown Telegram control")


async def _open_picker(
    manager: Any,
    envelope: InboundEnvelope,
    binding: Any,
    control: str,
    *,
    page: int = 0,
    expected_revision: str | None = None,
) -> None:
    session_revision: str | None = None
    if control in _SESSION_CONTROLS:
        gate = process_lifecycle.get_session_request_gate(
            manager.core, binding.session_id
        )
        if gate.locked():
            raise SessionBusyError(
                "The current session is busy. Use /stop or retry later."
            )
        await gate.acquire()
        try:
            await _assert_session_revision(
                manager, binding.session_id, expected_revision
            )
            text, choices = await _picker(
                manager, envelope, binding, control, page=page
            )
            session_revision = await _session_revision(manager, binding.session_id)
        finally:
            gate.release()
    else:
        text, choices = await _picker(manager, envelope, binding, control, page=page)
    if not choices:
        text += "\n\nNo choices are currently available."
    choices = choices[:_MAX_CHOICES]
    callback_id = uuid.uuid4().hex
    buttons = [
        [
            {
                "text": choice.label,
                "data": f"penguin:{callback_id}:c{index}",
            }
        ]
        for index, choice in enumerate(choices)
    ]
    payload: dict[str, Any] = {
        "kind": "control",
        "control": control,
        "session_id": binding.session_id,
        "binding_version": binding.version,
        "choices": [choice.value for choice in choices],
    }
    if session_revision is not None:
        payload["session_revision"] = session_revision
    await manager._create_projection(
        envelope.address,
        f"control:{callback_id}",
        text,
        buttons,
        session_id=binding.session_id,
        user_id=envelope.sender_id,
        callback_id=callback_id,
        request_id=f"control:{callback_id}",
        callback_payload=payload,
    )


async def _safe_control(operation: Any) -> str | None:
    try:
        return await operation
    except SessionBusyError as exc:
        return str(exc) or "The session is busy. Use /stop or retry later."
    except SessionAccessError:
        return "That session is not available to this Telegram binding."
    except CompareAndSwapError:
        return "Settings changed concurrently. Reopen the control and try again."
    except SessionControlStaleError as exc:
        return str(exc)
    except ValueError as exc:
        return str(exc) or "That setting is not available."
    except RuntimeError:
        return "Penguin could not persist that setting. Try again."


async def _seed_recent_binding(
    manager: Any, envelope: InboundEnvelope, binding: Any
) -> Any:
    settings = dict(getattr(binding, "settings", {}) or {})
    seeded = with_recent_session(settings, binding.session_id)
    if seeded == settings:
        return binding
    try:
        return await asyncio.to_thread(
            manager.store.upsert_binding,
            envelope.address.lane_key,
            binding.session_id,
            directory=getattr(binding, "directory", None),
            agent_id=getattr(binding, "agent_id", None),
            agent_mode=getattr(binding, "agent_mode", None),
            settings=seeded,
            expected_version=binding.version,
        )
    except CompareAndSwapError:
        current = await asyncio.to_thread(
            manager.store.get_binding, envelope.address.lane_key
        )
        current_settings = getattr(current, "settings", {}) if current else {}
        if (
            current
            and with_recent_session(current_settings, current.session_id)
            == current_settings
        ):
            return current
        raise


async def handle_control_command(
    manager: Any,
    command: str,
    arguments: str,
    envelope: InboundEnvelope,
    binding: Any,
) -> str | None:
    """Handle one curated control command without global runtime mutation."""

    if command in {"sessions", "settings"}:
        try:
            binding = await _seed_recent_binding(manager, envelope, binding)
        except CompareAndSwapError:
            return "Settings changed concurrently. Try again."
    value = arguments.strip()
    if command == "settings" and value:
        section, _, setting = value.partition(" ")
        if section == "streaming" and setting:
            return await _safe_control(
                _set_streaming(manager, envelope, binding, setting)
            )
        if section == "mode" and setting:
            return await _safe_control(_set_mode(manager, envelope, binding, setting))
        return "Usage: /settings or /settings streaming off|edit|progress"
    if value:
        if command == "model":
            return await _safe_control(
                _set_model(
                    manager,
                    binding,
                    value,
                    expected_address_key=envelope.address.lane_key,
                    expected_binding_version=binding.version,
                )
            )
        if command == "reasoning":
            return await _safe_control(
                _set_reasoning(
                    manager,
                    binding,
                    value,
                    expected_address_key=envelope.address.lane_key,
                    expected_binding_version=binding.version,
                )
            )
        if command == "fast":
            return await _safe_control(
                _set_fast(
                    manager,
                    binding,
                    value,
                    expected_address_key=envelope.address.lane_key,
                    expected_binding_version=binding.version,
                )
            )
        if command == "mode":
            return await _safe_control(_set_mode(manager, envelope, binding, value))
        if command == "sessions":
            return await _safe_control(_rebind(manager, binding, value))
    return await _safe_control(_open_picker(manager, envelope, binding, command))


async def _apply_choice(
    manager: Any,
    envelope: InboundEnvelope,
    binding: Any,
    control: str,
    value: str,
    *,
    expected_revision: str | None = None,
    expected_address_key: str | None = None,
    expected_binding_version: int | None = None,
) -> str:
    if value.startswith("open:"):
        target = value.removeprefix("open:")
        await _open_picker(manager, envelope, binding, target)
        return f"Opened {target}"
    if control == "model" and value.startswith("page:"):
        try:
            page = int(value.removeprefix("page:"))
        except ValueError as exc:
            raise ValueError("Invalid model page.") from exc
        await _open_picker(
            manager,
            envelope,
            binding,
            control,
            page=page,
            expected_revision=expected_revision,
        )
        return f"Opened model page {page + 1}"
    if control == "model":
        return await _set_model(
            manager,
            binding,
            value,
            expected_revision=expected_revision,
            expected_address_key=expected_address_key,
            expected_binding_version=expected_binding_version,
        )
    if control == "reasoning":
        return await _set_reasoning(
            manager,
            binding,
            value,
            expected_revision=expected_revision,
            expected_address_key=expected_address_key,
            expected_binding_version=expected_binding_version,
        )
    if control == "fast":
        return await _set_fast(
            manager,
            binding,
            value,
            expected_revision=expected_revision,
            expected_address_key=expected_address_key,
            expected_binding_version=expected_binding_version,
        )
    if control == "mode":
        return await _set_mode(manager, envelope, binding, value)
    if control == "streaming":
        return await _set_streaming(manager, envelope, binding, value)
    if control == "sessions":
        return await _rebind(manager, binding, value)
    raise ValueError("That control is no longer available.")


async def resolve_control_callback(
    manager: Any,
    envelope: InboundEnvelope,
    payload: Mapping[str, Any],
    action: str,
) -> ControlResolution:
    """Validate and consume one claimed control callback."""

    current = await asyncio.to_thread(
        manager.store.get_binding, envelope.address.lane_key
    )
    expected_session = str(payload.get("session_id") or "")
    expected_version = payload.get("binding_version")
    if (
        current is None
        or current.session_id != expected_session
        or current.version != expected_version
    ):
        return ControlResolution(
            False,
            "Stale",
            "Settings changed. Reopen the control and try again.",
        )
    if not action.startswith("c"):
        return ControlResolution(False, "Unavailable", "Invalid control choice.")
    try:
        index = int(action[1:])
    except ValueError:
        index = -1
    choices = payload.get("choices")
    if not isinstance(choices, list) or not (0 <= index < len(choices)):
        return ControlResolution(False, "Unavailable", "Invalid control choice.")
    value = choices[index]
    control = payload.get("control")
    if not isinstance(value, str) or not isinstance(control, str):
        return ControlResolution(False, "Unavailable", "Invalid control choice.")
    expected_revision = payload.get("session_revision")
    if control in _SESSION_CONTROLS and not isinstance(expected_revision, str):
        return ControlResolution(
            False,
            "Stale",
            "Session settings changed. Reopen the control and try again.",
        )
    try:
        message = await _apply_choice(
            manager,
            envelope,
            current,
            control,
            value,
            expected_revision=expected_revision,
            expected_address_key=envelope.address.lane_key,
            expected_binding_version=current.version,
        )
    except SessionBusyError as exc:
        return ControlResolution(False, "Busy", str(exc) or "Session is busy.")
    except SessionAccessError:
        return ControlResolution(False, "Unavailable", "Session is unavailable.")
    except CompareAndSwapError:
        return ControlResolution(
            False, "Stale", "Settings changed. Reopen the control and try again."
        )
    except SessionControlStaleError as exc:
        return ControlResolution(False, "Stale", str(exc))
    except ValueError as exc:
        return ControlResolution(False, "Unavailable", str(exc))
    except RuntimeError:
        return ControlResolution(
            False,
            "Unavailable",
            "Penguin could not persist that setting. Try again.",
        )
    return ControlResolution(True, message[:80], "Updated.")
