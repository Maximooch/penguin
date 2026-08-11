"""Lease renewal for long-running Telegram ingress and delivery work."""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, TypeVar

from penguin.channels.store_models import LeaseLostError

_T = TypeVar("_T")


async def lease_heartbeat(
    renew: Callable[..., bool],
    record_id: str,
    *,
    platform: str,
    account_id: str,
    owner_id: str,
    lease_seconds: float,
) -> None:
    """Renew one owned record until it completes or ownership is lost."""

    while True:
        await asyncio.sleep(lease_seconds / 3)
        renewed = await asyncio.to_thread(
            renew,
            record_id,
            platform=platform,
            account_id=account_id,
            owner_id=owner_id,
            lease_seconds=lease_seconds,
        )
        if not renewed:
            return


async def run_with_lease_heartbeat(
    operation: Awaitable[_T],
    renew: Callable[..., bool],
    record_id: str,
    *,
    platform: str,
    account_id: str,
    owner_id: str,
    lease_seconds: float,
) -> _T:
    """Cancel an in-flight operation if its durable ownership is lost."""

    operation_task = asyncio.ensure_future(operation)
    heartbeat = asyncio.create_task(
        lease_heartbeat(
            renew,
            record_id,
            platform=platform,
            account_id=account_id,
            owner_id=owner_id,
            lease_seconds=lease_seconds,
        )
    )
    try:
        done, _pending = await asyncio.wait(
            {operation_task, heartbeat}, return_when=asyncio.FIRST_COMPLETED
        )
        if heartbeat in done:
            error = heartbeat.exception()
            operation_task.cancel()
            await asyncio.gather(operation_task, return_exceptions=True)
            if error is not None:
                raise LeaseLostError(
                    f"lease renewal for {record_id!r} became uncertain"
                ) from error
            raise LeaseLostError(f"lease for {record_id!r} was lost")
        return await operation_task
    finally:
        heartbeat.cancel()
        operation_task.cancel()
        await asyncio.gather(heartbeat, operation_task, return_exceptions=True)


__all__ = ["lease_heartbeat", "run_with_lease_heartbeat"]
