"""A checkpoint id names a checkpoint that exists and holds the state it was taken of.

Covers SM-22: the id was returned before the file was written, an automatic
checkpoint serialised the live session later, workers could start in a
throwaway event loop and never run again, and an unreadable index was replaced
by an empty one on the next save.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from penguin.system.checkpoint_manager import CheckpointManager, CheckpointType
from penguin.system.conversation import ConversationSystem
from penguin.system.state import Message, MessageCategory, Session


def _manager(tmp_path: Path) -> CheckpointManager:
    sessions = SimpleNamespace(
        current_session=None, session_index={}, load_session=lambda _id: None
    )
    return CheckpointManager(tmp_path, sessions)


def _session(*texts: str) -> Session:
    session = Session()
    for text in texts:
        session.add_message(
            Message(role="user", content=text, category=MessageCategory.DIALOG)
        )
    return session


def _stored_session(manager: CheckpointManager, checkpoint_id: str) -> dict[str, Any]:
    path = manager.checkpoints_path / f"{checkpoint_id}.json.gz"
    return json.loads(gzip.decompress(path.read_bytes()))["session"]


async def _wait_for_checkpoints(manager: CheckpointManager, count: int) -> None:
    for _ in range(100):
        if len(manager.checkpoint_index) >= count:
            return
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_a_returned_id_can_be_rolled_back_to_at_once(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session = _session("hello")

    checkpoint_id = await manager.create_checkpoint(
        session, session.messages[-1], CheckpointType.MANUAL, name="before"
    )

    assert checkpoint_id is not None
    assert (manager.checkpoints_path / f"{checkpoint_id}.json.gz").exists()
    assert await manager.rollback_to_checkpoint(checkpoint_id) is True


@pytest.mark.asyncio
async def test_an_automatic_checkpoint_holds_the_conversation_as_it_was(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    conversation = ConversationSystem(checkpoint_manager=manager)

    first = conversation.add_message("user", "first", MessageCategory.DIALOG)
    conversation.add_message("assistant", "second", MessageCategory.DIALOG)
    await _wait_for_checkpoints(manager, 2)

    by_trigger = {
        metadata.message_id: checkpoint_id
        for checkpoint_id, metadata in manager.checkpoint_index.items()
    }
    stored = _stored_session(manager, by_trigger[first.id])
    assert [message["content"] for message in stored["messages"]] == ["first"]
    assert manager.checkpoint_index[by_trigger[first.id]].message_count == 1


def test_automatic_checkpoints_are_written_without_an_event_loop(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    conversation = ConversationSystem(checkpoint_manager=manager)

    conversation.add_message("user", "first", MessageCategory.DIALOG)
    conversation.add_message("assistant", "second", MessageCategory.DIALOG)

    assert len(manager.checkpoint_index) == 2
    for checkpoint_id in manager.checkpoint_index:
        assert (manager.checkpoints_path / f"{checkpoint_id}.json.gz").exists()


def test_checkpoints_work_from_successive_event_loops(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session = _session("hello")

    ids = [
        asyncio.run(manager.create_checkpoint(session, session.messages[-1]))
        for _ in range(2)
    ]

    for checkpoint_id in ids:
        assert checkpoint_id in manager.checkpoint_index
        assert (manager.checkpoints_path / f"{checkpoint_id}.json.gz").exists()


@pytest.mark.asyncio
@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
async def test_a_failed_write_returns_no_id(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session = _session("hello")
    manager.checkpoints_path.chmod(0o500)
    try:
        failed = await manager.create_checkpoint(session, session.messages[-1])
    finally:
        manager.checkpoints_path.chmod(0o700)

    later = await manager.create_checkpoint(session, session.messages[-1])

    assert failed is None
    assert later is not None
    assert list(manager.checkpoint_index) == [later]


def _write_checkpoint_file(directory: Path, checkpoint_id: str) -> None:
    data = {
        "metadata": {
            "id": checkpoint_id,
            "type": "manual",
            "created_at": "2026-11-14T10:00:00",
            "session_id": "session_a",
            "message_id": "msg_a",
            "message_count": 1,
            "name": "kept",
            "description": None,
            "parent_checkpoint": None,
            "branch_point": None,
            "auto": False,
        },
        "session": _session("hello").to_dict(),
    }
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{checkpoint_id}.json.gz").write_bytes(
        gzip.compress(json.dumps(data).encode("utf-8"))
    )


def test_an_unreadable_index_is_rebuilt_from_checkpoint_files(tmp_path: Path) -> None:
    checkpoints = tmp_path / "checkpoints"
    _write_checkpoint_file(checkpoints, "cp_kept")
    (checkpoints / "checkpoint_index.json").write_text("{not json")

    manager = _manager(tmp_path)

    assert [entry["id"] for entry in manager.list_checkpoints()] == ["cp_kept"]
    assert (checkpoints / "checkpoint_index.json.corrupt").read_text() == "{not json"


def test_one_bad_index_entry_does_not_drop_the_others(tmp_path: Path) -> None:
    checkpoints = tmp_path / "checkpoints"
    checkpoints.mkdir()
    good = {
        "id": "cp_good",
        "type": "manual",
        "created_at": "2026-11-14T10:00:00",
        "session_id": "session_a",
        "message_id": "msg_a",
        "message_count": 1,
    }
    (checkpoints / "checkpoint_index.json").write_text(
        json.dumps({"cp_good": good, "cp_bad": {**good, "type": "nonsense"}})
    )

    manager = _manager(tmp_path)

    assert list(manager.checkpoint_index) == ["cp_good"]
