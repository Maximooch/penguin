from __future__ import annotations

import asyncio
import sqlite3
import sys
import time
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from penguin.channels.store import (
    ChannelStore,
    LeaseLostError,
    PollerLeaseConflictError,
)
from penguin.integrations.telegram import manager as manager_module
from penguin.integrations.telegram._artifacts import artifact_paths
from penguin.integrations.telegram.binding_policy import TelegramBindingPolicy
from penguin.integrations.telegram.config import TelegramConfig
from penguin.integrations.telegram.manager import TelegramManager
from penguin.integrations.telegram.updates import normalize_update
from penguin.security.approval import ApprovalStatus, get_approval_manager
from penguin.security.question import get_question_manager
from penguin.system.execution_context import get_current_execution_context
from penguin.tools.artifact_tools import PublishArtifactTool
from penguin.tools.runtime import (
    legacy_action_result_from_tool_result,
    tool_result_from_action_result,
)


@pytest.fixture(autouse=True)
def reset_interactive_managers():
    get_approval_manager().reset()
    get_question_manager().reset()
    yield
    get_approval_manager().reset()
    get_question_manager().reset()


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.edits: list[dict[str, Any]] = []
        self.documents: list[dict[str, Any]] = []
        self.photos: list[dict[str, Any]] = []
        self.markup_edits: list[dict[str, Any]] = []
        self.callback_answers: list[dict[str, Any]] = []
        self.actions: list[dict[str, Any]] = []
        self.commands: list[Any] = []
        self.webhook: dict[str, Any] | None = None
        self.initialized = False
        self.closed = False
        self._next_message_id = 1

    async def initialize(self) -> None:
        self.initialized = True

    async def shutdown(self) -> None:
        self.closed = True

    async def get_me(self) -> Any:
        return SimpleNamespace(id=867, username="Penguin_agent_bot")

    async def set_my_commands(self, commands: list[Any]) -> None:
        self.commands = commands

    async def set_webhook(self, **kwargs: Any) -> None:
        self.webhook = kwargs

    async def send_message(self, **kwargs: Any) -> Any:
        self.messages.append(dict(kwargs))
        message_id = self._next_message_id
        self._next_message_id += 1
        return SimpleNamespace(message_id=message_id)

    async def edit_message_text(self, **kwargs: Any) -> Any:
        self.edits.append(dict(kwargs))
        return SimpleNamespace(message_id=kwargs["message_id"])

    async def send_chat_action(self, **kwargs: Any) -> None:
        self.actions.append(dict(kwargs))

    async def send_document(self, *, document: Any, **kwargs: Any) -> Any:
        self.documents.append({**kwargs, "name": Path(document.name).name})
        message_id = self._next_message_id
        self._next_message_id += 1
        return SimpleNamespace(message_id=message_id)

    async def send_photo(self, *, photo: Any, **kwargs: Any) -> Any:
        self.photos.append({**kwargs, "name": Path(photo.name).name})
        message_id = self._next_message_id
        self._next_message_id += 1
        return SimpleNamespace(message_id=message_id)

    async def answer_callback_query(self, **kwargs: Any) -> None:
        self.callback_answers.append(dict(kwargs))

    async def edit_message_reply_markup(self, **kwargs: Any) -> Any:
        self.markup_edits.append(dict(kwargs))
        return SimpleNamespace(message_id=kwargs["message_id"])


class PollingBot(FakeBot):
    """Fake Bot API boundary that inspects state before the next long poll."""

    def __init__(self, store: ChannelStore, update: dict[str, Any]) -> None:
        super().__init__()
        self.store = store
        self.update = update
        self.offsets: list[int | None] = []
        self.persisted_before_next_poll = False
        self.observed = asyncio.Event()

    async def delete_webhook(self, **kwargs: Any) -> None:
        del kwargs

    async def get_updates(self, *, offset: int | None, **kwargs: Any) -> list[Any]:
        del kwargs
        self.offsets.append(offset)
        if len(self.offsets) == 1:
            return [self.update]

        account_id = "867"
        fingerprint = self.store.fingerprint_token("test-only-token")
        ingress = self.store.get_ingress(
            f"telegram:{account_id}:{self.update['update_id']}",
            platform="telegram",
            account_id=account_id,
        )
        persisted_offset = self.store.get_poller_offset(
            platform="telegram",
            account_id=account_id,
            token_fingerprint=fingerprint,
        )
        self.persisted_before_next_poll = (
            ingress is not None
            and persisted_offset == self.update["update_id"] + 1
            and offset == persisted_offset
        )
        self.observed.set()
        await asyncio.Event().wait()
        return []


class TransportLeaseBot(FakeBot):
    """Track transport mutations while keeping polling alive."""

    def __init__(self) -> None:
        super().__init__()
        self.deleted_webhooks = 0
        self.polling_started = asyncio.Event()

    async def delete_webhook(self, **kwargs: Any) -> None:
        del kwargs
        self.deleted_webhooks += 1

    async def get_updates(self, **kwargs: Any) -> list[Any]:
        del kwargs
        self.polling_started.set()
        await asyncio.Event().wait()
        return []


class MigrationBatchPollingBot(FakeBot):
    def __init__(self, updates: list[dict[str, Any]]) -> None:
        super().__init__()
        self.updates = updates
        self.poll_count = 0
        self.batch_persisted = asyncio.Event()

    async def delete_webhook(self, **kwargs: Any) -> None:
        del kwargs

    async def get_updates(self, **kwargs: Any) -> list[Any]:
        del kwargs
        self.poll_count += 1
        if self.poll_count == 1:
            return self.updates
        self.batch_persisted.set()
        await asyncio.Event().wait()
        return []


class NetworkError(Exception):
    """Transport-shaped transient failure recognized by retry classification."""


class BadRequest(Exception):
    """Transport-shaped fatal formatting/edit failure."""


class Conflict(Exception):
    """Transport-shaped competing getUpdates failure."""


class InvalidToken(Exception):
    """Transport-shaped integration-fatal credential failure."""


class ConflictPollingBot(FakeBot):
    async def delete_webhook(self, **kwargs: Any) -> None:
        del kwargs

    async def get_updates(self, **kwargs: Any) -> list[Any]:
        del kwargs
        raise Conflict("another getUpdates consumer")


class InvalidTokenDeliveryBot(FakeBot):
    async def send_message(self, **kwargs: Any) -> Any:
        del kwargs
        raise InvalidToken("invalid test-only-token")


class FlakyDeliveryBot(FakeBot):
    """Fail the first final send, then behave like Telegram recovered."""

    def __init__(self) -> None:
        super().__init__()
        self.send_attempts = 0

    async def send_message(self, **kwargs: Any) -> Any:
        self.send_attempts += 1
        if self.send_attempts == 1:
            raise NetworkError("temporary Telegram outage")
        return await super().send_message(**kwargs)


class StalledDeliveryBot(FakeBot):
    """Let the manager's request deadline cancel the first delivery attempt."""

    def __init__(self) -> None:
        super().__init__()
        self.send_attempts = 0
        self.first_attempt_cancelled = asyncio.Event()

    async def send_message(self, **kwargs: Any) -> Any:
        self.send_attempts += 1
        if self.send_attempts == 1:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.first_attempt_cancelled.set()
                raise
        return await super().send_message(**kwargs)


class SlowDeliveryBot(FakeBot):
    """Hold a send open while the durable delivery lease is renewed."""

    def __init__(self) -> None:
        super().__init__()
        self.send_started = asyncio.Event()
        self.release_send = asyncio.Event()

    async def send_message(self, **kwargs: Any) -> Any:
        self.send_started.set()
        await self.release_send.wait()
        return await super().send_message(**kwargs)


class CompleteLeaseLossStore(ChannelStore):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.fail_next_completion = True

    def complete_delivery(self, *args: Any, **kwargs: Any) -> None:
        if self.fail_next_completion:
            self.fail_next_completion = False
            raise LeaseLostError("simulated stale delivery owner")
        super().complete_delivery(*args, **kwargs)


class IngressLeaseLossStore(ChannelStore):
    def renew_ingress_lease(self, *args: Any, **kwargs: Any) -> bool:
        return False


class ArtifactEnqueueFailureStore(ChannelStore):
    def enqueue_delivery(self, *args: Any, **kwargs: Any) -> bool:
        if kwargs.get("kind") in {"photo", "document"}:
            raise RuntimeError("simulated artifact projection failure")
        return super().enqueue_delivery(*args, **kwargs)


class EditFailBot(FakeBot):
    async def edit_message_text(self, **kwargs: Any) -> Any:
        del kwargs
        raise BadRequest("preview is no longer editable")


class FailingPollingBot(FakeBot):
    async def delete_webhook(self, **kwargs: Any) -> None:
        del kwargs
        raise RuntimeError("polling setup failed")


class DownloadableFile:
    """Fake Telegram file that records every temporary download target."""

    def __init__(self, content: bytes) -> None:
        self.content = content
        self.paths: list[Path] = []

    async def download_to_drive(self, *, custom_path: str) -> None:
        path = Path(custom_path)
        self.paths.append(path)
        path.write_bytes(self.content)


class MediaBot(FakeBot):
    """Fake Bot API media boundary with deterministic file payloads."""

    def __init__(self, files: dict[str, DownloadableFile]) -> None:
        super().__init__()
        self.files = files

    async def get_file(self, file_id: str) -> DownloadableFile:
        return self.files[file_id]


class FakeCore:
    def __init__(self) -> None:
        self.session_number = 0
        self.calls: list[dict[str, Any]] = []
        self.contexts: list[Any] = []
        self.model_config = SimpleNamespace(model="fake-model")

    def create_conversation(self) -> str:
        self.session_number += 1
        return f"session-{self.session_number}"

    async def abort_session(self, session_id: str) -> bool:
        return bool(session_id)

    async def process(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        self.contexts.append(get_current_execution_context())
        callback = kwargs.get("stream_callback")
        if callback is not None:
            await callback("streamed ", "assistant")
        return {
            "assistant_response": f"reply:{kwargs['input_data']['text']}",
            "action_results": [],
            "status": "ok",
        }


class MediaCore(FakeCore):
    """Observe that downloaded image paths exist only during Penguin execution."""

    def __init__(self) -> None:
        super().__init__()
        self.image_path: Path | None = None
        self.image_existed_during_turn = False
        self.document_input_text: str | None = None
        self.context_files: list[str] = []

    async def process(self, **kwargs: Any) -> dict[str, Any]:
        image_paths = kwargs["input_data"].get("image_paths") or []
        if image_paths:
            self.image_path = Path(image_paths[0])
            self.image_existed_during_turn = self.image_path.is_file()
        self.context_files = list(kwargs.get("context_files") or [])
        self.document_input_text = str(kwargs["input_data"].get("text") or "")
        return await super().process(**kwargs)


class ArtifactCore(FakeCore):
    def __init__(self, paths: list[Path]) -> None:
        super().__init__()
        self.paths = paths

    async def process(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {
            "assistant_response": "artifacts ready",
            "action_results": [
                {"artifact": {"path": str(path)}} for path in self.paths
            ],
            "status": "ok",
        }


class RuntimeArtifactCore(FakeCore):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path

    async def process(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        produced = PublishArtifactTool().execute(str(self.path))
        tool_result = tool_result_from_action_result(
            produced,
            call_id="publish-report",
            structured_output=produced,
        )
        return {
            "assistant_response": "report ready",
            "action_results": [legacy_action_result_from_tool_result(tool_result)],
            "status": "ok",
        }


class QuestionCore(FakeCore):
    def __init__(self) -> None:
        super().__init__()
        self.answered = asyncio.Event()

    async def process(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        context = get_current_execution_context()
        request = get_question_manager().create_request(
            session_id=str(context.session_id),
            questions=[
                {
                    "header": "Choice",
                    "question": "Which option?",
                    "options": [
                        {"label": "Alpha", "description": "First"},
                        {"label": "Beta", "description": "Second"},
                    ],
                }
            ],
        )
        resolved = await get_question_manager().wait_for_resolution(
            request.id, timeout_seconds=2
        )
        assert resolved is not None
        self.answered.set()
        return {
            "assistant_response": f"answer:{resolved.answers[0][0]}",
            "action_results": [],
            "status": "ok",
        }


class MultiQuestionCore(FakeCore):
    def __init__(self) -> None:
        super().__init__()
        self.answered = asyncio.Event()
        self.answers: list[list[str]] | None = None

    async def process(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        context = get_current_execution_context()
        request = get_question_manager().create_request(
            session_id=str(context.session_id),
            questions=[
                {"header": "First", "question": "First answer?", "options": []},
                {"header": "Second", "question": "Second answer?", "options": []},
            ],
        )
        resolved = await get_question_manager().wait_for_resolution(
            request.id, timeout_seconds=3
        )
        assert resolved is not None
        self.answers = resolved.answers
        self.answered.set()
        return {
            "assistant_response": "multi answered",
            "action_results": [],
            "status": "ok",
        }


class ApprovalCore(FakeCore):
    def __init__(self) -> None:
        super().__init__()
        self.side_effect_count = 0
        self.request_id: str | None = None
        self.request_created = asyncio.Event()

    async def process(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        context = get_current_execution_context()
        request = get_approval_manager().create_request(
            tool_name="write",
            operation="filesystem.write",
            resource="notes.txt",
            reason="test approval",
            session_id=str(context.session_id),
            context={"tool_call_id": "call-1"},
            ttl_seconds=2,
        )
        self.request_id = request.id
        self.request_created.set()
        resolved = await asyncio.to_thread(
            get_approval_manager().wait_for_resolution, request.id, 2
        )
        if resolved is not None and resolved.status == ApprovalStatus.APPROVED:
            self.side_effect_count += 1
            response = "approved"
        else:
            response = "denied"
        return {
            "assistant_response": response,
            "action_results": [],
            "status": "ok",
        }


class SharedSessionProjectionCore(FakeCore):
    """Create request-scoped approvals from two serialized shared-session turns."""

    def __init__(self) -> None:
        super().__init__()
        self.first_started = asyncio.Event()
        self.release_first = asyncio.Event()

    async def process(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        text = str(kwargs["input_data"]["text"])
        execution = get_current_execution_context()
        if text == "first":
            self.first_started.set()
            await self.release_first.wait()
        get_approval_manager().create_request(
            tool_name="write",
            operation="filesystem.write",
            resource=f"{text}.txt",
            reason=f"approve {text}",
            session_id=str(execution.session_id),
            context={"request_id": execution.request_id},
            ttl_seconds=2,
        )
        return {
            "assistant_response": f"queued:{text}",
            "action_results": [],
            "status": "ok",
        }


class BlockingCore(FakeCore):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def process(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise

    async def abort_session(self, session_id: str) -> bool:
        tasks = getattr(self, "_opencode_process_tasks", {}).get(session_id, set())
        for task in tuple(tasks):
            task.cancel()
        return bool(tasks)


class MigrationOrderingCore(FakeCore):
    """Hold the pre-migration turn while later group updates are admitted."""

    def __init__(self) -> None:
        super().__init__()
        self.first_started = asyncio.Event()
        self.release_first = asyncio.Event()

    async def process(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        text = str(kwargs["input_data"]["text"])
        if text == "before migration":
            self.first_started.set()
            await self.release_first.wait()
        return {
            "assistant_response": f"reply:{text}",
            "action_results": [],
            "status": "ok",
        }


def _config(**overrides: Any) -> TelegramConfig:
    values: dict[str, Any] = {
        "enabled": True,
        "token": "test-only-token",
        "expected_username": "Penguin_agent_bot",
        "transport": "webhook",
        "webhook_public_url": "https://example.test",
        "webhook_secret": "secret",
        "dm_policy": "allowlist",
        "allow_from": frozenset({42}),
        "streaming_mode": "progress",
        "ingress_workers": 2,
        "delivery_workers": 2,
    }
    values.update(overrides)
    return TelegramConfig(**values)


def _update(update_id: int, text: str, *, user_id: int = 42) -> dict[str, Any]:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "chat": {"id": user_id, "type": "private"},
            "from": {"id": user_id, "username": f"user{user_id}"},
            "text": text,
        },
    }


async def _wait_for(predicate: Any, timeout: float = 3.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition did not become true")
        await asyncio.sleep(0.01)


def test_missing_runtime_explains_python_and_install_extra(monkeypatch: Any) -> None:
    manager = TelegramManager(FakeCore(), _config())
    monkeypatch.setitem(sys.modules, "telegram", None)

    with pytest.raises(RuntimeError, match=r"Python 3\.10\+.*penguin-ai\[telegram\]"):
        manager._create_bot("test-only-token")


def test_artifact_discovery_requires_an_explicit_projection() -> None:
    assert artifact_paths(
        {
            "action_results": [
                {"path": "/private/direct.txt"},
                {"result": {"path": "/private/result.txt"}},
                {"output": {"file_path": "/private/output.txt"}},
                {"artifact": {"path": "/safe/report.txt"}},
            ]
        }
    ) == ["/safe/report.txt"]


@pytest.mark.asyncio
async def test_webhook_dm_round_trip_is_durable_and_reuses_binding(
    tmp_path: Path,
) -> None:
    bot = FakeBot()
    core = FakeCore()
    store = ChannelStore(tmp_path / "channel.db")
    manager = TelegramManager(core, _config(), bot=bot, store=store)
    await manager.start()
    try:
        assert await manager.admit_webhook_update(_update(1, "hello")) is True
        await _wait_for(lambda: len(core.calls) == 1 and bool(bot.edits))

        assert await manager.admit_webhook_update(_update(1, "hello")) is False
        assert await manager.admit_webhook_update(_update(2, "again")) is True
        await _wait_for(lambda: len(core.calls) == 2)

        assert {call["conversation_id"] for call in core.calls} == {"session-1"}
        assert core.contexts[0].permission_mode == "workspace"
        assert core.contexts[0].approval_policy["wait_for_resolution"] is True
        assert (
            store.get_ingress(
                "telegram:867:1", platform="telegram", account_id="867"
            ).state
            == "completed"
        )
        assert manager.status()["username"] == "@Penguin_agent_bot"
        assert "token" not in repr(manager.status()).lower()
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_polling_persists_update_before_requesting_the_next_offset(
    tmp_path: Path,
) -> None:
    """The next poll may begin only after ingress and its watermark are durable."""
    store = ChannelStore(tmp_path / "channel.db")
    bot = PollingBot(store, _update(20, "persist me"))
    manager = TelegramManager(
        FakeCore(),
        _config(transport="polling", streaming_mode="off"),
        bot=bot,
        store=store,
    )

    await manager.start()
    try:
        await asyncio.wait_for(bot.observed.wait(), timeout=1.0)

        assert bot.offsets[:2] == [None, 21]
        assert bot.persisted_before_next_poll is True
    finally:
        await manager.stop()


@pytest.mark.parametrize(
    ("owner_transport", "contender_transport"),
    [("webhook", "polling"), ("polling", "webhook")],
)
@pytest.mark.asyncio
async def test_polling_and_webhook_share_transport_ownership(
    tmp_path: Path,
    owner_transport: str,
    contender_transport: str,
) -> None:
    store = ChannelStore(tmp_path / "channel.db")
    owner_bot = TransportLeaseBot()
    owner = TelegramManager(
        FakeCore(),
        _config(transport=owner_transport, streaming_mode="off"),
        bot=owner_bot,
        store=store,
    )
    contender_bot = TransportLeaseBot()
    contender = TelegramManager(
        FakeCore(),
        _config(transport=contender_transport, streaming_mode="off"),
        bot=contender_bot,
        store=store,
    )

    await owner.start()
    try:
        if owner_transport == "polling":
            await asyncio.wait_for(owner_bot.polling_started.wait(), timeout=1.0)
        with pytest.raises(PollerLeaseConflictError):
            await contender.start()

        assert contender_bot.deleted_webhooks == 0
        assert contender_bot.webhook is None
    finally:
        await owner.stop()

    replacement_bot = TransportLeaseBot()
    replacement = TelegramManager(
        FakeCore(),
        _config(transport=contender_transport, streaming_mode="off"),
        bot=replacement_bot,
        store=store,
    )
    await replacement.start()
    try:
        if contender_transport == "polling":
            assert replacement_bot.deleted_webhooks == 1
        else:
            assert replacement_bot.webhook is not None
    finally:
        await replacement.stop()


@pytest.mark.asyncio
async def test_start_failure_rolls_back_bot_and_poller_ownership(
    tmp_path: Path,
) -> None:
    store = ChannelStore(tmp_path / "channel.db")
    bot = FailingPollingBot()
    config = _config(transport="polling")
    manager = TelegramManager(FakeCore(), config, bot=bot, store=store)

    with pytest.raises(RuntimeError, match="polling setup failed"):
        await manager.start()

    assert bot.closed is True
    assert manager.status()["running"] is False
    assert "polling setup failed" in str(manager.status()["error"])
    replacement = store.acquire_poller(
        platform="telegram",
        account_id="867",
        token_fingerprint=store.fingerprint_token("test-only-token"),
        owner_id="replacement",
        lease_seconds=10,
    )
    assert replacement.owner_id == "replacement"


@pytest.mark.asyncio
async def test_fatal_polling_exit_updates_running_status(tmp_path: Path) -> None:
    manager = TelegramManager(
        FakeCore(),
        _config(transport="polling", streaming_mode="off"),
        bot=ConflictPollingBot(),
        store=ChannelStore(tmp_path / "channel.db"),
    )
    await manager.start()
    try:
        await _wait_for(lambda: manager.status()["running"] is False)
        assert "Conflict" in str(manager.status()["error"])
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_invalid_token_delivery_stops_integration_and_sets_safe_status(
    tmp_path: Path,
) -> None:
    store = ChannelStore(tmp_path / "channel.db")
    manager = TelegramManager(
        FakeCore(),
        _config(streaming_mode="off", delivery_workers=1),
        bot=InvalidTokenDeliveryBot(),
        store=store,
    )
    await manager.start()
    try:
        assert await manager.admit_webhook_update(_update(26, "credential"))
        await _wait_for(lambda: manager.status()["running"] is False)
        delivery = store.get_delivery(
            "telegram:867:26:final",
            platform="telegram",
            account_id="867",
        )
        assert delivery is not None and delivery.state == "dead"
        error = str(manager.status()["error"])
        assert "InvalidToken" in error
        assert "test-only-token" not in error
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_transient_delivery_failure_is_durable_and_eventually_retried(
    tmp_path: Path,
) -> None:
    """A transient Bot API failure remains recoverable in the delivery outbox."""
    bot = FlakyDeliveryBot()
    store = ChannelStore(tmp_path / "channel.db")
    manager = TelegramManager(
        FakeCore(),
        _config(
            streaming_mode="off",
            delivery_workers=1,
            retry_base_seconds=0.2,
            retry_max_seconds=0.2,
        ),
        bot=bot,
        store=store,
    )
    delivery_id = "telegram:867:21:final"

    await manager.start()
    try:
        assert await manager.admit_webhook_update(_update(21, "retry me")) is True
        await _wait_for(
            lambda: (
                (
                    record := store.get_delivery(
                        delivery_id,
                        platform="telegram",
                        account_id="867",
                    )
                )
                is not None
                and record.state == "retry"
            )
        )
        retry_record = store.get_delivery(
            delivery_id,
            platform="telegram",
            account_id="867",
        )
        assert retry_record is not None
        assert retry_record.last_error_class == "NetworkError"

        await _wait_for(
            lambda: (
                (
                    record := store.get_delivery(
                        delivery_id,
                        platform="telegram",
                        account_id="867",
                    )
                )
                is not None
                and record.state == "delivered"
            )
        )
        delivered = store.get_delivery(
            delivery_id,
            platform="telegram",
            account_id="867",
        )

        assert delivered is not None
        assert delivered.attempt_count == 2
        assert bot.send_attempts == 2
        assert [message["text"] for message in bot.messages] == ["reply:retry me"]
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_stalled_delivery_is_timed_out_and_retried(tmp_path: Path) -> None:
    bot = StalledDeliveryBot()
    store = ChannelStore(tmp_path / "channel.db")
    manager = TelegramManager(
        FakeCore(),
        _config(
            streaming_mode="off",
            delivery_workers=1,
            request_timeout_seconds=0.05,
            retry_base_seconds=0.05,
            retry_max_seconds=0.05,
        ),
        bot=bot,
        store=store,
    )
    delivery_id = "telegram:867:22:final"

    await manager.start()
    try:
        assert await manager.admit_webhook_update(_update(22, "timeout")) is True
        await asyncio.wait_for(bot.first_attempt_cancelled.wait(), timeout=1.0)
        await _wait_for(
            lambda: (
                (
                    record := store.get_delivery(
                        delivery_id,
                        platform="telegram",
                        account_id="867",
                    )
                )
                is not None
                and record.state == "delivered"
            )
        )
        delivered = store.get_delivery(
            delivery_id,
            platform="telegram",
            account_id="867",
        )

        assert delivered is not None and delivered.attempt_count == 2
        assert bot.send_attempts == 2
        assert [message["text"] for message in bot.messages] == ["reply:timeout"]
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_slow_delivery_renews_lease_until_send_completes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(manager_module, "_LEASE_SECONDS", 0.12)
    bot = SlowDeliveryBot()
    store = ChannelStore(tmp_path / "channel.db")
    manager = TelegramManager(
        FakeCore(),
        _config(
            streaming_mode="off",
            delivery_workers=1,
            request_timeout_seconds=2,
        ),
        bot=bot,
        store=store,
    )
    delivery_id = "telegram:867:23:final"

    await manager.start()
    try:
        assert await manager.admit_webhook_update(_update(23, "slow send"))
        await asyncio.wait_for(bot.send_started.wait(), timeout=1.0)
        await asyncio.sleep(0.2)

        assert store.recover_expired_deliveries() == 0
        assert (
            store.claim_delivery(
                platform="telegram",
                account_id="867",
                owner_id="contender",
                lease_seconds=1,
            )
            is None
        )
        bot.release_send.set()
        await _wait_for(
            lambda: (
                (
                    record := store.get_delivery(
                        delivery_id,
                        platform="telegram",
                        account_id="867",
                    )
                )
                is not None
                and record.state == "delivered"
            )
        )
        delivered = store.get_delivery(
            delivery_id,
            platform="telegram",
            account_id="867",
        )
        assert delivered is not None and delivered.attempt_count == 1
    finally:
        bot.release_send.set()
        await manager.stop()


@pytest.mark.asyncio
async def test_delivery_worker_survives_completion_lease_loss(tmp_path: Path) -> None:
    bot = FakeBot()
    store = CompleteLeaseLossStore(tmp_path / "channel.db")
    manager = TelegramManager(
        FakeCore(),
        _config(
            allow_from=frozenset({42, 43}),
            streaming_mode="off",
            delivery_workers=1,
        ),
        bot=bot,
        store=store,
    )

    await manager.start()
    try:
        assert await manager.admit_webhook_update(_update(24, "first"))
        await _wait_for(
            lambda: any(item.get("text") == "reply:first" for item in bot.messages)
        )
        assert await manager.admit_webhook_update(_update(25, "second", user_id=43))
        await _wait_for(
            lambda: (
                (
                    record := store.get_delivery(
                        "telegram:867:25:final",
                        platform="telegram",
                        account_id="867",
                    )
                )
                is not None
                and record.state == "delivered"
            )
        )
        second = store.get_delivery(
            "telegram:867:25:final",
            platform="telegram",
            account_id="867",
        )
        assert second is not None and second.state == "delivered"
        assert any(
            task.get_name() == "telegram-out-0" and not task.done()
            for task in manager._tasks
        )
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_ingress_lease_loss_cancels_live_turn(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setattr(manager_module, "_LEASE_SECONDS", 0.06)
    bot = FakeBot()
    core = BlockingCore()
    store = IngressLeaseLossStore(tmp_path / "channel.db")
    manager = TelegramManager(
        core,
        _config(streaming_mode="off", ingress_workers=1),
        bot=bot,
        store=store,
    )

    await manager.start()
    try:
        assert await manager.admit_webhook_update(_update(90, "keep working"))
        await asyncio.wait_for(core.started.wait(), timeout=1.0)
        await asyncio.wait_for(core.cancelled.wait(), timeout=1.0)
        await _wait_for(
            lambda: (
                (
                    record := store.get_ingress(
                        "telegram:867:90", platform="telegram", account_id="867"
                    )
                )
                is not None
                and record.state == "dead"
            )
        )

        assert bot.messages == []
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_final_edit_failure_falls_back_to_plain_new_message() -> None:
    bot = EditFailBot()
    manager = TelegramManager(FakeCore(), _config(), bot=bot)

    message_id = await manager._send_text_payload(
        {
            "text": "**final answer**",
            "edit_message_id": "99",
            "reply_to_message_id": "7",
        },
        "42",
        "10",
    )

    assert message_id == "1"
    assert bot.messages == [
        {
            "chat_id": "42",
            "text": "final answer",
            "message_thread_id": 10,
            "reply_to_message_id": 7,
        }
    ]


@pytest.mark.asyncio
async def test_lease_expiring_after_start_is_recovered_without_another_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChannelStore(tmp_path / "channel.db")
    store.enqueue_delivery(
        "stale-delivery",
        "stale-delivery",
        "telegram\x1f867\x1f42\x1f",
        {"chat_id": "42", "topic_id": "", "text": "recovered"},
        platform="telegram",
        account_id="867",
    )
    claimed = store.claim_delivery(
        platform="telegram",
        account_id="867",
        owner_id="crashed-process",
        lease_seconds=0.3,
        now=time.time(),
    )
    assert claimed is not None
    monkeypatch.setattr(manager_module, "_RECOVERY_INTERVAL_SECONDS", 0.01)
    bot = FakeBot()
    manager = TelegramManager(FakeCore(), _config(), bot=bot, store=store)

    await manager.start()
    try:
        await _wait_for(
            lambda: (
                (
                    record := store.get_delivery(
                        "stale-delivery",
                        platform="telegram",
                        account_id="867",
                    )
                )
                is not None
                and record.state == "delivered"
            )
        )
        delivered = store.get_delivery(
            "stale-delivery",
            platform="telegram",
            account_id="867",
        )

        assert delivered is not None and delivered.state == "delivered"
        assert bot.messages[0]["text"] == "recovered"
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_media_downloads_are_bounded_and_temporary_files_are_cleaned(
    tmp_path: Path,
) -> None:
    """Media exists for the turn only; downloaded oversize bodies never execute."""
    image_buffer = BytesIO()
    Image.new("RGB", (1, 1), color="blue").save(image_buffer, format="PNG")
    valid_file = DownloadableFile(image_buffer.getvalue())
    oversized_file = DownloadableFile(b"x" * 2048)
    document_file = DownloadableFile(b"untrusted document")
    bot = MediaBot(
        {
            "valid-photo": valid_file,
            "oversized-photo": oversized_file,
            "text-document": document_file,
        }
    )
    core = MediaCore()
    store = ChannelStore(tmp_path / "channel.db")
    manager = TelegramManager(
        core,
        _config(
            streaming_mode="off",
            max_download_bytes=1024,
            retry_attempts=1,
        ),
        bot=bot,
        store=store,
    )
    valid_update = _update(40, "inspect this photo")
    valid_update["message"]["photo"] = [
        {
            "file_id": "valid-photo",
            "file_size": len(valid_file.content),
        }
    ]
    oversized_update = _update(41, "reject this photo")
    oversized_update["message"]["photo"] = [
        {
            "file_id": "oversized-photo",
            "file_size": 10,
        }
    ]
    document_update = _update(43, "read this document")
    document_update["message"]["document"] = {
        "file_id": "text-document",
        "file_name": "notes.txt",
        "mime_type": "text/plain",
        "file_size": len(document_file.content),
    }

    await manager.start()
    try:
        assert await manager.admit_webhook_update(valid_update) is True
        await _wait_for(
            lambda: (
                (
                    record := store.get_ingress(
                        "telegram:867:40",
                        platform="telegram",
                        account_id="867",
                    )
                )
                is not None
                and record.state == "completed"
            )
        )

        assert core.image_existed_during_turn is True
        assert core.image_path is not None
        assert core.image_path.is_file() is False
        assert valid_file.paths and all(not path.exists() for path in valid_file.paths)

        assert await manager.admit_webhook_update(oversized_update) is True
        await _wait_for(
            lambda: (
                (
                    record := store.get_ingress(
                        "telegram:867:41",
                        platform="telegram",
                        account_id="867",
                    )
                )
                is not None
                and record.state == "completed"
            )
        )
        await _wait_for(
            lambda: any(
                "size limit" in message.get("text", "") for message in bot.messages
            )
        )

        assert len(core.calls) == 1
        assert oversized_file.paths
        assert all(not path.exists() for path in oversized_file.paths)

        assert await manager.admit_webhook_update(document_update) is True
        await _wait_for(lambda: len(core.calls) == 2)

        assert core.context_files == []
        assert core.document_input_text == (
            "[Begin untrusted Telegram document 'notes.txt']\n"
            "untrusted document\n"
            "[End untrusted Telegram document]\n\n"
            "read this document"
        )
        assert document_file.paths
        assert all(not path.exists() for path in document_file.paths)
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_artifacts_are_durable_and_confined_to_bound_project(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    allowed = project / "report.txt"
    allowed.write_text("report", encoding="utf-8")
    outside = tmp_path / "private.txt"
    outside.write_text("private", encoding="utf-8")
    bot = FakeBot()
    core = ArtifactCore([allowed, outside])
    store = ChannelStore(tmp_path / "channel.db")
    store.upsert_binding(
        "telegram\x1f867\x1f42\x1f",
        "session-artifacts",
        directory=str(project),
        agent_mode="build",
        expected_version=0,
    )
    manager = TelegramManager(
        core,
        _config(streaming_mode="off"),
        bot=bot,
        store=store,
    )

    await manager.start()
    try:
        await manager.admit_webhook_update(_update(42, "make artifacts"))
        await _wait_for(lambda: bool(bot.documents))
        await _wait_for(
            lambda: any(
                "skipped 1 unsafe" in message.get("text", "")
                for message in bot.messages
            )
        )

        assert bot.documents == [{"chat_id": "42", "name": "report.txt"}]
        assert all(item["name"] != "private.txt" for item in bot.documents)
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_explicit_runtime_artifact_reaches_telegram_delivery(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    artifact = project / "report.txt"
    artifact.write_text("report", encoding="utf-8")
    bot = FakeBot()
    store = ChannelStore(tmp_path / "channel.db")
    store.upsert_binding(
        "telegram\x1f867\x1f42\x1f",
        "session-runtime-artifact",
        directory=str(project),
        agent_mode="build",
        expected_version=0,
    )
    manager = TelegramManager(
        RuntimeArtifactCore(artifact),
        _config(streaming_mode="off"),
        bot=bot,
        store=store,
    )

    await manager.start()
    try:
        assert await manager.admit_webhook_update(_update(46, "send the report"))
        await _wait_for(lambda: bool(bot.documents))

        assert bot.documents == [{"chat_id": "42", "name": "report.txt"}]
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_artifact_projection_failure_is_visible_in_final_message(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    artifact = project / "report.txt"
    artifact.write_text("report", encoding="utf-8")
    bot = FakeBot()
    store = ArtifactEnqueueFailureStore(tmp_path / "channel.db")
    store.upsert_binding(
        "telegram\x1f867\x1f42\x1f",
        "session-artifact-failure",
        directory=str(project),
        agent_mode="build",
        expected_version=0,
    )
    manager = TelegramManager(
        ArtifactCore([artifact]),
        _config(streaming_mode="off"),
        bot=bot,
        store=store,
    )

    await manager.start()
    try:
        assert await manager.admit_webhook_update(_update(45, "make artifact"))
        await _wait_for(
            lambda: any(
                "could not queue one or more generated artifacts"
                in message.get("text", "")
                for message in bot.messages
            )
        )

        ingress = store.get_ingress(
            "telegram:867:45", platform="telegram", account_id="867"
        )
        assert ingress is not None and ingress.state == "completed"
        assert bot.documents == []
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_artifact_symlink_swap_after_enqueue_is_rejected(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    artifact = project / "report.txt"
    artifact.write_text("safe report", encoding="utf-8")
    outside = tmp_path / "private.txt"
    outside.write_text("private", encoding="utf-8")
    bot = FakeBot()
    store = ChannelStore(tmp_path / "channel.db")
    manager = TelegramManager(FakeCore(), _config(), bot=bot, store=store)
    manager.account_id = "867"
    envelope = normalize_update(_update(43, "make artifact"), account_id="867")
    assert envelope is not None
    store.admit_ingress(
        envelope.event_id,
        envelope.address.lane_key,
        {"event": envelope.event_id},
        platform="telegram",
        account_id="867",
    )
    ingress = store.get_ingress(
        envelope.event_id,
        platform="telegram",
        account_id="867",
    )
    assert ingress is not None
    await manager._enqueue_artifacts(
        envelope,
        "session-artifact-swap",
        ingress,
        {"action_results": [{"artifact": {"path": str(artifact)}}]},
        allowed_root=project,
    )
    delivery = store.get_delivery(
        f"{envelope.event_id}:artifact:0",
        platform="telegram",
        account_id="867",
    )
    assert delivery is not None
    assert delivery.payload["allowed_root"] == str(project.resolve())

    artifact.unlink()
    artifact.symlink_to(outside)

    with pytest.raises(ValueError, match="unsafe or unavailable"):
        await manager._send_delivery(delivery)
    assert bot.documents == []


@pytest.mark.asyncio
async def test_missing_bound_project_is_rejected_without_workspace_fallback(
    tmp_path: Path,
) -> None:
    project = tmp_path / "removed-project"
    project.mkdir()
    bot = FakeBot()
    core = FakeCore()
    store = ChannelStore(tmp_path / "channel.db")
    store.upsert_binding(
        "telegram\x1f867\x1f42\x1f",
        "session-missing-project",
        directory=str(project),
        agent_mode="build",
        expected_version=0,
    )
    project.rmdir()
    manager = TelegramManager(
        core,
        _config(streaming_mode="off"),
        bot=bot,
        store=store,
    )

    await manager.start()
    try:
        assert await manager.admit_webhook_update(_update(44, "do work"))
        await _wait_for(
            lambda: any(
                "Bound project unavailable" in message.get("text", "")
                for message in bot.messages
            )
        )

        assert core.calls == []
        record = store.get_ingress(
            "telegram:867:44", platform="telegram", account_id="867"
        )
        assert record is not None and record.state == "completed"
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_unauthorized_sender_never_reaches_penguin(tmp_path: Path) -> None:
    bot = FakeBot()
    core = FakeCore()
    store = ChannelStore(tmp_path / "channel.db")
    manager = TelegramManager(
        core,
        _config(),
        bot=bot,
        store=store,
    )
    await manager.start()
    try:
        with sqlite3.connect(store.path) as conn:
            before = conn.execute(
                """SELECT
                    (SELECT COUNT(*) FROM channel_ingress),
                    (SELECT COUNT(*) FROM channel_deliveries)
                """
            ).fetchone()

        assert (
            await manager.admit_webhook_update(_update(3, "hello", user_id=99)) is False
        )
        await asyncio.sleep(0.05)

        with sqlite3.connect(store.path) as conn:
            after = conn.execute(
                """SELECT
                    (SELECT COUNT(*) FROM channel_ingress),
                    (SELECT COUNT(*) FROM channel_deliveries)
                """
            ).fetchone()

        assert core.calls == []
        assert bot.messages == []
        assert before == after == (0, 0)
        assert (
            store.get_ingress("telegram:867:3", platform="telegram", account_id="867")
            is None
        )
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_pairing_grants_one_expected_dm_without_broadening_access(
    tmp_path: Path,
) -> None:
    """A manager-issued code is expected-user, single-use, and DM-only."""
    bot = FakeBot()
    core = FakeCore()
    store = ChannelStore(tmp_path / "channel.db")
    manager = TelegramManager(
        core,
        _config(dm_policy="pairing", streaming_mode="off"),
        bot=bot,
        store=store,
    )
    await manager.start()
    try:
        code = await manager.create_pairing(expected_user_id="42", ttl_seconds=60)

        assert (
            await manager.admit_webhook_update(_update(30, f"/pair {code}", user_id=99))
            is False
        )
        assert not store.is_dm_authorized(account_id="867", user_id="99")

        assert await manager.admit_webhook_update(_update(31, f"/pair {code}"))
        await _wait_for(lambda: store.is_dm_authorized(account_id="867", user_id="42"))
        assert await manager.admit_webhook_update(_update(32, "paired hello"))
        await _wait_for(lambda: len(core.calls) == 1)

        assert (
            await manager.admit_webhook_update(_update(33, f"/pair {code}", user_id=99))
            is False
        )
        assert (
            await manager.admit_webhook_update(
                {
                    "update_id": 34,
                    "message": {
                        "message_id": 34,
                        "chat": {"id": -100, "type": "supergroup"},
                        "from": {"id": 42},
                        "text": "paired grant must not authorize this group",
                    },
                }
            )
            is False
        )

        assert len(core.calls) == 1
        assert not store.is_dm_authorized(account_id="867", user_id="99")
        assert all(
            store.get_ingress(
                f"telegram:867:{update_id}",
                platform="telegram",
                account_id="867",
            )
            is None
            for update_id in (30, 33, 34)
        )
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_new_command_rebinds_without_running_a_model_turn(tmp_path: Path) -> None:
    bot = FakeBot()
    core = FakeCore()
    store = ChannelStore(tmp_path / "channel.db")
    manager = TelegramManager(core, _config(streaming_mode="off"), bot=bot, store=store)
    await manager.start()
    try:
        await manager.admit_webhook_update(_update(4, "/status"))
        await _wait_for(lambda: bool(bot.messages))
        address_key = "telegram\x1f867\x1f42\x1f"
        assert store.get_binding(address_key).session_id == "session-1"

        await manager.admit_webhook_update(_update(5, "/new"))
        await _wait_for(
            lambda: store.get_binding(address_key).session_id == "session-2"
        )

        assert core.calls == []
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_stop_uses_reserved_control_worker_and_preserves_normal_capacity(
    tmp_path: Path,
) -> None:
    bot = FakeBot()
    core = BlockingCore()
    store = ChannelStore(tmp_path / "channel.db")
    manager = TelegramManager(
        core,
        _config(streaming_mode="off", ingress_workers=1),
        bot=bot,
        store=store,
    )
    await manager.start()
    try:
        await manager.admit_webhook_update(_update(50, "keep working"))
        await asyncio.wait_for(core.started.wait(), timeout=1.0)
        await manager.admit_webhook_update(_update(51, "/stop"))

        await asyncio.wait_for(core.cancelled.wait(), timeout=1.0)
        await _wait_for(
            lambda: any(
                "Stopped the active Penguin turn" in message.get("text", "")
                for message in bot.messages
            )
        )
        await _wait_for(
            lambda: (
                (
                    record := store.get_ingress(
                        "telegram:867:50",
                        platform="telegram",
                        account_id="867",
                    )
                )
                is not None
                and record.state == "dead"
            )
        )

        assert any(
            task.get_name() == "telegram-in-0" and not task.done()
            for task in manager._tasks
        )
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_group_topics_receive_distinct_sessions(tmp_path: Path) -> None:
    bot = FakeBot()
    core = FakeCore()
    config = _config(
        group_policy="allowlist",
        allowed_group_ids=frozenset({-100}),
        allowed_group_sender_ids=frozenset({42}),
        activation="always",
        streaming_mode="off",
    )
    store = ChannelStore(tmp_path / "channel.db")
    manager = TelegramManager(core, config, bot=bot, store=store)
    await manager.start()
    try:
        for update_id, topic_id in ((6, 10), (7, 11)):
            await manager.admit_webhook_update(
                {
                    "update_id": update_id,
                    "message": {
                        "message_id": update_id,
                        "message_thread_id": topic_id,
                        "chat": {"id": -100, "type": "supergroup"},
                        "from": {"id": 42},
                        "text": "hello",
                    },
                }
            )
        await _wait_for(lambda: len(core.calls) == 2)

        assert len({call["conversation_id"] for call in core.calls}) == 2
        assert store.get_binding("telegram\x1f867\x1f-100\x1f10") is not None
        assert store.get_binding("telegram\x1f867\x1f-100\x1f11") is not None
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_webhook_migration_preserves_binding_order_and_destination(
    tmp_path: Path,
) -> None:
    core = MigrationOrderingCore()
    bot = FakeBot()
    store = ChannelStore(tmp_path / "channel.db")
    old_lane = "telegram\x1f867\x1f-100\x1f"
    new_lane = "telegram\x1f867\x1f-200\x1f"
    store.upsert_binding(
        old_lane,
        "session-existing",
        directory=str(tmp_path),
        expected_version=0,
    )
    manager = TelegramManager(
        core,
        _config(
            group_policy="allowlist",
            allowed_group_ids=frozenset({-100}),
            allowed_group_sender_ids=frozenset({42}),
            activation="always",
            streaming_mode="off",
        ),
        bot=bot,
        store=store,
    )
    before = {
        "update_id": 99,
        "message": {
            "message_id": 99,
            "chat": {"id": -100, "type": "group"},
            "from": {"id": 42},
            "text": "before migration",
        },
    }
    migration = {
        "update_id": 100,
        "message": {
            "message_id": 100,
            "chat": {"id": -100, "type": "group"},
            "migrate_to_chat_id": -200,
        },
    }
    following = {
        "update_id": 101,
        "message": {
            "message_id": 101,
            "chat": {"id": -200, "type": "supergroup"},
            "from": {"id": 42},
            "text": "after migration",
        },
    }

    await manager.start()
    try:
        assert await manager.admit_webhook_update(before)
        await asyncio.wait_for(core.first_started.wait(), timeout=1.0)
        assert await manager.admit_webhook_update(migration)
        assert await manager.admit_webhook_update(following)

        records = [
            store.get_ingress(
                f"telegram:867:{update_id}",
                platform="telegram",
                account_id="867",
            )
            for update_id in (99, 100, 101)
        ]
        assert all(record is not None for record in records)
        assert {record.lane_key for record in records if record is not None} == {
            old_lane
        }
        assert (
            store.claim_ingress(
                platform="telegram",
                account_id="867",
                owner_id="race-check",
                lease_seconds=1,
            )
            is None
        )
        assert len(core.calls) == 1

        core.release_first.set()
        await _wait_for(lambda: len(core.calls) == 2 and len(bot.messages) == 2)

        assert [call["input_data"]["text"] for call in core.calls] == [
            "before migration",
            "after migration",
        ]
        assert [call["conversation_id"] for call in core.calls] == [
            "session-existing",
            "session-existing",
        ]
        assert [message["chat_id"] for message in bot.messages] == ["-200", "-200"]
        assert [message["text"] for message in bot.messages] == [
            "reply:before migration",
            "reply:after migration",
        ]
        assert store.get_binding(old_lane) is None
        assert store.get_binding(new_lane).session_id == "session-existing"
    finally:
        core.release_first.set()
        await manager.stop()


@pytest.mark.asyncio
async def test_polling_migration_batch_admits_following_new_group_update(
    tmp_path: Path,
) -> None:
    updates = [
        {
            "update_id": 110,
            "message": {
                "message_id": 110,
                "chat": {"id": -100, "type": "group"},
                "migrate_to_chat_id": -200,
            },
        },
        {
            "update_id": 111,
            "message": {
                "message_id": 111,
                "chat": {"id": -200, "type": "supergroup"},
                "from": {"id": 42},
                "text": "continue",
            },
        },
    ]
    core = FakeCore()
    bot = MigrationBatchPollingBot(updates)
    manager = TelegramManager(
        core,
        _config(
            transport="polling",
            group_policy="allowlist",
            allowed_group_ids=frozenset({-100}),
            allowed_group_sender_ids=frozenset({42}),
            activation="always",
            streaming_mode="off",
        ),
        bot=bot,
        store=ChannelStore(tmp_path / "channel.db"),
    )

    await manager.start()
    try:
        await asyncio.wait_for(bot.batch_persisted.wait(), timeout=1.0)
        await _wait_for(lambda: len(core.calls) == 1)
    finally:
        await manager.stop()


@pytest.mark.parametrize(
    ("migration_field", "event_chat_id", "event_chat_type"),
    [
        ("migrate_to_chat_id", -100, "group"),
        ("migrate_from_chat_id", -100200, "supergroup"),
    ],
)
@pytest.mark.asyncio
async def test_supergroup_migration_moves_base_and_topic_bindings(
    tmp_path: Path,
    migration_field: str,
    event_chat_id: int,
    event_chat_type: str,
) -> None:
    old_prefix = "telegram\x1f867\x1f-100"
    new_prefix = "telegram\x1f867\x1f-100200"
    old_base_key = old_prefix + "\x1f"
    old_topic_key = old_prefix + "\x1f42"
    store = ChannelStore(tmp_path / "channel.db")
    base_before = store.upsert_binding(
        old_base_key,
        "session-group",
        directory=str(tmp_path),
        agent_id="group-agent",
        agent_mode="build",
        settings={
            "activation": "mention",
            "prompt": "Base group prompt",
            "skills": ["review"],
        },
        expected_version=0,
    )
    topic_before = store.upsert_binding(
        old_topic_key,
        "session-topic-42",
        directory=str(tmp_path),
        agent_id="topic-agent",
        agent_mode="plan",
        settings={
            "activation": "always",
            "prompt": "Topic prompt",
            "skills": ["tdd"],
        },
        expected_version=0,
    )
    manager = TelegramManager(
        FakeCore(),
        _config(
            group_policy="allowlist",
            allowed_group_ids=frozenset({-100}),
            allowed_group_sender_ids=frozenset({42}),
            streaming_mode="off",
        ),
        bot=FakeBot(),
        store=store,
    )

    await manager.start()
    try:
        assert await manager.admit_webhook_update(
            {
                "update_id": 63,
                "message": {
                    "message_id": 63,
                    "chat": {"id": event_chat_id, "type": event_chat_type},
                    migration_field: -100200
                    if migration_field == "migrate_to_chat_id"
                    else -100,
                },
            }
        )
        await _wait_for(
            lambda: (
                (
                    record := store.get_ingress(
                        "telegram:867:63",
                        platform="telegram",
                        account_id="867",
                    )
                )
                is not None
                and record.state == "completed"
            )
        )

        assert store.get_binding(old_base_key) is None
        assert store.get_binding(old_topic_key) is None
        base_after = store.get_binding(new_prefix + "\x1f")
        topic_after = store.get_binding(new_prefix + "\x1f42")
        assert base_after is not None
        assert topic_after is not None
        assert (
            base_after.session_id,
            base_after.directory,
            base_after.agent_id,
            base_after.agent_mode,
            base_after.settings,
            base_after.version,
        ) == (
            base_before.session_id,
            base_before.directory,
            base_before.agent_id,
            base_before.agent_mode,
            base_before.settings,
            base_before.version + 1,
        )
        assert (
            topic_after.session_id,
            topic_after.directory,
            topic_after.agent_id,
            topic_after.agent_mode,
            topic_after.settings,
            topic_after.version,
        ) == (
            topic_before.session_id,
            topic_before.directory,
            topic_before.agent_id,
            topic_before.agent_mode,
            topic_before.settings,
            topic_before.version + 1,
        )
        assert store.is_group_authorized(
            platform="telegram",
            account_id="867",
            chat_id="-100200",
            allowed_source_chat_ids=frozenset({"-100"}),
        )
        assert not store.is_group_authorized(
            platform="telegram",
            account_id="867",
            chat_id="-100200",
            allowed_source_chat_ids=frozenset({"-999"}),
        )
        assert manager.core.calls == []

        assert not await manager.admit_webhook_update(
            {
                "update_id": 64,
                "message": {
                    "message_id": 64,
                    "chat": {"id": -100200, "type": "supergroup"},
                    "from": {"id": 999},
                    "text": "@Penguin_agent_bot unauthorized",
                },
            }
        )
        assert await manager.admit_webhook_update(
            {
                "update_id": 65,
                "message": {
                    "message_id": 65,
                    "chat": {"id": -100200, "type": "supergroup"},
                    "from": {"id": 42},
                    "text": "@Penguin_agent_bot continue",
                },
            }
        )
        await _wait_for(lambda: len(manager.core.calls) == 1)
        assert manager.core.calls[0]["conversation_id"] == "session-group"
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_group_mention_gate_observes_context_without_running_ambient_turns(
    tmp_path: Path,
) -> None:
    bot = FakeBot()
    core = FakeCore()
    manager = TelegramManager(
        core,
        _config(
            group_policy="allowlist",
            allowed_group_ids=frozenset({-100}),
            allowed_group_sender_ids=frozenset({42}),
            activation="mention",
            streaming_mode="off",
        ),
        bot=bot,
        store=ChannelStore(tmp_path / "channel.db"),
    )

    def group_update(update_id: int, text: str) -> dict[str, Any]:
        return {
            "update_id": update_id,
            "message": {
                "message_id": update_id,
                "chat": {"id": -100, "type": "supergroup"},
                "from": {"id": 42, "username": "member"},
                "text": text,
            },
        }

    await manager.start()
    try:
        await manager.admit_webhook_update(group_update(60, "ambient context"))
        await manager.admit_webhook_update(group_update(61, "/status@Other_bot"))
        await _wait_for(
            lambda: all(
                (
                    record := manager.store.get_ingress(
                        f"telegram:867:{update_id}",
                        platform="telegram",
                        account_id="867",
                    )
                )
                is not None
                and record.state == "completed"
                for update_id in (60, 61)
            )
        )
        assert core.calls == []

        await manager.admit_webhook_update(
            group_update(62, "@Penguin_agent_bot answer now")
        )
        await _wait_for(lambda: len(core.calls) == 1)

        assert core.calls[0]["input_data"]["text"] == (
            "[Untrusted recent Telegram group context]\n"
            "member: ambient context\n"
            "[End untrusted Telegram group context]\n\n"
            "answer now"
        )
        assert core.calls[0]["context"]["observed_group_context"] == [
            "member: ambient context"
        ]
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_group_approval_hides_details_and_rejects_wrong_sender(
    tmp_path: Path,
) -> None:
    bot = FakeBot()
    core = ApprovalCore()
    manager = TelegramManager(
        core,
        _config(
            group_policy="allowlist",
            allowed_group_ids=frozenset({-100}),
            allowed_group_sender_ids=frozenset({42, 99}),
            activation="always",
            streaming_mode="off",
            ingress_workers=1,
        ),
        bot=bot,
        store=ChannelStore(tmp_path / "channel.db"),
    )
    original = {
        "update_id": 70,
        "message": {
            "message_id": 70,
            "message_thread_id": 10,
            "chat": {"id": -100, "type": "supergroup"},
            "from": {"id": 42},
            "text": "write it",
        },
    }

    await manager.start()
    try:
        await manager.admit_webhook_update(original)
        await _wait_for(
            lambda: any(
                "Tool approval required" in item["text"] for item in bot.messages
            )
        )
        prompt = next(
            item for item in bot.messages if "Tool approval required" in item["text"]
        )
        assert "notes.txt" not in prompt["text"]
        assert "test approval" not in prompt["text"]
        callback_data = prompt["reply_markup"].inline_keyboard[0][0].callback_data

        def callback_update(update_id: int, sender_id: int) -> dict[str, Any]:
            return {
                "update_id": update_id,
                "callback_query": {
                    "id": f"callback-{update_id}",
                    "from": {"id": sender_id},
                    "data": callback_data,
                    "message": {
                        "message_id": 71,
                        "message_thread_id": 10,
                        "chat": {"id": -100, "type": "supergroup"},
                        "from": {"id": 867},
                    },
                },
            }

        await manager.admit_webhook_update(callback_update(71, 99))
        await asyncio.sleep(0.05)
        assert core.side_effect_count == 0
        assert bot.edits == []

        await manager.admit_webhook_update(callback_update(72, 42))
        await _wait_for(lambda: core.side_effect_count == 1)
        await _wait_for(
            lambda: any(item.get("text") == "<b>Approved</b>" for item in bot.edits)
        )
        terminal = next(
            item for item in bot.edits if item.get("text") == "<b>Approved</b>"
        )
        assert terminal["reply_markup"] is None
        assert bot.callback_answers[0]["text"] == "This action is unavailable."
        assert bot.callback_answers[-1]["text"] == "Recorded."
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_shared_session_projections_use_exact_execution_request(
    tmp_path: Path,
) -> None:
    bot = FakeBot()
    core = SharedSessionProjectionCore()
    store = ChannelStore(tmp_path / "channel.db")
    for user_id in (42, 43):
        store.upsert_binding(
            f"telegram\x1f867\x1f{user_id}\x1f",
            "shared-session",
            directory=str(tmp_path),
            agent_mode="build",
            expected_version=0,
        )
    manager = TelegramManager(
        core,
        _config(
            allow_from=frozenset({42, 43}),
            streaming_mode="off",
            ingress_workers=2,
            delivery_workers=2,
        ),
        bot=bot,
        store=store,
    )

    await manager.start()
    try:
        assert await manager.admit_webhook_update(_update(80, "first"))
        await asyncio.wait_for(core.first_started.wait(), timeout=1.0)
        assert await manager.admit_webhook_update(_update(81, "second", user_id=43))
        await _wait_for(lambda: len(manager._request_targets) == 2)
        core.release_first.set()
        await _wait_for(
            lambda: (
                sum(
                    "Tool approval required" in message.get("text", "")
                    for message in bot.messages
                )
                == 2
            )
        )

        first_prompt = next(
            message
            for message in bot.messages
            if "first.txt" in message.get("text", "")
        )
        second_prompt = next(
            message
            for message in bot.messages
            if "second.txt" in message.get("text", "")
        )
        assert first_prompt["chat_id"] == "42"
        assert second_prompt["chat_id"] == "43"
        await _wait_for(lambda: not manager._request_targets)
        assert manager._session_targets == {}
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_question_text_reply_bypasses_busy_session_lane(tmp_path: Path) -> None:
    bot = FakeBot()
    core = QuestionCore()
    manager = TelegramManager(
        core,
        _config(streaming_mode="off", ingress_workers=1),
        bot=bot,
        store=ChannelStore(tmp_path / "channel.db"),
    )
    await manager.start()
    try:
        await manager.admit_webhook_update(_update(8, "ask me"))
        await _wait_for(
            lambda: any("needs your input" in item["text"] for item in bot.messages)
        )
        await manager.admit_webhook_update(_update(9, "Beta"))
        await _wait_for(lambda: core.answered.is_set())
        await _wait_for(
            lambda: any("answer:Beta" in item.get("text", "") for item in bot.messages)
        )
        await _wait_for(
            lambda: any(item.get("text") == "<b>Answered</b>" for item in bot.edits)
        )
        assert (
            next(item for item in bot.edits if item.get("text") == "<b>Answered</b>")[
                "reply_markup"
            ]
            is None
        )

        assert len(core.calls) == 1
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_multi_question_requires_one_answer_per_line(tmp_path: Path) -> None:
    bot = FakeBot()
    core = MultiQuestionCore()
    manager = TelegramManager(
        core,
        _config(streaming_mode="off", ingress_workers=1),
        bot=bot,
        store=ChannelStore(tmp_path / "channel.db"),
    )
    await manager.start()
    try:
        await manager.admit_webhook_update(_update(86, "ask twice"))
        await _wait_for(
            lambda: any(
                "First answer?" in item.get("text", "")
                and "Second answer?" in item.get("text", "")
                for item in bot.messages
            )
        )
        prompt = next(
            item for item in bot.messages if "First answer?" in item.get("text", "")
        )
        assert "reply_markup" not in prompt

        await manager.admit_webhook_update(_update(87, "only one"))
        await _wait_for(
            lambda: any(
                "one non-empty answer per question" in item.get("text", "")
                for item in bot.messages
            )
        )
        assert not core.answered.is_set()

        await manager.admit_webhook_update(_update(88, "alpha\nbeta"))
        await _wait_for(lambda: core.answered.is_set())
        assert core.answers == [["alpha"], ["beta"]]
        await _wait_for(
            lambda: any(item.get("text") == "<b>Answered</b>" for item in bot.edits)
        )
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_external_approval_resolution_terminalizes_prompt(
    tmp_path: Path,
) -> None:
    bot = FakeBot()
    core = ApprovalCore()
    manager = TelegramManager(
        core,
        _config(streaming_mode="off", ingress_workers=1),
        bot=bot,
        store=ChannelStore(tmp_path / "channel.db"),
    )
    await manager.start()
    try:
        await manager.admit_webhook_update(_update(90, "write it"))
        await asyncio.wait_for(core.request_created.wait(), timeout=1.0)
        await _wait_for(
            lambda: any(
                "Tool approval required" in item.get("text", "")
                for item in bot.messages
            )
        )
        assert core.request_id is not None
        assert get_approval_manager().deny(core.request_id) is not None

        await _wait_for(
            lambda: any(item.get("text") == "<b>Denied</b>" for item in bot.edits)
        )
        terminal = next(
            item for item in bot.edits if item.get("text") == "<b>Denied</b>"
        )
        assert terminal["reply_markup"] is None
        await _wait_for(
            lambda: any(item.get("text") == "denied" for item in bot.messages)
        )
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_restart_terminalizes_orphaned_prompt_before_ttl(
    tmp_path: Path,
) -> None:
    store = ChannelStore(tmp_path / "channel.db")
    now = time.time()
    store.create_callback_with_delivery(
        "orphan",
        account_id="867",
        chat_id="42",
        topic_id=None,
        user_id="42",
        request_id="lost-request",
        payload={
            "kind": "approval",
            "projection_delivery_id": "projection-orphan",
            "lane_key": "telegram\x1f867\x1f42\x1f",
            "platform": "telegram",
            "session_id": "lost-session",
        },
        expires_at=now + 60,
        projection_delivery_id="projection-orphan",
        lane_key="telegram\x1f867\x1f42\x1f",
        delivery_payload={
            "chat_id": "42",
            "topic_id": "",
            "text": "Tool approval required",
            "buttons": [
                [
                    {
                        "text": "Approve once",
                        "data": "penguin:orphan:approve",
                    }
                ]
            ],
        },
        platform="telegram",
        source_session_id="lost-session",
        now=now,
    )
    bot = FakeBot()
    manager = TelegramManager(
        FakeCore(),
        _config(streaming_mode="off", delivery_workers=1),
        bot=bot,
        store=store,
    )

    await manager.start()
    try:
        await _wait_for(lambda: bool(bot.messages) and bool(bot.edits))
        assert bot.messages[0]["text"] == "Tool approval required"
        assert bot.edits[0]["message_id"] == 1
        assert bot.edits[0]["text"] == "<b>Expired</b>"
        assert bot.edits[0]["reply_markup"] is None
        with store._read() as conn:
            state = conn.execute(
                "SELECT state FROM channel_callbacks WHERE callback_id = 'orphan'"
            ).fetchone()[0]
        assert state == "expired"
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_approval_callback_resumes_once_and_duplicate_is_inert(
    tmp_path: Path,
) -> None:
    bot = FakeBot()
    core = ApprovalCore()
    manager = TelegramManager(
        core,
        _config(streaming_mode="off", ingress_workers=2),
        bot=bot,
        store=ChannelStore(tmp_path / "channel.db"),
    )
    await manager.start()
    try:
        await manager.admit_webhook_update(_update(10, "write it"))
        await _wait_for(
            lambda: any(
                "Tool approval required" in item["text"] for item in bot.messages
            )
        )
        prompt = next(
            item for item in bot.messages if "Tool approval required" in item["text"]
        )
        markup = prompt["reply_markup"]
        callback_data = markup.inline_keyboard[0][0].callback_data
        callback_message = {
            "message_id": 50,
            "chat": {"id": 42, "type": "private"},
            "from": {"id": 867, "username": "Penguin_agent_bot"},
        }
        callback_update = {
            "update_id": 11,
            "callback_query": {
                "id": "callback-1",
                "from": {"id": 42},
                "data": callback_data,
                "message": callback_message,
            },
        }
        await manager.admit_webhook_update(callback_update)
        await _wait_for(lambda: core.side_effect_count == 1)
        await _wait_for(
            lambda: any(item.get("text") == "<b>Approved</b>" for item in bot.edits)
        )

        duplicate = dict(callback_update)
        duplicate["update_id"] = 12
        duplicate["callback_query"] = dict(callback_update["callback_query"])
        duplicate["callback_query"]["id"] = "callback-2"
        await manager.admit_webhook_update(duplicate)
        await asyncio.sleep(0.1)

        assert core.side_effect_count == 1
        assert len(core.calls) == 1
        assert sum(item.get("text") == "<b>Approved</b>" for item in bot.edits) == 1
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_group_topic_policy_seeds_and_scopes_execution(
    tmp_path: Path,
) -> None:
    project = tmp_path / "configured-project"
    project.mkdir()
    policy = TelegramBindingPolicy.from_mapping(
        {
            "-100": {
                "activation": "mention",
                "history_limit": 1,
                "prompt": "Answer for the release team.",
                "directory": str(project),
                "agent_id": "configured-agent",
                "mode": "plan",
                "skills": ["ponytail"],
            }
        }
    )
    core = FakeCore()
    store = ChannelStore(tmp_path / "channel.db")
    manager = TelegramManager(
        core,
        _config(
            group_policy="allowlist",
            allowed_group_ids=frozenset({-100}),
            allowed_group_sender_ids=frozenset({42}),
            activation="mention",
            binding_policy=policy,
            streaming_mode="off",
        ),
        bot=FakeBot(),
        store=store,
    )

    def group_update(update_id: int, text: str) -> dict[str, Any]:
        return {
            "update_id": update_id,
            "message": {
                "message_id": update_id,
                "chat": {"id": -100, "type": "supergroup"},
                "from": {"id": 42, "username": "member"},
                "text": text,
            },
        }

    await manager.start()
    try:
        for update_id, text in ((101, "old context"), (102, "recent context")):
            assert await manager.admit_webhook_update(group_update(update_id, text))
            await _wait_for(
                lambda update_id=update_id: (
                    (
                        record := store.get_ingress(
                            f"telegram:867:{update_id}",
                            platform="telegram",
                            account_id="867",
                        )
                    )
                    is not None
                    and record.state == "completed"
                )
            )

        assert await manager.admit_webhook_update(
            group_update(103, "@Penguin_agent_bot ship it")
        )
        await _wait_for(lambda: len(core.calls) == 1)

        binding = store.get_binding("telegram\x1f867\x1f-100\x1f")
        assert binding is not None
        assert binding.directory == str(project.resolve())
        assert binding.agent_id == "configured-agent"
        assert binding.agent_mode == "plan"
        assert binding.settings == {
            "activation": "mention",
            "history_limit": 1,
            "prompt": "Answer for the release team.",
            "skills": ["ponytail"],
        }
        assert "old context" not in core.calls[0]["input_data"]["text"]
        assert "member: recent context" in core.calls[0]["input_data"]["text"]
        execution = core.contexts[0]
        assert execution.directory == str(project.resolve())
        assert execution.agent_mode == "plan"
        assert execution.request_system_prompt == "Answer for the release team."
        assert execution.request_skills == ("ponytail",)
        assert execution.require_registered_agent is True
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_disabled_group_binding_is_rejected_before_durable_admission(
    tmp_path: Path,
) -> None:
    core = FakeCore()
    store = ChannelStore(tmp_path / "channel.db")
    manager = TelegramManager(
        core,
        _config(
            group_policy="allowlist",
            allowed_group_ids=frozenset({-100}),
            allowed_group_sender_ids=frozenset({42}),
            binding_policy=TelegramBindingPolicy.from_mapping(
                {"-100": {"enabled": False}}
            ),
            streaming_mode="off",
        ),
        bot=FakeBot(),
        store=store,
    )
    await manager.start()
    try:
        admitted = await manager.admit_webhook_update(
            {
                "update_id": 104,
                "message": {
                    "message_id": 104,
                    "chat": {"id": -100, "type": "supergroup"},
                    "from": {"id": 42},
                    "text": "@Penguin_agent_bot should not run",
                },
            }
        )
        assert admitted is False
        assert core.calls == []
        assert (
            store.get_ingress("telegram:867:104", platform="telegram", account_id="867")
            is None
        )
    finally:
        await manager.stop()
