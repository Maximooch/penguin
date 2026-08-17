"""Value records and explicit errors returned by the channel state store."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


class ChannelStoreError(RuntimeError):
    """Base error for durable channel state operations."""


class CompareAndSwapError(ChannelStoreError):
    """Raised when a caller tries to replace stale state."""


class LeaseLostError(ChannelStoreError):
    """Raised when a worker no longer owns a claimed record."""


class IdempotencyConflictError(ChannelStoreError):
    """Raised when one idempotency key is reused for different work."""


class PollerLeaseConflictError(ChannelStoreError):
    """Raised when another process currently owns a polling lease."""


class PayloadTooLargeError(ChannelStoreError, ValueError):
    """Raised when a persisted JSON payload exceeds its configured bound."""


@dataclass(frozen=True)
class BindingRecord:
    """A channel address bound to one Penguin session."""

    address_key: str
    session_id: str
    directory: str | None
    agent_id: str | None
    agent_mode: str | None
    settings: dict[str, Any]
    version: int
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class PairingRecord:
    """A pairing attempt without the plaintext pairing code."""

    code_hash: str
    account_id: str
    expected_user_id: str | None
    state: str
    expires_at: float
    consumed_by_user_id: str | None
    consumed_chat_id: str | None
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class CallbackRecord:
    """A single-use interactive callback scoped to its intended recipient."""

    callback_id: str
    account_id: str
    chat_id: str
    topic_id: str | None
    user_id: str
    request_id: str
    tool_call_id: str | None
    payload: dict[str, Any]
    state: str
    claim_owner: str | None
    lease_expires_at: float | None
    expires_at: float
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class IngressRecord:
    """A durable inbound event and its processing state."""

    sequence: int
    platform: str
    account_id: str
    event_id: str
    lane_key: str
    payload: dict[str, Any]
    state: str
    attempt_count: int
    next_attempt_at: float
    claim_owner: str | None
    lease_expires_at: float | None
    started_at: float | None
    last_error_class: str | None
    last_error_message: str | None
    created_at: float
    updated_at: float
    completed_at: float | None


@dataclass(frozen=True)
class DeliveryRecord:
    """A durable outbound delivery and its retry state."""

    sequence: int
    platform: str
    account_id: str
    delivery_id: str
    idempotency_key: str
    lane_key: str
    kind: str
    payload: dict[str, Any]
    source_event_id: str | None
    source_session_id: str | None
    source_request_id: str | None
    state: str
    attempt_count: int
    next_attempt_at: float
    claim_owner: str | None
    lease_expires_at: float | None
    external_message_id: str | None
    last_error_class: str | None
    last_error_message: str | None
    created_at: float
    updated_at: float
    completed_at: float | None


@dataclass(frozen=True)
class PollerLease:
    """Exclusive ownership and durable update offset for one bot identity."""

    platform: str
    account_id: str
    token_fingerprint: str
    owner_id: str
    lease_expires_at: float
    update_offset: int | None


@dataclass(frozen=True)
class RecoveryCounts:
    """Counts of safely retried and terminal uncertain records."""

    retried: int
    dead: int


def binding_record_from_row(row: Any) -> BindingRecord:
    return BindingRecord(
        address_key=row["address_key"],
        session_id=row["session_id"],
        directory=row["directory"],
        agent_id=row["agent_id"],
        agent_mode=row["agent_mode"],
        settings=json.loads(row["settings_json"]),
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def pairing_record_from_row(row: Any) -> PairingRecord:
    return PairingRecord(
        code_hash=row["code_hash"],
        account_id=row["account_id"],
        expected_user_id=row["expected_user_id"],
        state=row["state"],
        expires_at=row["expires_at"],
        consumed_by_user_id=row["consumed_by_user_id"],
        consumed_chat_id=row["consumed_chat_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def callback_record_from_row(row: Any) -> CallbackRecord:
    return CallbackRecord(
        callback_id=row["callback_id"],
        account_id=row["account_id"],
        chat_id=row["chat_id"],
        topic_id=row["topic_id"] or None,
        user_id=row["user_id"],
        request_id=row["request_id"],
        tool_call_id=row["tool_call_id"],
        payload=json.loads(row["payload_json"]),
        state=row["state"],
        claim_owner=row["claim_owner"],
        lease_expires_at=row["lease_expires_at"],
        expires_at=row["expires_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def ingress_record_from_row(row: Any) -> IngressRecord:
    return IngressRecord(
        sequence=row["sequence"],
        platform=row["platform"],
        account_id=row["account_id"],
        event_id=row["event_id"],
        lane_key=row["lane_key"],
        payload=json.loads(row["payload_json"]),
        state=row["state"],
        attempt_count=row["attempt_count"],
        next_attempt_at=row["next_attempt_at"],
        claim_owner=row["claim_owner"],
        lease_expires_at=row["lease_expires_at"],
        started_at=row["started_at"],
        last_error_class=row["last_error_class"],
        last_error_message=row["last_error_message"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
    )


def delivery_record_from_row(row: Any) -> DeliveryRecord:
    return DeliveryRecord(
        sequence=row["sequence"],
        platform=row["platform"],
        account_id=row["account_id"],
        delivery_id=row["delivery_id"],
        idempotency_key=row["idempotency_key"],
        lane_key=row["lane_key"],
        kind=row["kind"],
        payload=json.loads(row["payload_json"]),
        source_event_id=row["source_event_id"],
        source_session_id=row["source_session_id"],
        source_request_id=row["source_request_id"],
        state=row["state"],
        attempt_count=row["attempt_count"],
        next_attempt_at=row["next_attempt_at"],
        claim_owner=row["claim_owner"],
        lease_expires_at=row["lease_expires_at"],
        external_message_id=row["external_message_id"],
        last_error_class=row["last_error_class"],
        last_error_message=row["last_error_message"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
    )


def poller_record_from_row(row: Any) -> PollerLease:
    assert row["lease_owner"] is not None
    assert row["lease_expires_at"] is not None
    return PollerLease(
        platform=row["platform"],
        account_id=row["account_id"],
        token_fingerprint=row["token_fingerprint"],
        owner_id=row["lease_owner"],
        lease_expires_at=row["lease_expires_at"],
        update_offset=row["update_offset"],
    )


__all__ = [
    "BindingRecord",
    "CallbackRecord",
    "ChannelStoreError",
    "CompareAndSwapError",
    "DeliveryRecord",
    "IdempotencyConflictError",
    "IngressRecord",
    "LeaseLostError",
    "PairingRecord",
    "PayloadTooLargeError",
    "PollerLease",
    "PollerLeaseConflictError",
    "RecoveryCounts",
]
