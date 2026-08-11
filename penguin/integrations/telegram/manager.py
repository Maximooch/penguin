"""In-process Telegram gateway sharing one PenguinCore with penguin-web."""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
import tempfile
import time
import uuid
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping

from PIL import Image, UnidentifiedImageError

from penguin.channels.chat import ChatProcessRequest, execute_chat_turn
from penguin.channels.store import (
    ChannelStore,
    CompareAndSwapError,
    DeliveryRecord,
    IngressRecord,
    LeaseLostError,
    PollerLeaseConflictError,
)
from penguin.config import WORKSPACE_PATH
from penguin.integrations.telegram import _migration
from penguin.integrations.telegram._artifacts import (
    artifact_paths,
    validated_artifact_path,
)
from penguin.integrations.telegram._authorization import (
    group_event_is_authorized,
    migration_chat_ids,
)
from penguin.integrations.telegram._commands import handle_command
from penguin.integrations.telegram._helpers import (
    delivery_payload as _delivery_payload,
    inline_markup as _inline_markup,
    interactive_terminal_label,
    message_id as _message_id,
    value as _value,
)
from penguin.integrations.telegram._history import GroupHistory
from penguin.integrations.telegram._leases import run_with_lease_heartbeat
from penguin.integrations.telegram._preview import Preview
from penguin.integrations.telegram.formatting import formatted_chunks
from penguin.integrations.telegram.transport import classify_failure, retry_delay
from penguin.integrations.telegram.updates import (
    envelope_from_dict,
    envelope_to_dict,
    is_addressed_to_bot,
    normalize_update,
    parse_command,
    strip_bot_mention,
    update_to_dict,
)
from penguin.system.execution_context import ExecutionContext, normalize_directory

if TYPE_CHECKING:
    from penguin.channels.schema import ChannelAddress, InboundEnvelope
    from penguin.integrations.telegram.config import TelegramConfig

__all__ = ["TelegramManager"]

logger = logging.getLogger(__name__)

_PLATFORM = "telegram"
_LEASE_SECONDS = 120.0
_POLL_LEASE_SECONDS = 90.0
_RECOVERY_INTERVAL_SECONDS = 30.0
_INTERACTIVE_PREFIX = "penguin:"
_INTERACTIVE_LANE_SUFFIX = "\x1finteractive"
_TOKEN_PATTERN = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")
_TEXT_DOCUMENT_MIMES = frozenset(
    {
        "application/json",
        "application/xml",
        "application/x-yaml",
        "text/csv",
        "text/markdown",
        "text/plain",
        "text/yaml",
    }
)


class TelegramManager:
    """Own polling/webhook admission, Penguin routing, and durable delivery."""

    def __init__(
        self,
        core: Any,
        config: TelegramConfig,
        *,
        store: ChannelStore | None = None,
        bot: Any = None,
        store_path: Path | None = None,
        bot_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self.core = core
        self.config = config
        self.store = store
        self._store_path = store_path or (
            Path(WORKSPACE_PATH) / "channels" / "channel_state.db"
        )
        self.bot = bot
        self._bot_factory = bot_factory
        self.account_id = ""
        self.bot_username = config.expected_username
        self.owner_id = f"telegram-{uuid.uuid4().hex}"
        self._fingerprint = ""
        self._tasks: list[asyncio.Task[Any]] = []
        self._projection_tasks: set[asyncio.Task[Any]] = set()
        self._stop = asyncio.Event()
        self._work_available = asyncio.Event()
        self._running = False
        self._status_error: str | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._admission_lock = asyncio.Lock()
        self._session_create_lock = asyncio.Lock()
        self._request_targets: dict[str, tuple[ChannelAddress, str]] = {}
        self._session_targets: dict[str, tuple[ChannelAddress, str]] = {}
        self._pending_questions: dict[tuple[str, str], str] = {}
        self._group_context = GroupHistory()
        self._question_created_callback = self._on_question_created
        self._question_resolved_callback = self._on_question_resolved
        self._approval_created_callback = self._on_approval_created
        self._approval_resolved_callback = self._on_approval_resolved

    async def start(self) -> None:
        """Validate identity, recover leases, and start bounded workers."""

        if not self.config.enabled or self._running:
            return
        try:
            await self._start_enabled()
        except BaseException as exc:
            self._status_error = f"{type(exc).__name__}: {self._safe_error(exc)}"
            await self.stop()
            raise

    async def _start_enabled(self) -> None:
        """Start an enabled manager; :meth:`start` owns failure rollback."""

        if not self.config.token:
            raise RuntimeError("Telegram token is unavailable")
        self._loop = asyncio.get_running_loop()
        self.bot = self.bot or self._create_bot(self.config.token)
        initializer = getattr(self.bot, "initialize", None)
        if callable(initializer):
            await self._api_call(initializer())
        identity = await self._api_call(self.bot.get_me())
        self.account_id = str(_value(identity, "id") or "")
        actual_username = str(_value(identity, "username") or "").lstrip("@")
        if not self.account_id or not actual_username:
            raise RuntimeError("Telegram getMe returned an incomplete bot identity")
        if actual_username.casefold() != self.config.expected_username.casefold():
            raise RuntimeError(
                "Configured Telegram bot identity does not match expected_username"
            )
        self.bot_username = actual_username
        if self.store is None:
            self.store = ChannelStore(self._store_path)
        self._fingerprint = self.store.fingerprint_token(self.config.token)
        await asyncio.to_thread(
            self.store.acquire_poller,
            platform=_PLATFORM,
            account_id=self.account_id,
            token_fingerprint=self._fingerprint,
            owner_id=self.owner_id,
            lease_seconds=_POLL_LEASE_SECONDS,
        )
        await asyncio.to_thread(self.store.recover_expired_ingress)
        await asyncio.to_thread(self.store.recover_expired_deliveries)
        recovered_callbacks = await asyncio.to_thread(
            self.store.recover_orphaned_callbacks,
            platform=_PLATFORM,
            account_id=self.account_id,
        )
        if recovered_callbacks:
            self._work_available.set()
        self._register_interactive_callbacks()
        await self._set_commands()

        if self.config.transport == "polling":
            deleter = getattr(self.bot, "delete_webhook", None)
            if callable(deleter):
                await self._api_call(deleter(drop_pending_updates=False))
        else:
            if not self.config.webhook_public_url:
                raise RuntimeError("Telegram webhook mode requires webhook.public_url")
            setter = getattr(self.bot, "set_webhook", None)
            if not callable(setter):
                raise RuntimeError("Telegram bot client does not support webhooks")
            url = self.config.webhook_public_url.rstrip("/") + self.config.webhook_path
            await self._api_call(
                setter(
                    url=url,
                    secret_token=self.config.webhook_secret,
                    allowed_updates=["message", "callback_query"],
                )
            )

        self._stop.clear()
        self._running = True
        self._tasks.extend(
            asyncio.create_task(
                self._ingress_worker(index), name=f"telegram-in-{index}"
            )
            for index in range(self.config.ingress_workers)
        )
        self._tasks.append(
            asyncio.create_task(
                self._ingress_worker("control", interactive=True),
                name="telegram-in-control",
            )
        )
        self._tasks.extend(
            asyncio.create_task(
                self._delivery_worker(index), name=f"telegram-out-{index}"
            )
            for index in range(self.config.delivery_workers)
        )
        self._tasks.append(
            asyncio.create_task(self._recovery_loop(), name="telegram-lease-recovery")
        )
        if self.config.transport == "polling":
            self._tasks.append(
                asyncio.create_task(self._polling_loop(), name="telegram-poller")
            )
        logger.info(
            "Telegram integration started username=@%s transport=%s",
            self.bot_username,
            self.config.transport,
        )

    async def stop(self) -> None:
        """Stop workers, release polling ownership, and unregister callbacks."""

        self._stop.set()
        self._work_available.set()
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        projection_tasks, self._projection_tasks = self._projection_tasks, set()
        for task in projection_tasks:
            task.cancel()
        if projection_tasks:
            await asyncio.gather(*projection_tasks, return_exceptions=True)
        self._unregister_interactive_callbacks()
        if self.store is not None and self.account_id and self._fingerprint:
            with suppress(Exception):
                await asyncio.to_thread(
                    self.store.release_poller,
                    platform=_PLATFORM,
                    account_id=self.account_id,
                    token_fingerprint=self._fingerprint,
                    owner_id=self.owner_id,
                )
        shutdown = getattr(self.bot, "shutdown", None)
        if callable(shutdown):
            with suppress(Exception):
                await self._api_call(shutdown())
        self._running = False
        logger.info("Telegram integration stopped")

    def status(self) -> dict[str, Any]:
        """Return diagnostics with no credentials or secrets."""

        return {
            "enabled": self.config.enabled,
            "running": self._running,
            "transport": self.config.transport,
            "username": f"@{self.bot_username}",
            "account_id": self.account_id or None,
            "workers": len([task for task in self._tasks if not task.done()]),
            "error": self._status_error,
        }

    def _safe_error(self, value: Any) -> str:
        text = str(value)[:1000]
        for secret in (self.config.token, self.config.webhook_secret):
            if secret:
                text = text.replace(secret, "[redacted]")
        return _TOKEN_PATTERN.sub("[redacted-telegram-token]", text)

    async def create_pairing(
        self,
        *,
        expected_user_id: str | None = None,
        ttl_seconds: int = 3600,
    ) -> str:
        """Create a one-hour, single-use DM pairing code for an operator."""

        if self.store is None or not self.account_id:
            raise RuntimeError("Telegram integration is not running")
        if ttl_seconds < 60 or ttl_seconds > 3600:
            raise ValueError("pairing TTL must be between 60 and 3600 seconds")
        code = secrets.token_hex(8).upper()
        await asyncio.to_thread(
            self.store.create_pairing,
            code,
            account_id=self.account_id,
            expected_user_id=expected_user_id,
            expires_at=time.time() + ttl_seconds,
        )
        return code

    async def revoke_dm(self, user_id: str) -> bool:
        """Revoke one pairing-derived DM grant."""

        if self.store is None or not self.account_id:
            raise RuntimeError("Telegram integration is not running")
        return bool(
            await asyncio.to_thread(
                self.store.revoke_dm_authorization,
                account_id=self.account_id,
                user_id=str(user_id),
            )
        )

    async def list_dead_letters(
        self, *, kind: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Return bounded inspectable dead-letter records."""

        if self.store is None or not self.account_id:
            raise RuntimeError("Telegram integration is not running")
        if kind == "ingress":
            records = await asyncio.to_thread(
                self.store.list_dead_ingress,
                platform=_PLATFORM,
                account_id=self.account_id,
                limit=limit,
            )
        elif kind == "delivery":
            records = await asyncio.to_thread(
                self.store.list_dead_deliveries,
                platform=_PLATFORM,
                account_id=self.account_id,
                limit=limit,
            )
        else:
            raise ValueError("dead-letter kind must be ingress or delivery")
        return [
            {
                "id": getattr(record, "event_id", None)
                or getattr(record, "delivery_id", None),
                "lane_key": record.lane_key,
                "attempt_count": record.attempt_count,
                "error_class": record.last_error_class,
                "error_message": record.last_error_message,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
                "payload": record.payload,
            }
            for record in records
        ]

    async def retry_dead_letter(self, *, kind: str, record_id: str) -> bool:
        """Explicitly requeue one terminal record."""

        if self.store is None or not self.account_id:
            raise RuntimeError("Telegram integration is not running")
        method = (
            self.store.requeue_dead_ingress
            if kind == "ingress"
            else self.store.requeue_dead_delivery
            if kind == "delivery"
            else None
        )
        if method is None:
            raise ValueError("dead-letter kind must be ingress or delivery")
        result = await asyncio.to_thread(
            method,
            record_id,
            platform=_PLATFORM,
            account_id=self.account_id,
        )
        if result:
            self._work_available.set()
        return bool(result)

    async def discard_dead_letter(self, *, kind: str, record_id: str) -> bool:
        """Delete one terminal record after an explicit operator request."""

        if self.store is None or not self.account_id:
            raise RuntimeError("Telegram integration is not running")
        method = (
            self.store.discard_dead_ingress
            if kind == "ingress"
            else self.store.discard_dead_delivery
            if kind == "delivery"
            else None
        )
        if method is None:
            raise ValueError("dead-letter kind must be ingress or delivery")
        return bool(
            await asyncio.to_thread(
                method,
                record_id,
                platform=_PLATFORM,
                account_id=self.account_id,
            )
        )

    async def admit_webhook_update(self, update: Any) -> bool:
        """Durably adopt one webhook update before acknowledging it."""

        if not self._running or self.store is None:
            raise RuntimeError("Telegram integration is not running")
        envelope = normalize_update(update, account_id=self.account_id)
        if envelope is None:
            return False
        async with self._admission_lock:
            if not await self._may_admit(envelope):
                return False
            migration = migration_chat_ids(envelope)
            lane = await self._ingress_lane(envelope)
            inserted = await asyncio.to_thread(
                self.store.admit_ingress,
                envelope.event_id,
                lane,
                envelope_to_dict(envelope),
                platform=_PLATFORM,
                account_id=self.account_id,
                group_authorization=_migration.migration_authorization(
                    self.account_id, migration
                ),
            )
        self._work_available.set()
        return bool(inserted)

    async def _polling_loop(self) -> None:
        assert self.store is not None
        offset = await asyncio.to_thread(
            self.store.get_poller_offset,
            platform=_PLATFORM,
            account_id=self.account_id,
            token_fingerprint=self._fingerprint,
        )
        failures = 0
        while not self._stop.is_set():
            try:
                renewed = await asyncio.to_thread(
                    self.store.renew_poller,
                    platform=_PLATFORM,
                    account_id=self.account_id,
                    token_fingerprint=self._fingerprint,
                    owner_id=self.owner_id,
                    lease_seconds=_POLL_LEASE_SECONDS,
                )
                if not renewed:
                    raise PollerLeaseConflictError("Telegram poller lease was lost")
                updates = await self._api_call(
                    self.bot.get_updates(
                        offset=offset,
                        timeout=self.config.poll_timeout_seconds,
                        allowed_updates=["message", "callback_query"],
                    ),
                    timeout=min(
                        self.config.poll_timeout_seconds
                        + self.config.request_timeout_seconds,
                        _POLL_LEASE_SECONDS * 2 / 3,
                    ),
                )
                failures = 0
                for update in updates:
                    raw = update_to_dict(update)
                    update_id = int(raw["update_id"])
                    next_offset = update_id + 1
                    envelope = normalize_update(raw, account_id=self.account_id)
                    if envelope is None:
                        await asyncio.to_thread(
                            self.store.advance_poller_offset,
                            next_offset,
                            platform=_PLATFORM,
                            account_id=self.account_id,
                            token_fingerprint=self._fingerprint,
                            owner_id=self.owner_id,
                        )
                    elif not await self._may_admit(envelope):
                        await asyncio.to_thread(
                            self.store.advance_poller_offset,
                            next_offset,
                            platform=_PLATFORM,
                            account_id=self.account_id,
                            token_fingerprint=self._fingerprint,
                            owner_id=self.owner_id,
                        )
                    else:
                        migration = migration_chat_ids(envelope)
                        lane = await self._ingress_lane(envelope)
                        await asyncio.to_thread(
                            self.store.admit_ingress_and_advance_poller,
                            envelope.event_id,
                            lane,
                            envelope_to_dict(envelope),
                            platform=_PLATFORM,
                            account_id=self.account_id,
                            token_fingerprint=self._fingerprint,
                            owner_id=self.owner_id,
                            new_offset=next_offset,
                            group_authorization=_migration.migration_authorization(
                                self.account_id, migration
                            ),
                        )
                        self._work_available.set()
                    offset = next_offset
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failure = classify_failure(exc)
                self._status_error = (
                    f"{failure.error_class}: {self._safe_error(failure.message)}"
                )
                if failure.polling_conflict or not failure.retryable:
                    logger.error("Telegram polling stopped: %s", self._status_error)
                    self._running = False
                    self._stop.set()
                    return
                failures += 1
                delay = retry_delay(
                    failures,
                    base_seconds=self.config.retry_base_seconds,
                    max_seconds=self.config.retry_max_seconds,
                    retry_after=failure.retry_after,
                )
                await self._wait_or_stop(delay)

    async def _ingress_worker(
        self, index: int | str, *, interactive: bool = False
    ) -> None:
        assert self.store is not None
        worker_id = f"{self.owner_id}:in:{index}"
        while not self._stop.is_set():
            record = await asyncio.to_thread(
                self.store.claim_ingress,
                platform=_PLATFORM,
                account_id=self.account_id,
                owner_id=worker_id,
                lease_seconds=_LEASE_SECONDS,
                lane_suffix=_INTERACTIVE_LANE_SUFFIX if interactive else None,
                exclude_lane_suffix=(None if interactive else _INTERACTIVE_LANE_SUFFIX),
            )
            if record is None:
                await self._wait_for_work()
                continue
            try:
                await run_with_lease_heartbeat(
                    self._handle_ingress(record, worker_id),
                    self.store.renew_ingress_lease,
                    record.event_id,
                    platform=_PLATFORM,
                    account_id=self.account_id,
                    owner_id=worker_id,
                    lease_seconds=_LEASE_SECONDS,
                )
            except asyncio.CancelledError:
                if self._stop.is_set():
                    raise
                logger.info("Telegram ingress was cancelled event=%s", record.event_id)
            except Exception:
                logger.exception("Unhandled Telegram ingress worker error")

    async def _delivery_worker(self, index: int) -> None:
        assert self.store is not None
        worker_id = f"{self.owner_id}:out:{index}"
        while not self._stop.is_set():
            record = await asyncio.to_thread(
                self.store.claim_delivery,
                platform=_PLATFORM,
                account_id=self.account_id,
                owner_id=worker_id,
                lease_seconds=_LEASE_SECONDS,
            )
            if record is None:
                await self._wait_for_work()
                continue
            try:
                try:
                    remote_id = await run_with_lease_heartbeat(
                        self._send_delivery(record),
                        self.store.renew_delivery_lease,
                        record.delivery_id,
                        platform=_PLATFORM,
                        account_id=self.account_id,
                        owner_id=worker_id,
                        lease_seconds=_LEASE_SECONDS,
                    )
                    await asyncio.to_thread(
                        self.store.complete_delivery,
                        record.delivery_id,
                        platform=_PLATFORM,
                        account_id=self.account_id,
                        owner_id=worker_id,
                        external_message_id=remote_id,
                    )
                except LeaseLostError:
                    logger.warning(
                        "Telegram delivery ownership lost id=%s",
                        record.delivery_id,
                    )
                except Exception as exc:
                    await self._handle_delivery_failure(record, worker_id, exc)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Telegram delivery persistence failed id=%s; left for recovery",
                    record.delivery_id,
                )

    async def _recovery_loop(self) -> None:
        """Recover leases that expire after this process has already started."""

        assert self.store is not None
        while not self._stop.is_set():
            await self._wait_or_stop(_RECOVERY_INTERVAL_SECONDS)
            if self._stop.is_set():
                return
            try:
                if self.config.transport == "webhook":
                    renewed = await asyncio.to_thread(
                        self.store.renew_poller,
                        platform=_PLATFORM,
                        account_id=self.account_id,
                        token_fingerprint=self._fingerprint,
                        owner_id=self.owner_id,
                        lease_seconds=_POLL_LEASE_SECONDS,
                    )
                    if not renewed:
                        self._status_error = "Telegram transport lease was lost"
                        self._running = False
                        self._stop.set()
                        return
                ingress = await asyncio.to_thread(self.store.recover_expired_ingress)
                deliveries = await asyncio.to_thread(
                    self.store.recover_expired_deliveries
                )
                callbacks = await asyncio.to_thread(
                    self.store.recover_expired_callbacks,
                    platform=_PLATFORM,
                    account_id=self.account_id,
                )
                if ingress.retried or deliveries or callbacks:
                    self._work_available.set()
            except Exception:
                logger.exception("Telegram lease recovery failed")

    async def _handle_ingress(self, record: IngressRecord, worker_id: str) -> None:
        assert self.store is not None
        envelope = envelope_from_dict(record.payload)
        started = False
        completed = False
        try:
            if not await self._is_authorized(envelope):
                await asyncio.to_thread(
                    self.store.start_ingress,
                    record.event_id,
                    platform=_PLATFORM,
                    account_id=self.account_id,
                    owner_id=worker_id,
                )
                started = True
                await self._complete_without_delivery(record, worker_id)
                return

            migration = migration_chat_ids(envelope)
            if migration is not None:
                await self._migrate_binding(*migration)
                await asyncio.to_thread(
                    self.store.start_ingress,
                    record.event_id,
                    platform=_PLATFORM,
                    account_id=self.account_id,
                    owner_id=worker_id,
                )
                started = True
                await self._complete_without_delivery(record, worker_id)
                return

            callback_data = str(envelope.metadata.get("callback_data") or "")
            if callback_data.startswith(_INTERACTIVE_PREFIX):
                await asyncio.to_thread(
                    self.store.start_ingress,
                    record.event_id,
                    platform=_PLATFORM,
                    account_id=self.account_id,
                    owner_id=worker_id,
                )
                started = True
                await self._resolve_callback(envelope, callback_data, worker_id)
                await self._complete_without_delivery(record, worker_id)
                return

            pending_key = (
                record.lane_key.removesuffix(_INTERACTIVE_LANE_SUFFIX),
                envelope.sender_id,
            )
            pending_question = self._pending_questions.get(pending_key)
            if pending_question and envelope.text.strip():
                await asyncio.to_thread(
                    self.store.start_ingress,
                    record.event_id,
                    platform=_PLATFORM,
                    account_id=self.account_id,
                    owner_id=worker_id,
                )
                started = True
                answer_result = await self._reply_to_question(
                    pending_question, envelope.text
                )
                if answer_result is True:
                    self._pending_questions.pop(pending_key, None)
                    await self._complete_with_text(
                        record, worker_id, envelope, "Answer received."
                    )
                elif answer_result is None:
                    await self._complete_with_text(
                        record,
                        worker_id,
                        envelope,
                        "Please reply with one non-empty answer per question, "
                        "one per line.",
                    )
                else:
                    self._pending_questions.pop(pending_key, None)
                    await self._complete_with_text(
                        record,
                        worker_id,
                        envelope,
                        "That question is no longer pending.",
                    )
                return

            command, arguments, target = parse_command(envelope.text)
            if target and target.casefold() != self.bot_username.casefold():
                await asyncio.to_thread(
                    self.store.start_ingress,
                    record.event_id,
                    platform=_PLATFORM,
                    account_id=self.account_id,
                    owner_id=worker_id,
                )
                started = True
                await self._complete_without_delivery(record, worker_id)
                return

            binding = await self._binding_for(envelope.address)
            if command is not None:
                await asyncio.to_thread(
                    self.store.start_ingress,
                    record.event_id,
                    platform=_PLATFORM,
                    account_id=self.account_id,
                    owner_id=worker_id,
                )
                started = True
                response = await handle_command(
                    self, command, arguments, envelope, binding
                )
                if response is None:
                    await self._complete_without_delivery(record, worker_id)
                else:
                    await self._complete_with_text(
                        record,
                        worker_id,
                        envelope,
                        response,
                        session_id=getattr(binding, "session_id", None),
                    )
                return

            if not self._is_activated(envelope, binding):
                self._observe_group_message(envelope)
                await asyncio.to_thread(
                    self.store.start_ingress,
                    record.event_id,
                    platform=_PLATFORM,
                    account_id=self.account_id,
                    owner_id=worker_id,
                )
                started = True
                await self._complete_without_delivery(record, worker_id)
                return

            bound_directory = getattr(binding, "directory", None)
            directory = normalize_directory(bound_directory)
            if bound_directory and directory is None:
                await asyncio.to_thread(
                    self.store.start_ingress,
                    record.event_id,
                    platform=_PLATFORM,
                    account_id=self.account_id,
                    owner_id=worker_id,
                )
                started = True
                await self._complete_with_text(
                    record,
                    worker_id,
                    envelope,
                    "Bound project unavailable. Update or recreate this Telegram "
                    "session binding before retrying.",
                )
                return
            directory = directory or normalize_directory(WORKSPACE_PATH)
            settings = getattr(binding, "settings", {})
            raw_history_limit = (
                settings.get("history_limit") if isinstance(settings, Mapping) else None
            )
            history_limit = (
                raw_history_limit
                if isinstance(raw_history_limit, int)
                and not isinstance(raw_history_limit, bool)
                and 0 <= raw_history_limit <= 200
                else self.config.binding_for(
                    envelope.address.chat_id, envelope.address.topic_id or None
                ).history_limit
            )
            history = self._group_context.recent(
                envelope.address.lane_key, history_limit
            )
            self._observe_group_message(envelope)
            with tempfile.TemporaryDirectory(prefix="penguin-telegram-") as temp_dir:
                try:
                    image_paths, document_inputs = await self._download_attachments(
                        envelope, Path(temp_dir)
                    )
                except ValueError as exc:
                    await asyncio.to_thread(
                        self.store.start_ingress,
                        record.event_id,
                        platform=_PLATFORM,
                        account_id=self.account_id,
                        owner_id=worker_id,
                    )
                    started = True
                    await self._complete_with_text(
                        record,
                        worker_id,
                        envelope,
                        f"Telegram attachment rejected: {exc}",
                    )
                    return
                await asyncio.to_thread(
                    self.store.start_ingress,
                    record.event_id,
                    platform=_PLATFORM,
                    account_id=self.account_id,
                    owner_id=worker_id,
                )
                started = True
                result, preview_id = await self._execute_turn(
                    envelope,
                    binding,
                    image_paths=image_paths,
                    document_inputs=document_inputs,
                    group_history=history,
                    directory=directory,
                )
            if result.get("error") or result.get("status") in {"error", "failed"}:
                error = result.get("error")
                error_text = (
                    str(error.get("message") or error)
                    if isinstance(error, Mapping)
                    else str(error or "Penguin could not complete the request.")
                )
                final_text = f"Penguin error: {error_text}"
            else:
                final_text = str(result.get("assistant_response") or "")
                if not final_text:
                    final_text = "Penguin completed the turn without a text response."
            try:
                await self._enqueue_artifacts(
                    envelope,
                    binding.session_id,
                    record,
                    result,
                    allowed_root=Path(
                        getattr(binding, "directory", None) or WORKSPACE_PATH
                    ),
                )
            except Exception:
                logger.exception(
                    "Failed to enqueue Telegram artifacts event=%s",
                    record.event_id,
                )
                final_text += (
                    "\n\nPenguin could not queue one or more generated artifacts."
                )
            await self._complete_with_text(
                record,
                worker_id,
                envelope,
                final_text,
                session_id=binding.session_id,
                request_id=envelope.event_id,
                edit_message_id=preview_id,
            )
            completed = True
        except asyncio.CancelledError:
            if started and not completed:
                with suppress(Exception):
                    await asyncio.to_thread(
                        self.store.dead_letter_ingress,
                        record.event_id,
                        platform=_PLATFORM,
                        account_id=self.account_id,
                        owner_id=worker_id,
                        error_class="execution_cancelled",
                        error_message=(
                            "Telegram turn was cancelled after execution began"
                        ),
                    )
            raise
        except Exception as exc:
            if completed:
                logger.exception(
                    "Telegram post-completion work failed event=%s", record.event_id
                )
            elif started:
                await asyncio.to_thread(
                    self.store.dead_letter_ingress,
                    record.event_id,
                    platform=_PLATFORM,
                    account_id=self.account_id,
                    owner_id=worker_id,
                    error_class="execution_uncertain",
                    error_message=self._safe_error(exc),
                )
            elif record.attempt_count < self.config.retry_attempts:
                delay = retry_delay(
                    record.attempt_count,
                    base_seconds=self.config.retry_base_seconds,
                    max_seconds=self.config.retry_max_seconds,
                )
                await asyncio.to_thread(
                    self.store.retry_ingress,
                    record.event_id,
                    platform=_PLATFORM,
                    account_id=self.account_id,
                    owner_id=worker_id,
                    retry_at=time.time() + delay,
                    error_class=type(exc).__name__,
                    error_message=self._safe_error(exc),
                )
            else:
                await asyncio.to_thread(
                    self.store.dead_letter_ingress,
                    record.event_id,
                    platform=_PLATFORM,
                    account_id=self.account_id,
                    owner_id=worker_id,
                    error_class=type(exc).__name__,
                    error_message=self._safe_error(exc),
                )
            logger.error(
                "Telegram ingress failed event=%s class=%s message=%s",
                record.event_id,
                type(exc).__name__,
                self._safe_error(exc),
            )

    def _create_bot(self, token: str) -> Any:
        if self._bot_factory is not None:
            return self._bot_factory(token)
        try:
            from telegram import Bot
        except ImportError as exc:
            raise RuntimeError(
                "Telegram support requires Python 3.10+ and "
                "`pip install penguin-ai[telegram]`"
            ) from exc
        return Bot(token=token)

    async def _set_commands(self) -> None:
        setter = getattr(self.bot, "set_my_commands", None)
        if not callable(setter):
            return
        commands = [
            ("start", "Start or resume Penguin"),
            ("help", "Show Telegram commands"),
            ("new", "Start a fresh Penguin session"),
            ("status", "Show bot and session status"),
            ("stop", "Stop the active Penguin turn"),
            ("whoami", "Show your numeric Telegram identity"),
            ("session", "Show the bound Penguin session"),
            ("mode", "Show or set plan/build mode"),
            ("model", "Show the active Penguin model"),
            ("goal", "Show or update the session goal"),
            ("project", "Show the bound project directory"),
            ("activation", "Set group mention activation"),
            ("topic", "Show the current topic binding"),
            ("pair", "Authorize this private chat"),
        ]
        with suppress(Exception):
            await self._api_call(setter(commands))

    async def _api_call(self, operation: Any, *, timeout: float | None = None) -> Any:
        """Run one Bot API operation within its configured wall-clock budget."""

        return await asyncio.wait_for(
            operation,
            timeout=self.config.request_timeout_seconds if timeout is None else timeout,
        )

    async def _wait_for_work(self) -> None:
        self._work_available.clear()
        try:
            await asyncio.wait_for(self._work_available.wait(), timeout=0.25)
        except asyncio.TimeoutError:
            return

    async def _wait_or_stop(self, delay: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=max(0.0, delay))
        except asyncio.TimeoutError:
            return

    async def _ingress_lane(self, envelope: InboundEnvelope) -> str:
        migration = migration_chat_ids(envelope)
        lane = envelope.address.lane_key
        if envelope.metadata.get("chat_type") != "private":
            lane = await _migration.stable_lane(
                self.store,
                envelope.address,
                chat_id=migration[0] if migration else None,
            )
        interactive = (
            str(envelope.metadata.get("callback_data") or "").startswith(
                _INTERACTIVE_PREFIX
            )
            or (lane, envelope.sender_id) in self._pending_questions
            or parse_command(envelope.text)[0] == "stop"
        )
        return f"{lane}{_INTERACTIVE_LANE_SUFFIX}" if interactive else lane

    async def _is_authorized(self, envelope: InboundEnvelope) -> bool:
        assert self.store is not None
        chat_type = str(envelope.metadata.get("chat_type") or "private")
        if chat_type != "private":
            return await group_event_is_authorized(
                envelope,
                config=self.config,
                store=self.store,
                account_id=self.account_id,
            )
        try:
            user_id = int(envelope.sender_id)
        except ValueError:
            return False
        if self.config.dm_policy == "pairing":
            if await asyncio.to_thread(
                self.store.is_dm_authorized,
                account_id=self.account_id,
                user_id=envelope.sender_id,
            ):
                return True
            command, arguments, target = parse_command(envelope.text)
            if (
                command == "pair"
                and arguments
                and (
                    target is None or target.casefold() == self.bot_username.casefold()
                )
            ):
                paired = await asyncio.to_thread(
                    self.store.consume_pairing,
                    arguments.split()[0],
                    account_id=self.account_id,
                    user_id=envelope.sender_id,
                    chat_id=envelope.address.chat_id,
                )
                return paired is not None
            return False
        return self.config.allows_dm(user_id)

    async def _may_admit(self, envelope: InboundEnvelope) -> bool:
        """Reject unauthorized updates before they enter durable work queues."""

        assert self.store is not None
        chat_type = str(envelope.metadata.get("chat_type") or "private")
        if chat_type != "private":
            return await group_event_is_authorized(
                envelope,
                config=self.config,
                store=self.store,
                account_id=self.account_id,
            )
        try:
            user_id = int(envelope.sender_id)
        except ValueError:
            return False
        if self.config.dm_policy != "pairing":
            return self.config.allows_dm(user_id)
        if await asyncio.to_thread(
            self.store.is_dm_authorized,
            account_id=self.account_id,
            user_id=envelope.sender_id,
        ):
            return True
        command, arguments, target = parse_command(envelope.text)
        if (
            command != "pair"
            or not arguments
            or (
                target is not None and target.casefold() != self.bot_username.casefold()
            )
        ):
            return False
        try:
            return await asyncio.to_thread(
                self.store.can_consume_pairing,
                arguments.split()[0],
                account_id=self.account_id,
                user_id=envelope.sender_id,
                chat_id=envelope.address.chat_id,
            )
        except ValueError:
            return False

    def _is_activated(self, envelope: InboundEnvelope, binding: Any) -> bool:
        if envelope.metadata.get("chat_type") == "private":
            return True
        settings = getattr(binding, "settings", {})
        activation = (
            settings.get("activation") if isinstance(settings, Mapping) else None
        ) or self.config.binding_for(
            envelope.address.chat_id, envelope.address.topic_id or None
        ).activation
        if activation == "always":
            return True
        return (
            is_addressed_to_bot(envelope.text, self.bot_username)
            or str(envelope.metadata.get("reply_sender_id") or "") == self.account_id
        )

    def _observe_group_message(self, envelope: InboundEnvelope) -> None:
        if envelope.metadata.get("chat_type") == "private" or not envelope.text:
            return
        username = envelope.sender_username or envelope.sender_id
        self._group_context.append(
            envelope.address.lane_key, f"{username}: {envelope.text[:1000]}"
        )

    async def _binding_for(self, address: ChannelAddress) -> Any:
        assert self.store is not None
        binding = await asyncio.to_thread(self.store.get_binding, address.lane_key)
        if binding is not None:
            return binding
        async with self._session_create_lock:
            binding = await asyncio.to_thread(self.store.get_binding, address.lane_key)
            if binding is not None:
                return binding
            policy = self._configured_group_binding(address)
            session_id = await asyncio.to_thread(self.core.create_conversation)
            try:
                return await asyncio.to_thread(
                    self.store.upsert_binding,
                    address.lane_key,
                    session_id,
                    directory=(
                        policy.directory
                        if policy is not None and policy.directory is not None
                        else normalize_directory(WORKSPACE_PATH)
                    ),
                    agent_id=policy.agent_id if policy is not None else None,
                    agent_mode=policy.mode if policy is not None else "build",
                    settings=(
                        policy.durable_settings() if policy is not None else None
                    ),
                    expected_version=0,
                )
            except CompareAndSwapError:
                existing = await asyncio.to_thread(
                    self.store.get_binding, address.lane_key
                )
                if existing is None:
                    raise
                return existing

    async def _new_binding(self, address: ChannelAddress, binding: Any) -> Any:
        assert self.store is not None
        async with self._session_create_lock:
            policy = self._configured_group_binding(address)
            session_id = await asyncio.to_thread(self.core.create_conversation)
            return await asyncio.to_thread(
                self.store.upsert_binding,
                address.lane_key,
                session_id,
                directory=(
                    policy.directory or normalize_directory(WORKSPACE_PATH)
                    if policy is not None
                    else getattr(binding, "directory", None)
                ),
                agent_id=(
                    policy.agent_id
                    if policy is not None
                    else getattr(binding, "agent_id", None)
                ),
                agent_mode=(
                    policy.mode
                    if policy is not None
                    else getattr(binding, "agent_mode", None)
                ),
                settings=(
                    policy.durable_settings()
                    if policy is not None
                    else getattr(binding, "settings", {})
                ),
                expected_version=getattr(binding, "version", None),
            )

    def _configured_group_binding(self, address: ChannelAddress) -> Any:
        """Return trusted defaults for a Telegram group/topic address."""

        try:
            if int(address.chat_id) >= 0:
                return None
        except ValueError:
            return None
        return self.config.binding_for(address.chat_id, address.topic_id or None)

    async def _migrate_binding(self, old_chat_id: str, new_chat_id: str) -> None:
        assert self.store is not None
        old_prefix = "\x1f".join((_PLATFORM, self.account_id, old_chat_id))
        new_prefix = "\x1f".join((_PLATFORM, self.account_id, new_chat_id))
        await asyncio.to_thread(
            self.store.migrate_binding_prefix,
            old_prefix,
            new_prefix,
            group_authorization=(
                _PLATFORM,
                self.account_id,
                old_chat_id,
                new_chat_id,
            ),
        )

    async def _execute_turn(
        self,
        envelope: InboundEnvelope,
        binding: Any,
        *,
        image_paths: list[str],
        document_inputs: list[str],
        group_history: list[str],
        directory: str | None,
    ) -> tuple[dict[str, Any], str | None]:
        text = strip_bot_mention(envelope.text, self.bot_username)
        if envelope.metadata.get("reply_text"):
            text = (
                f"[Replying to Telegram message]\n"
                f"{str(envelope.metadata['reply_text'])[:2000]}\n\n{text}"
            )
        if document_inputs:
            text = "\n\n".join([*document_inputs, text])
        if group_history:
            observed = "\n".join(group_history)
            text = (
                "[Untrusted recent Telegram group context]\n"
                f"{observed}\n"
                "[End untrusted Telegram group context]\n\n"
                f"{text}"
            )
        input_data: dict[str, Any] = {
            "text": text,
            "client_message_id": envelope.event_id,
        }
        if image_paths:
            input_data["image_paths"] = image_paths
        request_id = str(uuid.uuid4())
        context = {
            "channel": "telegram",
            "sender_id": envelope.sender_id,
            "reply_to_message_id": envelope.reply_to_message_id,
        }
        if group_history:
            context["observed_group_context"] = group_history
        settings = getattr(binding, "settings", {})
        if not isinstance(settings, Mapping):
            settings = {}
        configured = (
            self.config.binding_for(
                envelope.address.chat_id, envelope.address.topic_id or None
            )
            if envelope.metadata.get("chat_type") != "private"
            else None
        )
        prompt = settings.get(
            "prompt", configured.prompt if configured is not None else None
        )
        raw_skills = settings.get(
            "skills", configured.skills if configured is not None else ()
        )
        skills = (
            tuple(item for item in raw_skills if isinstance(item, str))
            if isinstance(raw_skills, (list, tuple))
            else ()
        )
        agent_id = getattr(binding, "agent_id", None)
        execution_context = ExecutionContext(
            session_id=binding.session_id,
            conversation_id=binding.session_id,
            agent_id=agent_id,
            agent_mode=getattr(binding, "agent_mode", None) or "build",
            directory=directory,
            project_root=directory,
            workspace_root=directory,
            request_id=request_id,
            permission_mode=self.config.permission_mode,
            approval_policy=self.config.approval_policy,
            request_system_prompt=prompt if isinstance(prompt, str) else None,
            request_skills=skills,
            require_registered_agent=bool(agent_id),
        )
        target = (envelope.address, envelope.sender_id)
        self._request_targets[request_id] = target
        self._session_targets[binding.session_id] = target
        preview = Preview(self, envelope)
        try:
            await preview.start()
            result = await execute_chat_turn(
                self.core,
                ChatProcessRequest(
                    input_data=input_data,
                    execution_context=execution_context,
                    session_id=binding.session_id,
                    context=context,
                    agent_id=agent_id,
                    streaming=self.config.streaming_mode != "off",
                    stream_callback=preview.push
                    if self.config.streaming_mode != "off"
                    else None,
                ),
            )
            return result, await preview.finish()
        finally:
            await preview.close()
            self._request_targets.pop(request_id, None)
            if self._session_targets.get(binding.session_id) == target:
                self._session_targets.pop(binding.session_id, None)

    async def _download_attachments(
        self, envelope: InboundEnvelope, directory: Path
    ) -> tuple[list[str], list[str]]:
        image_paths: list[str] = []
        document_inputs: list[str] = []
        for attachment in envelope.attachments:
            if (
                attachment.size is not None
                and attachment.size > self.config.max_download_bytes
            ):
                raise ValueError(
                    "Telegram attachment exceeds the configured size limit"
                )
            remote_file = await self._api_call(self.bot.get_file(attachment.file_id))
            safe_name = Path(
                attachment.file_name or f"{attachment.kind}-{uuid.uuid4().hex}"
            ).name
            target = directory / safe_name
            downloader = getattr(remote_file, "download_to_drive", None)
            if not callable(downloader):
                raise RuntimeError("Telegram file cannot be downloaded")
            await self._api_call(downloader(custom_path=str(target)))
            size = target.stat().st_size
            if size > self.config.max_download_bytes:
                raise ValueError(
                    "Downloaded Telegram attachment exceeds the size limit"
                )
            if attachment.kind == "photo":
                await asyncio.to_thread(_validate_image, target)
                image_paths.append(str(target))
                continue
            mime = (attachment.mime_type or "").lower()
            if not (mime.startswith("text/") or mime in _TEXT_DOCUMENT_MIMES):
                raise ValueError(
                    f"Unsupported Telegram document type: {mime or 'unknown'}"
                )
            text = await asyncio.to_thread(target.read_text, "utf-8")
            if len(text) > self.config.max_document_text_chars:
                raise ValueError("Telegram text document exceeds the character limit")
            document_inputs.append(
                f"[Begin untrusted Telegram document {safe_name!r}]\n{text}\n"
                "[End untrusted Telegram document]"
            )
        return image_paths, document_inputs

    async def _complete_with_text(
        self,
        record: IngressRecord,
        worker_id: str,
        envelope: InboundEnvelope,
        text: str,
        *,
        session_id: str | None = None,
        request_id: str | None = None,
        edit_message_id: str | None = None,
    ) -> None:
        assert self.store is not None
        delivery_id = f"{record.event_id}:final"
        payload = _delivery_payload(
            envelope.address,
            text,
            reply_to_message_id=envelope.reply_to_message_id,
            edit_message_id=edit_message_id,
        )
        await asyncio.to_thread(
            self.store.complete_ingress_and_enqueue_delivery,
            record.event_id,
            ingress_owner_id=worker_id,
            delivery_id=delivery_id,
            idempotency_key=delivery_id,
            lane_key=record.lane_key.removesuffix(_INTERACTIVE_LANE_SUFFIX),
            payload=payload,
            platform=_PLATFORM,
            account_id=self.account_id,
            kind="text",
            source_session_id=session_id,
            source_request_id=request_id,
        )
        self._work_available.set()

    async def _complete_without_delivery(
        self, record: IngressRecord, worker_id: str
    ) -> None:
        assert self.store is not None
        await asyncio.to_thread(
            self.store.complete_ingress,
            record.event_id,
            platform=_PLATFORM,
            account_id=self.account_id,
            owner_id=worker_id,
        )

    async def _send_delivery(self, record: DeliveryRecord) -> str | None:
        assert self.store is not None
        payload = record.payload
        chat_id = await _migration.latest_chat_id(
            self.store,
            platform=record.platform,
            account_id=record.account_id,
            chat_id=str(payload["chat_id"]),
        )
        topic_id = payload.get("topic_id") or None
        if record.kind == "text":
            return await self._send_text_payload(payload, chat_id, topic_id)
        if record.kind == "callback_terminal":
            return await self._send_callback_terminal(payload, chat_id)
        path = validated_artifact_path(payload, self.config.max_download_bytes)
        kwargs = {"chat_id": chat_id}
        if topic_id is not None:
            kwargs["message_thread_id"] = int(topic_id)
        with path.open("rb") as file_obj:
            if record.kind == "photo":
                message = await self._api_call(
                    self.bot.send_photo(photo=file_obj, **kwargs)
                )
            else:
                message = await self._api_call(
                    self.bot.send_document(document=file_obj, **kwargs)
                )
        return _message_id(message)

    async def _send_text_payload(
        self, payload: Mapping[str, Any], chat_id: Any, topic_id: Any
    ) -> str | None:
        text = str(payload.get("text") or "")
        chunks = formatted_chunks(text) or [("", "")]
        edit_id = payload.get("edit_message_id")
        last_id: str | None = None
        button_message_id: str | None = None
        for index, (chunk, fallback) in enumerate(chunks):
            try:
                if index == 0 and edit_id:
                    message = await self._api_call(
                        self.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=int(edit_id),
                            text=chunk,
                            parse_mode="HTML",
                        )
                    )
                else:
                    kwargs: dict[str, Any] = {
                        "chat_id": chat_id,
                        "text": chunk,
                        "parse_mode": "HTML",
                    }
                    if topic_id:
                        kwargs["message_thread_id"] = int(topic_id)
                    if index == 0 and payload.get("reply_to_message_id"):
                        kwargs["reply_to_message_id"] = int(
                            payload["reply_to_message_id"]
                        )
                    markup = _inline_markup(payload.get("buttons"))
                    if markup is not None and index == 0:
                        kwargs["reply_markup"] = markup
                    message = await self._api_call(self.bot.send_message(**kwargs))
            except Exception as exc:
                if type(exc).__name__ != "BadRequest":
                    raise
                kwargs = {"chat_id": chat_id, "text": fallback}
                if topic_id:
                    kwargs["message_thread_id"] = int(topic_id)
                if index == 0 and payload.get("reply_to_message_id"):
                    kwargs["reply_to_message_id"] = int(payload["reply_to_message_id"])
                markup = _inline_markup(payload.get("buttons"))
                if markup is not None and index == 0:
                    kwargs["reply_markup"] = markup
                message = await self._api_call(self.bot.send_message(**kwargs))
            current_id = _message_id(message)
            if index == 0 and payload.get("buttons"):
                button_message_id = current_id
            last_id = current_id or last_id
        return button_message_id or last_id

    async def _send_callback_terminal(
        self, payload: Mapping[str, Any], chat_id: Any
    ) -> str | None:
        assert self.store is not None
        projection_id = str(payload.get("projection_delivery_id") or "")
        projection = await asyncio.to_thread(
            self.store.get_delivery,
            projection_id,
            platform=_PLATFORM,
            account_id=self.account_id,
        )
        if projection is None or not projection.external_message_id:
            return None
        label = str(payload.get("label") or "Expired")
        message = await self._api_call(
            self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=int(projection.external_message_id),
                text=f"<b>{label}</b>",
                parse_mode="HTML",
                reply_markup=None,
            )
        )
        return _message_id(message) or projection.external_message_id

    async def _handle_delivery_failure(
        self, record: DeliveryRecord, worker_id: str, exc: BaseException
    ) -> None:
        assert self.store is not None
        failure = classify_failure(exc)
        age = time.time() - record.created_at
        retryable = (
            failure.retryable
            and record.attempt_count < self.config.retry_attempts
            and age < self.config.dead_letter_after_hours * 3600
        )
        if retryable:
            delay = retry_delay(
                record.attempt_count,
                base_seconds=self.config.retry_base_seconds,
                max_seconds=self.config.retry_max_seconds,
                retry_after=failure.retry_after,
            )
            await asyncio.to_thread(
                self.store.retry_delivery,
                record.delivery_id,
                platform=_PLATFORM,
                account_id=self.account_id,
                owner_id=worker_id,
                retry_at=time.time() + delay,
                error_class=failure.error_class,
                error_message=self._safe_error(failure.message),
            )
        else:
            self._status_error = (
                f"{failure.error_class}: {self._safe_error(failure.message)}"
            )
            await asyncio.to_thread(
                self.store.dead_letter_delivery,
                record.delivery_id,
                platform=_PLATFORM,
                account_id=self.account_id,
                owner_id=worker_id,
                error_class=failure.error_class,
                error_message=self._safe_error(failure.message),
            )
            if failure.error_class.casefold() == "invalidtoken":
                self._running = False
                self._stop.set()
                self._work_available.set()
        logger.warning(
            "Telegram delivery failed id=%s retryable=%s class=%s",
            record.delivery_id,
            retryable,
            failure.error_class,
        )

    async def _enqueue_artifacts(
        self,
        envelope: InboundEnvelope,
        session_id: str,
        ingress: IngressRecord,
        result: Mapping[str, Any],
        *,
        allowed_root: Path,
    ) -> None:
        assert self.store is not None
        root = allowed_root.expanduser().resolve()
        skipped = 0
        for index, path in enumerate(artifact_paths(result)):
            try:
                resolved = Path(path).expanduser().resolve(strict=True)
                resolved.relative_to(root)
            except (OSError, ValueError):
                skipped += 1
                continue
            if not resolved.is_file() or (
                resolved.stat().st_size > self.config.max_download_bytes
            ):
                skipped += 1
                continue
            kind = (
                "photo"
                if resolved.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
                else "document"
            )
            delivery_id = f"{ingress.event_id}:artifact:{index}"
            await asyncio.to_thread(
                self.store.enqueue_delivery,
                delivery_id,
                delivery_id,
                ingress.lane_key.removesuffix(_INTERACTIVE_LANE_SUFFIX),
                {
                    "chat_id": envelope.address.chat_id,
                    "topic_id": envelope.address.topic_id,
                    "path": str(resolved),
                    "allowed_root": str(root),
                },
                platform=_PLATFORM,
                account_id=self.account_id,
                kind=kind,
                source_event_id=ingress.event_id,
                source_session_id=session_id,
            )
        if skipped:
            warning_id = f"{ingress.event_id}:artifact-warning"
            await asyncio.to_thread(
                self.store.enqueue_delivery,
                warning_id,
                warning_id,
                ingress.lane_key.removesuffix(_INTERACTIVE_LANE_SUFFIX),
                _delivery_payload(
                    envelope.address,
                    f"Penguin skipped {skipped} unsafe or unavailable artifact(s).",
                ),
                platform=_PLATFORM,
                account_id=self.account_id,
                kind="text",
                source_event_id=ingress.event_id,
                source_session_id=session_id,
            )
        self._work_available.set()

    def _register_interactive_callbacks(self) -> None:
        from penguin.security.approval import get_approval_manager
        from penguin.security.question import get_question_manager

        get_question_manager().on_request_created(self._question_created_callback)
        get_question_manager().on_request_answered(self._question_resolved_callback)
        get_question_manager().on_request_rejected(self._question_resolved_callback)
        get_approval_manager().on_request_created(self._approval_created_callback)
        get_approval_manager().on_request_resolved(self._approval_resolved_callback)

    def _unregister_interactive_callbacks(self) -> None:
        from penguin.security.approval import get_approval_manager
        from penguin.security.question import get_question_manager

        get_question_manager().remove_callback(self._question_created_callback)
        get_question_manager().remove_callback(self._question_resolved_callback)
        get_approval_manager().remove_callback(self._approval_created_callback)
        get_approval_manager().remove_callback(self._approval_resolved_callback)

    def _on_question_created(self, request: Any) -> None:
        target = self._projection_target(request)
        if target is not None:
            self._schedule_projection(self._project_question(request, target))

    def _on_approval_created(self, request: Any) -> None:
        target = self._projection_target(request)
        if target is not None:
            self._schedule_projection(self._project_approval(request, target))

    def _projection_target(self, request: Any) -> tuple[ChannelAddress, str] | None:
        context = getattr(request, "context", {})
        request_id = context.get("request_id") if isinstance(context, Mapping) else None
        if request_id:
            return self._request_targets.get(str(request_id))
        return self._session_targets.get(str(request.session_id))

    def _on_question_resolved(self, request: Any) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(
            self._discard_pending_question,
            str(request.id),
        )
        label = interactive_terminal_label(request)
        if label is not None:
            self._schedule_projection(self._terminalize_request(request, label))

    def _on_approval_resolved(self, request: Any) -> None:
        label = interactive_terminal_label(request)
        if label is not None:
            self._schedule_projection(self._terminalize_request(request, label))

    async def _terminalize_request(self, request: Any, label: str) -> None:
        if self.store is None:
            return
        records = await asyncio.to_thread(
            self.store.terminalize_callbacks,
            str(request.id),
            account_id=self.account_id,
            label=label,
            platform=_PLATFORM,
            expired=label == "Expired",
        )
        if records:
            self._work_available.set()

    def _discard_pending_question(self, request_id: str) -> None:
        stale = [
            key
            for key, pending_request_id in self._pending_questions.items()
            if pending_request_id == request_id
        ]
        for key in stale:
            self._pending_questions.pop(key, None)

    def _schedule_projection(self, coroutine: Any) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            close = getattr(coroutine, "close", None)
            if callable(close):
                close()
            return

        def schedule() -> None:
            task = asyncio.create_task(coroutine)
            self._projection_tasks.add(task)
            task.add_done_callback(self._projection_tasks.discard)

        loop.call_soon_threadsafe(schedule)

    async def _project_question(
        self, request: Any, target: tuple[ChannelAddress, str]
    ) -> None:
        if self.store is None:
            return
        address, user_id = target
        callback_id = uuid.uuid4().hex
        questions = list(getattr(request, "questions", []) or [])
        text_lines = ["Penguin needs your input:"]
        buttons: list[list[dict[str, str]]] = []
        if len(questions) == 1:
            first = questions[0]
            text_lines.append(str(first.get("question") or "Choose an answer"))
            for index, option in enumerate(first.get("options") or []):
                label = str(option.get("label") or option.get("description") or index)
                buttons.append(
                    [
                        {
                            "text": label[:40],
                            "data": f"{_INTERACTIVE_PREFIX}{callback_id}:q{index}",
                        }
                    ]
                )
            text_lines.append("You may also reply with text.")
        elif questions:
            for index, question in enumerate(questions, start=1):
                text_lines.append(
                    f"{index}. {question.get('question') or 'Provide an answer'}"
                )
            text_lines.append(
                "Reply with exactly one non-empty answer per line, in the same order."
            )
        self._pending_questions[(address.lane_key, user_id)] = str(request.id)
        await self._create_projection(
            address,
            f"question:{request.id}",
            "\n\n".join(text_lines),
            buttons,
            session_id=str(request.session_id),
            user_id=user_id,
            callback_id=callback_id,
            request_id=str(request.id),
            callback_payload={"kind": "question", "questions": questions},
        )
        label = interactive_terminal_label(request)
        if label is not None:
            await self._terminalize_request(request, label)

    async def _project_approval(
        self, request: Any, target: tuple[ChannelAddress, str]
    ) -> None:
        if self.store is None:
            return
        address, user_id = target
        callback_id = uuid.uuid4().hex
        buttons = [
            [
                {
                    "text": "Approve once",
                    "data": f"{_INTERACTIVE_PREFIX}{callback_id}:approve",
                },
                {"text": "Deny", "data": f"{_INTERACTIVE_PREFIX}{callback_id}:deny"},
            ]
        ]
        if address.chat_id == user_id:
            text = (
                f"Tool approval required\nTool: {request.tool_name}\n"
                f"Operation: {request.operation}\nResource: {request.resource}\n"
                f"Reason: {request.reason}"
            )
        else:
            text = (
                "Tool approval required\n"
                "Sensitive operation details are hidden in shared chats."
            )
        await self._create_projection(
            address,
            f"approval:{request.id}",
            text,
            buttons,
            session_id=str(request.session_id or ""),
            user_id=user_id,
            callback_id=callback_id,
            request_id=str(request.id),
            callback_payload={"kind": "approval"},
            tool_call_id=str(getattr(request, "context", {}).get("tool_call_id") or "")
            or None,
        )
        label = interactive_terminal_label(request)
        if label is not None:
            await self._terminalize_request(request, label)

    async def _create_projection(
        self,
        address: ChannelAddress,
        key: str,
        text: str,
        buttons: list[list[dict[str, str]]],
        *,
        session_id: str,
        user_id: str,
        callback_id: str,
        request_id: str,
        callback_payload: Mapping[str, Any],
        tool_call_id: str | None = None,
    ) -> None:
        assert self.store is not None
        delivery_id = f"telegram:{key}"
        delivery = _delivery_payload(address, text)
        delivery["buttons"] = buttons
        callback = {
            **callback_payload,
            "projection_delivery_id": delivery_id,
            "lane_key": address.lane_key,
            "platform": _PLATFORM,
            "session_id": session_id,
        }
        await asyncio.to_thread(
            self.store.create_callback_with_delivery,
            callback_id,
            account_id=self.account_id,
            chat_id=address.chat_id,
            topic_id=address.topic_id or None,
            user_id=user_id,
            request_id=request_id,
            payload=callback,
            expires_at=time.time() + self.config.approval_timeout_seconds,
            projection_delivery_id=delivery_id,
            lane_key=address.lane_key,
            delivery_payload=delivery,
            platform=_PLATFORM,
            source_session_id=session_id,
            tool_call_id=tool_call_id,
        )
        self._work_available.set()

    async def _resolve_callback(
        self, envelope: InboundEnvelope, callback_data: str, worker_id: str
    ) -> None:
        assert self.store is not None
        parts = callback_data.split(":", 2)
        if len(parts) != 3:
            return
        _prefix, callback_id, action = parts
        callback = await asyncio.to_thread(
            self.store.claim_callback,
            callback_id,
            account_id=self.account_id,
            chat_id=envelope.address.chat_id,
            topic_id=envelope.address.topic_id or None,
            user_id=envelope.sender_id,
            owner_id=worker_id,
            platform=_PLATFORM,
        )
        if callback is None:
            await self._answer_callback(envelope, "This action is unavailable.")
            return
        kind = callback.payload.get("kind")
        resolved = False
        label = "Expired"
        if kind == "approval":
            from penguin.security.approval import ApprovalScope, get_approval_manager

            manager = get_approval_manager()
            if action == "approve":
                resolved = (
                    manager.approve(callback.request_id, scope=ApprovalScope.ONCE)
                    is not None
                )
                if resolved:
                    label = "Approved"
            elif action == "deny":
                resolved = manager.deny(callback.request_id) is not None
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
                resolved = await self._reply_to_question(callback.request_id, answer)
                if resolved:
                    label = "Answered"
                    self._pending_questions.pop(
                        (envelope.address.lane_key, envelope.sender_id), None
                    )
        await asyncio.to_thread(
            self.store.complete_callback_with_terminal,
            callback_id,
            owner_id=worker_id,
            label=label,
            platform=_PLATFORM,
        )
        self._work_available.set()
        await self._answer_callback(
            envelope,
            "Recorded." if resolved else "This request is no longer pending.",
        )

    async def _reply_to_question(self, request_id: str, text: str) -> bool | None:
        from penguin.security.question import get_question_manager

        request = get_question_manager().get_request(request_id)
        if request is None or request.status.value != "pending":
            return False
        questions = list(request.questions or [])
        if len(questions) <= 1:
            answers = [[text.strip()]]
        else:
            values = [line.strip() for line in text.splitlines() if line.strip()]
            if len(values) != len(questions):
                return None
            answers = [[value] for value in values]
        return get_question_manager().reply(request_id, answers) is not None

    async def _answer_callback(self, envelope: InboundEnvelope, text: str) -> None:
        callback_id = envelope.metadata.get("callback_id")
        answer = getattr(self.bot, "answer_callback_query", None)
        if callback_id and callable(answer):
            with suppress(Exception):
                await self._api_call(
                    answer(callback_query_id=callback_id, text=text[:200])
                )


def _validate_image(path: Path) -> None:
    try:
        with Image.open(path) as image:
            image.verify()
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError("Telegram photo is not a valid supported image") from exc
