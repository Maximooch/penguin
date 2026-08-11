"""Durable Telegram group migration address helpers."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from penguin.channels.schema import ChannelAddress

if TYPE_CHECKING:
    from penguin.channels.store import ChannelStore


def migration_authorization(
    account_id: str, migration: tuple[str, str] | None
) -> tuple[str, str, str, str] | None:
    """Return the durable Telegram migration edge accepted by the store."""

    return ("telegram", account_id, *migration) if migration is not None else None


async def stable_lane(
    store: ChannelStore,
    address: ChannelAddress,
    *,
    chat_id: str | None = None,
) -> str:
    """Return one scheduling lane shared by every ID in a migration chain."""

    source = await asyncio.to_thread(
        store.resolve_group_source,
        platform=address.platform,
        account_id=address.account_id,
        chat_id=chat_id or address.chat_id,
    )
    return ChannelAddress(
        address.platform,
        address.account_id,
        source,
        address.topic_id,
    ).lane_key


async def latest_chat_id(
    store: ChannelStore,
    *,
    platform: str,
    account_id: str,
    chat_id: str,
) -> str:
    """Return the latest durable destination for a possibly obsolete chat ID."""

    return await asyncio.to_thread(
        store.resolve_group_destination,
        platform=platform,
        account_id=account_id,
        chat_id=chat_id,
    )


__all__ = ["latest_chat_id", "migration_authorization", "stable_lane"]
