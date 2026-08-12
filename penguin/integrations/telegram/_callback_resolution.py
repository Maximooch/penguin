"""Lease-safe resolution of Telegram inline callbacks."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from penguin.integrations.telegram._controls import resolve_control_callback
from penguin.integrations.telegram._leases import run_with_lease_heartbeat

if TYPE_CHECKING:
    from penguin.channels.schema import InboundEnvelope
    from penguin.channels.store_models import CallbackRecord

__all__ = ["resolve_callback"]

_PLATFORM = "telegram"
_CALLBACK_LEASE_SECONDS = 30.0


async def _resolve_claimed_callback(
    manager: Any,
    envelope: InboundEnvelope,
    callback: CallbackRecord,
    action: str,
) -> tuple[bool, str, str | None]:
    """Apply one claimed callback while its durable lease is live."""

    kind = callback.payload.get("kind")
    resolved = False
    label = "Expired"
    callback_answer: str | None = None
    if kind == "approval":
        from penguin.security.approval import ApprovalScope, get_approval_manager

        approval_manager = get_approval_manager()
        if action == "approve":
            resolved = (
                approval_manager.approve(callback.request_id, scope=ApprovalScope.ONCE)
                is not None
            )
            if resolved:
                label = "Approved"
        elif action == "approve_session":
            resolved = (
                approval_manager.approve(
                    callback.request_id, scope=ApprovalScope.SESSION
                )
                is not None
            )
            if resolved:
                label = "Approved for session"
        elif action == "deny":
            resolved = approval_manager.deny(callback.request_id) is not None
            if resolved:
                label = "Denied"
    elif kind == "question" and action.startswith("q"):
        try:
            index = int(action[1:])
        except ValueError:
            index = -1
        questions = callback.payload.get("questions") or []
        options = questions[0].get("options") if questions else []
        if 0 <= index < len(options):
            option = options[index]
            answer = str(option.get("label") or option.get("description") or "")
            resolved = await manager._reply_to_question(callback.request_id, answer)
            if resolved:
                label = "Answered"
                manager._pending_questions.pop(
                    (envelope.address.lane_key, envelope.sender_id), None
                )
    elif kind == "control":
        resolution = await resolve_control_callback(
            manager, envelope, callback.payload, action
        )
        resolved = resolution.resolved
        label = resolution.label
        callback_answer = resolution.answer
    return resolved, label, callback_answer


async def resolve_callback(
    manager: Any,
    envelope: InboundEnvelope,
    callback_data: str,
    worker_id: str,
) -> None:
    """Claim, renew, and terminalize one addressed Telegram callback."""

    parts = callback_data.split(":", 2)
    if len(parts) != 3:
        return
    _prefix, callback_id, action = parts
    callback = await asyncio.to_thread(
        manager.store.claim_callback,
        callback_id,
        account_id=manager.account_id,
        chat_id=envelope.address.chat_id,
        topic_id=envelope.address.topic_id or None,
        user_id=envelope.sender_id,
        owner_id=worker_id,
        lease_seconds=_CALLBACK_LEASE_SECONDS,
        platform=_PLATFORM,
    )
    if callback is None:
        await manager._answer_callback(envelope, "This action is unavailable.")
        return
    resolved, label, callback_answer = await run_with_lease_heartbeat(
        _resolve_claimed_callback(manager, envelope, callback, action),
        manager.store.renew_callback_lease,
        callback_id,
        platform=_PLATFORM,
        account_id=manager.account_id,
        owner_id=worker_id,
        lease_seconds=_CALLBACK_LEASE_SECONDS,
    )
    await asyncio.to_thread(
        manager.store.complete_callback_with_terminal,
        callback_id,
        owner_id=worker_id,
        label=label,
        platform=_PLATFORM,
    )
    manager._work_available.set()
    await manager._answer_callback(
        envelope,
        callback_answer
        or ("Recorded." if resolved else "This request is no longer pending."),
    )
