"""Narrow authorization helpers for Telegram group migrations."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from penguin.channels.schema import InboundEnvelope
    from penguin.channels.store import ChannelStore
    from penguin.integrations.telegram.config import TelegramConfig


def migration_chat_ids(envelope: InboundEnvelope) -> tuple[str, str] | None:
    """Return the trusted old/new IDs carried by a migration service update."""

    migrate_to = str(envelope.metadata.get("migrate_to_chat_id") or "")
    if migrate_to:
        return envelope.address.chat_id, migrate_to
    migrate_from = str(envelope.metadata.get("migrate_from_chat_id") or "")
    if migrate_from:
        return migrate_from, envelope.address.chat_id
    return None


async def group_event_is_authorized(
    envelope: InboundEnvelope,
    *,
    config: TelegramConfig,
    store: ChannelStore,
    account_id: str,
) -> bool:
    """Authorize normal group traffic or a narrowly scoped migration event."""

    migration = migration_chat_ids(envelope)
    candidate_chat_id = (
        migration[0] if migration is not None else envelope.address.chat_id
    )
    destination_chat_id = (
        migration[1] if migration is not None else envelope.address.chat_id
    )
    try:
        numeric_chat_id = int(candidate_chat_id)
    except ValueError:
        return False
    topic_id = envelope.address.topic_id or None
    try:
        destination_enabled = config.binding_for(destination_chat_id, topic_id).enabled
        candidate_enabled = config.binding_for(candidate_chat_id, topic_id).enabled
    except ValueError:
        return False
    if not destination_enabled or not candidate_enabled:
        return False

    allowed = config.allows_group(numeric_chat_id)
    if not allowed and config.group_policy == "allowlist":
        allowed_sources = frozenset(
            str(chat_id)
            for chat_id in config.allowed_group_ids
            if config.binding_for(chat_id, topic_id).enabled
        )
        allowed = await asyncio.to_thread(
            store.is_group_authorized,
            platform="telegram",
            account_id=account_id,
            chat_id=candidate_chat_id,
            allowed_source_chat_ids=allowed_sources,
        )
    if migration is not None:
        return allowed
    try:
        numeric_sender_id = int(envelope.sender_id)
    except ValueError:
        return False
    return allowed and config.allows_group_sender(numeric_sender_id)


__all__ = ["group_event_is_authorized", "migration_chat_ids"]
