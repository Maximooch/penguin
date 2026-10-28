"""Concurrent session writes and narrowly classified Windows sharing failures."""

from __future__ import annotations

import json
import os
import stat
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from penguin.system import atomic_storage
from penguin.system.session_manager import SessionManager
from penguin.system.state import Session


def test_concurrent_same_session_writes_are_complete_and_use_unique_temps(
    tmp_path, monkeypatch
):
    managers = [SessionManager(str(tmp_path), auto_save_interval=0) for _ in range(4)]
    paths = []
    real_replace = atomic_storage.os.replace

    def observe(source, target):
        paths.append(str(source))
        return real_replace(source, target)

    monkeypatch.setattr(atomic_storage.os, "replace", observe)
    stop = threading.Event()
    invalid = []

    def read_continuously():
        while not stop.wait(0.001):
            for path in tmp_path.glob("*.json"):
                try:
                    json.loads(path.read_text(encoding="utf-8"))
                except Exception as error:
                    invalid.append(error)

    reader = threading.Thread(target=read_continuously)
    reader.start()

    def save(index):
        session = Session(
            id="shared", metadata={"revision": index, "payload": str(index) * 2000}
        )
        return managers[index % 4].save_session(session)

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            assert all(pool.map(save, range(32)))
    finally:
        stop.set()
        reader.join(2)
    assert not invalid
    assert len(paths) == len(set(paths))
    for name in ("shared.json", "shared.json.bak"):
        data = json.loads((tmp_path / name).read_text(encoding="utf-8"))
        assert data["metadata"]["payload"] == str(data["metadata"]["revision"]) * 2000
    index = json.loads((tmp_path / "session_index.json").read_text())
    current = json.loads((tmp_path / "shared.json").read_text())
    assert index["shared"]["last_active"] == current["last_active"]
    assert not list(tmp_path.glob("*.tmp"))


def test_separate_managers_keep_peer_index_entries_and_metadata(tmp_path):
    first = SessionManager(str(tmp_path), auto_save_interval=0)
    second = SessionManager(str(tmp_path), auto_save_interval=0)
    one, two = Session(id="one"), Session(id="two")
    assert first.save_session(one)
    assert second.save_session(two)
    one.metadata["title"] = "first changed"
    assert first.save_session(one)
    two.metadata["title"] = "second changed"
    assert second.save_session(two)
    index = json.loads(first.index_path.read_text(encoding="utf-8"))
    assert set(index) == {"one", "two"}
    assert index["one"]["title"] == "first changed"
    assert index["two"]["title"] == "second changed"


def test_concurrent_distinct_sessions_keep_all_index_entries(tmp_path):
    managers = [SessionManager(str(tmp_path), auto_save_interval=0) for _ in range(4)]

    def save(index):
        return managers[index % 4].save_session(Session(id=f"session-{index}"))

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert all(pool.map(save, range(24)))
    index = json.loads((tmp_path / "session_index.json").read_text())
    assert set(index) == {f"session-{i}" for i in range(24)}


def test_serialization_failure_never_changes_existing_files(tmp_path, monkeypatch):
    manager = SessionManager(str(tmp_path), auto_save_interval=0)
    session = manager.create_session()
    assert manager.save_session(session)
    original = {path: path.read_bytes() for path in tmp_path.iterdir()}

    def broken_json():
        raise ValueError("cannot serialize")

    monkeypatch.setattr(session, "to_json", broken_json)
    assert not manager.save_session(session)
    assert {path: path.read_bytes() for path in tmp_path.iterdir()} == original


def test_flush_failure_preserves_target_and_removes_own_temp(tmp_path, monkeypatch):
    target = tmp_path / "target.json"
    target.write_text("old")

    def failed_flush(_fd):
        raise OSError("disk flush failed")

    monkeypatch.setattr(atomic_storage.os, "fsync", failed_flush)
    with pytest.raises(OSError, match="flush"):
        atomic_storage.atomic_write_text(target, "new")
    assert target.read_text() == "old"
    assert not list(tmp_path.glob("*.tmp"))


def test_backup_recovery_restores_complete_session_atomically(tmp_path):
    manager = SessionManager(str(tmp_path), auto_save_interval=0)
    session = manager.create_session()
    session.metadata["revision"] = "old"
    assert manager.save_session(session)
    session.metadata["revision"] = "new"
    assert manager.save_session(session)
    target = tmp_path / f"{session.id}.json"
    backup = target.with_suffix(".json.bak")
    expected = backup.read_bytes()
    target.write_text("{incomplete", encoding="utf-8")
    reloaded = SessionManager(str(tmp_path), auto_save_interval=0)
    recovered = reloaded.load_session(session.id)
    assert recovered.metadata["revision"] == "old"
    assert target.read_bytes() == expected
    assert backup.read_bytes() == expected
    assert not list(tmp_path.glob("*.tmp"))


def test_failed_session_replace_preserves_previous_data_and_marks_dirty(
    tmp_path, monkeypatch
):
    manager = SessionManager(str(tmp_path), auto_save_interval=0)
    session = manager.create_session()
    assert manager.save_session(session)
    target = tmp_path / f"{session.id}.json"
    original = target.read_bytes()
    session.metadata["title"] = "unsaved"
    real_replace = atomic_storage.os.replace

    def denied(source, destination):
        if Path(destination) == target:
            raise PermissionError("real permission denial")
        return real_replace(source, destination)

    monkeypatch.setattr(atomic_storage.os, "replace", denied)
    assert not manager.save_session(session)
    assert target.read_bytes() == original
    assert target.with_suffix(".json.bak").read_bytes() == original
    assert manager.sessions[session.id][1] is True
    assert not list(tmp_path.glob("*.tmp"))


def test_failed_index_save_is_not_reported_as_complete(tmp_path, monkeypatch):
    manager = SessionManager(str(tmp_path), auto_save_interval=0)
    session = manager.create_session()
    assert manager.save_session(session)
    old_index = manager.index_path.read_bytes()
    session.metadata["title"] = "new"
    real_replace = atomic_storage.os.replace

    def denied(source, destination):
        if Path(destination) == manager.index_path:
            raise PermissionError("index denied")
        return real_replace(source, destination)

    monkeypatch.setattr(atomic_storage.os, "replace", denied)
    assert not manager.save_session(session)
    assert manager.index_path.read_bytes() == old_index
    assert manager.sessions[session.id][1] is True
    assert (
        json.loads((tmp_path / f"{session.id}.json").read_text())["metadata"]["title"]
        == "new"
    )
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize(
    "code,shared,attempts",
    [(32, False, 2), (33, False, 2), (5, True, 2), (5, False, 1)],
)
def test_retry_requires_a_confirmed_sharing_failure(
    tmp_path, monkeypatch, code, shared, attempts
):
    real_os = atomic_storage.os
    calls, sleeps = [], []
    error = PermissionError("injected Windows error")
    error.winerror = code

    def replace(source, target):
        calls.append((source, target))
        if len(calls) == 1:
            raise error
        return real_os.replace(source, target)

    monkeypatch.setattr(
        atomic_storage,
        "os",
        SimpleNamespace(name="nt", replace=replace, fsync=real_os.fsync),
    )
    monkeypatch.setattr(
        atomic_storage, "_windows_delete_is_shared", lambda path: shared
    )
    monkeypatch.setattr(atomic_storage.time, "sleep", sleeps.append)
    target = tmp_path / "data.json"
    target.write_text("old")
    if attempts == 1:
        with pytest.raises(PermissionError):
            atomic_storage.atomic_write_text(target, "new")
        assert target.read_text() == "old"
    else:
        atomic_storage.atomic_write_text(target, "new")
        assert target.read_text() == "new"
    assert len(calls) == attempts
    assert len(sleeps) == attempts - 1
    assert not list(tmp_path.glob("*.tmp"))


def test_sharing_retry_exhaustion_is_bounded_and_preserves_target(
    tmp_path, monkeypatch
):
    error = PermissionError("persistent sharing violation")
    error.winerror = 32
    calls, sleeps = [], []

    def blocked(source, target):
        calls.append(source)
        raise error

    monkeypatch.setattr(
        atomic_storage,
        "os",
        SimpleNamespace(name="nt", replace=blocked, fsync=os.fsync),
    )
    monkeypatch.setattr(atomic_storage.time, "sleep", sleeps.append)
    target = tmp_path / "data.json"
    target.write_text("old")
    with pytest.raises(PermissionError):
        atomic_storage.atomic_write_text(target, "new")
    assert len(calls) == 6
    assert sum(sleeps) == pytest.approx(0.31)
    assert target.read_text() == "old"
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.skipif(os.name != "nt", reason="Windows sharing semantics")
def test_windows_open_reader_releases_during_replace_retry(tmp_path, monkeypatch):
    target = tmp_path / "held.json"
    target.write_text("old")
    held = target.open("r")
    attempted = threading.Event()
    real_replace = atomic_storage.os.replace
    errors = []

    def replace(source, destination):
        try:
            return real_replace(source, destination)
        except OSError as error:
            errors.append(error.winerror)
            attempted.set()
            raise

    def release():
        assert attempted.wait(2)
        time.sleep(0.05)
        held.close()

    monkeypatch.setattr(atomic_storage.os, "replace", replace)
    thread = threading.Thread(target=release)
    thread.start()
    try:
        atomic_storage.atomic_write_text(target, "new")
    finally:
        held.close()
        thread.join(2)
    assert errors and errors[0] == 5
    assert target.read_text() == "new"


@pytest.mark.skipif(os.name != "nt", reason="Windows read-only attribute")
def test_windows_read_only_target_is_not_retried_or_changed(tmp_path, monkeypatch):
    target = tmp_path / "readonly.json"
    target.write_text("old")
    target.chmod(stat.S_IREAD)
    calls = []
    real_replace = atomic_storage.os.replace

    def replace(source, destination):
        calls.append(source)
        return real_replace(source, destination)

    monkeypatch.setattr(atomic_storage.os, "replace", replace)
    try:
        with pytest.raises(PermissionError):
            atomic_storage.atomic_write_text(target, "new")
        assert len(calls) == 1
        assert target.read_text() == "old"
    finally:
        target.chmod(stat.S_IWRITE)
