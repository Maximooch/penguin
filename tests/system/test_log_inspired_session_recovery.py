"""Log-inspired persistence and recovery tests for real Penguin sessions.

The fixtures are synthetic and exercise only local files under ``tmp_path``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from penguin.system import session_manager as session_manager_module
from penguin.system.session_manager import SessionManager
from penguin.system.state import MessageCategory, Session, create_message


def _manager(tmp_path: Path) -> SessionManager:
    return SessionManager(base_path=str(tmp_path), auto_save_interval=0)


def _session(session_id: str, *contents: str) -> Session:
    session = Session(id=session_id)
    for content in contents:
        session.add_message(
            create_message(
                role="user",
                content=content,
                category=MessageCategory.DIALOG,
            )
        )
    return session


def _paths(tmp_path: Path, session_id: str) -> tuple[Path, Path, Path]:
    primary = tmp_path / f"{session_id}.json"
    return primary, Path(f"{primary}.bak"), Path(f"{primary}.temp")


def test_truncated_primary_restores_valid_backup_with_actual_messages(
    tmp_path: Path,
) -> None:
    session_id = "session_backup_restore"
    primary, backup, _ = _paths(tmp_path, session_id)
    expected = _session(session_id, "first durable message", "second durable message")
    primary.write_text(
        '{"id": "session_backup_restore", "messages": [', encoding="utf-8"
    )
    backup.write_text(expected.to_json(), encoding="utf-8")

    loaded = _manager(tmp_path).load_session(session_id)

    assert loaded is not None
    assert [message.content for message in loaded.messages] == [
        "first durable message",
        "second durable message",
    ]
    assert json.loads(primary.read_text(encoding="utf-8")) == expected.to_dict()
    assert json.loads(backup.read_text(encoding="utf-8")) == expected.to_dict()


def test_unrecoverable_truncated_primary_creates_notice_without_overwriting_source(
    tmp_path: Path,
) -> None:
    session_id = "session_truncated_only"
    primary, backup, _ = _paths(tmp_path, session_id)
    corrupt_bytes = b'{"id": "session_truncated_only"'
    primary.write_bytes(corrupt_bytes)

    recovered = _manager(tmp_path).load_session(session_id)

    assert recovered is not None
    assert recovered.id.startswith("recovery_")
    assert recovered.metadata["recovered_from"] == session_id
    assert recovered.messages[0].metadata["type"] == "recovery_notice"
    assert primary.read_bytes() == corrupt_bytes
    assert not backup.exists()


def test_malformed_primary_and_backup_are_both_preserved_on_recovery(
    tmp_path: Path,
) -> None:
    session_id = "session_both_corrupt"
    primary, backup, _ = _paths(tmp_path, session_id)
    primary_bytes = b"{not-json-primary"
    backup_bytes = b"{not-json-backup"
    primary.write_bytes(primary_bytes)
    backup.write_bytes(backup_bytes)

    recovered = _manager(tmp_path).load_session(session_id)

    assert recovered is not None
    assert recovered.id.startswith("recovery_")
    assert primary.read_bytes() == primary_bytes
    assert backup.read_bytes() == backup_bytes


def test_unknown_legacy_category_loads_as_dialog_without_losing_message(
    tmp_path: Path,
) -> None:
    session_id = "session_unknown_category"
    primary, _, _ = _paths(tmp_path, session_id)
    payload = _session(session_id, "legacy message").to_dict()
    payload["messages"][0]["category"] = "REMOVED_LEGACY_CATEGORY"
    primary.write_text(json.dumps(payload), encoding="utf-8")

    loaded = _manager(tmp_path).load_session(session_id)

    assert loaded is not None
    assert loaded.id == session_id
    assert [message.content for message in loaded.messages] == ["legacy message"]
    assert loaded.messages[0].category is MessageCategory.DIALOG


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Message.from_dict requires category instead of applying a legacy default; "
        "the observed load shape discards access to otherwise valid messages by "
        "returning a recovery session"
    ),
)
def test_missing_legacy_category_preserves_otherwise_valid_message(
    tmp_path: Path,
) -> None:
    session_id = "session_missing_category"
    primary, _, _ = _paths(tmp_path, session_id)
    payload = _session(session_id, "message from older schema").to_dict()
    payload["messages"][0].pop("category")
    primary.write_text(json.dumps(payload), encoding="utf-8")

    loaded = _manager(tmp_path).load_session(session_id)

    assert loaded is not None
    assert loaded.id == session_id
    assert [message.content for message in loaded.messages] == [
        "message from older schema"
    ]
    assert loaded.messages[0].category is MessageCategory.DIALOG


def test_failed_temp_write_preserves_good_primary_and_backup_then_retry_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "session_temp_write_retry"
    manager = _manager(tmp_path)
    primary, backup, temp = _paths(tmp_path, session_id)
    original = _session(session_id, "durable original")
    previous_backup = _session(session_id, "older backup")
    primary.write_text(original.to_json(), encoding="utf-8")
    backup.write_text(previous_backup.to_json(), encoding="utf-8")
    primary_before = primary.read_bytes()
    backup_before = backup.read_bytes()
    updated = _session(session_id, "durable original", "new message")

    real_write = session_manager_module.atomic_write_text

    def fail_primary_write(target: Path, text: str) -> None:
        if Path(target) == primary:
            raise OSError("synthetic temp write failure")
        real_write(target, text)

    monkeypatch.setattr(session_manager_module, "atomic_write_text", fail_primary_write)
    assert manager.save_session(updated) is False
    assert primary.read_bytes() == primary_before
    # The backup is refreshed before the primary is written, so after a failed
    # primary write it holds the last complete primary, not the older backup.
    assert backup_before != primary_before
    assert backup.read_bytes() == primary_before

    monkeypatch.setattr(session_manager_module, "atomic_write_text", real_write)
    assert manager.save_session(updated) is True
    reloaded = _manager(tmp_path).load_session(session_id)
    assert reloaded is not None
    assert [message.content for message in reloaded.messages] == [
        "durable original",
        "new message",
    ]


def test_failed_primary_replace_preserves_good_primary_and_backup_then_retry_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "session_replace_retry"
    manager = _manager(tmp_path)
    primary, backup, temp = _paths(tmp_path, session_id)
    original = _session(session_id, "durable original")
    primary.write_text(original.to_json(), encoding="utf-8")
    primary_before = primary.read_bytes()
    updated = _session(session_id, "durable original", "new message")
    real_replace = session_manager_module.os.replace

    def fail_primary_replace(source: object, destination: object) -> None:
        if Path(destination) == primary:
            raise OSError("synthetic atomic replace failure")
        real_replace(source, destination)

    monkeypatch.setattr(session_manager_module.os, "replace", fail_primary_replace)
    assert manager.save_session(updated) is False
    assert primary.read_bytes() == primary_before
    assert backup.read_bytes() == primary_before

    monkeypatch.setattr(session_manager_module.os, "replace", real_replace)
    assert manager.save_session(updated) is True
    reloaded = _manager(tmp_path).load_session(session_id)
    assert reloaded is not None
    assert [message.content for message in reloaded.messages] == [
        "durable original",
        "new message",
    ]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "SessionManager._save_index swallows persistence errors, so save_session "
        "reports success even when the durable index was not updated"
    ),
)
def test_index_replace_failure_makes_save_fail_and_retry_updates_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "session_index_retry"
    manager = _manager(tmp_path)
    session = _session(session_id, "message requiring indexed persistence")
    index_temp = Path(f"{manager.index_path}.temp")
    real_replace = session_manager_module.os.replace

    def fail_index_replace(source: object, destination: object) -> None:
        if Path(source) == index_temp and Path(destination) == manager.index_path:
            raise OSError("synthetic index replace failure")
        real_replace(source, destination)

    monkeypatch.setattr(session_manager_module.os, "replace", fail_index_replace)
    assert manager.save_session(session) is False

    monkeypatch.setattr(session_manager_module.os, "replace", real_replace)
    assert manager.save_session(session) is True
    persisted_index = json.loads(manager.index_path.read_text(encoding="utf-8"))
    assert persisted_index[session_id]["message_count"] == 1
