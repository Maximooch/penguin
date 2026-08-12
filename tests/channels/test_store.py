from __future__ import annotations

import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from hypothesis import settings
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from penguin.channels.store import (
    ChannelStore,
    CompareAndSwapError,
    IdempotencyConflictError,
    LeaseLostError,
    PayloadTooLargeError,
    PollerLeaseConflictError,
)

PLATFORM = "telegram"
ACCOUNT = "default"


@pytest.fixture
def store(tmp_path: Path) -> ChannelStore:
    return ChannelStore(tmp_path / "channels.db")


def _admit(store: ChannelStore, event_id: str, lane: str, now: float) -> None:
    assert store.admit_ingress(
        event_id,
        lane,
        {"event": event_id},
        platform=PLATFORM,
        account_id=ACCOUNT,
        now=now,
    )


def _claim_and_start(
    store: ChannelStore, event_id: str, owner: str, now: float
) -> None:
    claimed = store.claim_ingress(
        platform=PLATFORM,
        account_id=ACCOUNT,
        owner_id=owner,
        lease_seconds=10,
        now=now,
    )
    assert claimed is not None
    assert claimed.event_id == event_id
    store.start_ingress(
        event_id,
        platform=PLATFORM,
        account_id=ACCOUNT,
        owner_id=owner,
        now=now,
    )


def test_database_uses_durable_pragmas_and_foreign_keys(
    store: ChannelStore,
) -> None:
    with store._read() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30_000

    with pytest.raises(sqlite3.IntegrityError):
        store.enqueue_delivery(
            "delivery-1",
            "key-1",
            "lane-1",
            {"text": "answer"},
            platform=PLATFORM,
            account_id=ACCOUNT,
            source_event_id="missing-event",
            now=1,
        )


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes only")
def test_database_file_is_private(store: ChannelStore) -> None:
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes only")
def test_database_and_sidecars_are_private_under_permissive_umask(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "public-parent"
    parent.mkdir(mode=0o755)
    parent.chmod(0o755)
    script = """
import os
import stat
import sys
from pathlib import Path
from penguin.channels.store import ChannelStore

os.umask(0)
path = Path(sys.argv[1])
store = ChannelStore(path)
with store._write() as connection:
    connection.execute("CREATE TABLE mode_probe (id INTEGER)")
    paths = (path, Path(str(path) + "-wal"), Path(str(path) + "-shm"))
    assert all(item.exists() for item in paths)
    assert all(stat.S_IMODE(item.stat().st_mode) == 0o600 for item in paths)
"""

    subprocess.run(
        [sys.executable, "-c", script, str(parent / "channels.db")],
        check=True,
        cwd=Path(__file__).parents[2],
    )


def test_payloads_and_error_messages_are_bounded(tmp_path: Path) -> None:
    bounded = ChannelStore(
        tmp_path / "bounded.db", max_payload_bytes=24, max_error_chars=8
    )
    with pytest.raises(PayloadTooLargeError):
        bounded.admit_ingress(
            "event",
            "lane",
            {"text": "x" * 30},
            platform=PLATFORM,
            account_id=ACCOUNT,
        )

    assert bounded.admit_ingress(
        "event", "lane", {"ok": True}, platform=PLATFORM, account_id=ACCOUNT
    )
    claimed = bounded.claim_ingress(
        platform=PLATFORM,
        account_id=ACCOUNT,
        owner_id="worker",
        lease_seconds=10,
    )
    assert claimed is not None
    bounded.dead_letter_ingress(
        "event",
        platform=PLATFORM,
        account_id=ACCOUNT,
        owner_id="worker",
        error_class="TransportError",
        error_message="0123456789abcdef",
    )
    record = bounded.get_ingress("event", platform=PLATFORM, account_id=ACCOUNT)
    assert record is not None
    assert record.last_error_message == "01234567"


def test_binding_replacement_supports_version_cas(store: ChannelStore) -> None:
    first = store.upsert_binding(
        "telegram/default/dm/7",
        "session-1",
        settings={
            "prompt": "Be terse",
            "skills": ["review"],
            "activation": "mention",
        },
        expected_version=0,
        now=1,
    )
    assert first.version == 1
    assert first.settings["prompt"] == "Be terse"

    second = store.upsert_binding(
        first.address_key,
        "session-2",
        directory="/workspace",
        expected_version=first.version,
        now=2,
    )
    assert second.version == 2
    assert second.session_id == "session-2"
    assert second.directory == "/workspace"
    assert second.settings == first.settings

    with pytest.raises(CompareAndSwapError):
        store.upsert_binding(
            first.address_key,
            "stale-session",
            expected_version=first.version,
            now=3,
        )
    assert store.get_binding(first.address_key) == second


def test_supergroup_migration_moves_group_and_topics_atomically(
    store: ChannelStore,
) -> None:
    separator = "\x1f"
    old = separator.join((PLATFORM, ACCOUNT, "-100-old"))
    new = separator.join((PLATFORM, ACCOUNT, "-100-new"))
    topic = old + separator + "42"
    store.upsert_binding(old, "group-session", settings={"prompt": "group"}, now=1)
    store.upsert_binding(topic, "topic-session", settings={"skills": ["tdd"]}, now=1)
    store.upsert_binding("unrelated", "dm-session", now=1)

    versions = {
        old: store.get_binding(old).version,
        topic: store.get_binding(topic).version,
    }
    migrated = store.migrate_binding_prefix(old, new, expected_versions=versions, now=2)
    assert [record.address_key for record in migrated] == [
        new,
        new + separator + "42",
    ]
    assert [record.session_id for record in migrated] == [
        "group-session",
        "topic-session",
    ]
    assert migrated[0].settings == {"prompt": "group"}
    assert migrated[1].settings == {"skills": ["tdd"]}
    assert store.get_binding(old) is None
    assert store.get_binding(topic) is None
    assert store.get_binding("unrelated") is not None

    collision_old = separator.join((PLATFORM, ACCOUNT, "-100-collision-old"))
    collision_new = separator.join((PLATFORM, ACCOUNT, "-100-collision-new"))
    store.upsert_binding(collision_old, "source-session", now=3)
    store.upsert_binding(collision_new, "destination-session", now=3)
    with pytest.raises(CompareAndSwapError):
        store.migrate_binding_prefix(collision_old, collision_new, now=4)
    assert store.get_binding(collision_old).session_id == "source-session"
    assert store.get_binding(collision_new).session_id == "destination-session"


def test_group_migration_lineage_requires_a_current_allowed_source(
    store: ChannelStore,
) -> None:
    separator = "\x1f"
    first = separator.join((PLATFORM, ACCOUNT, "-100"))
    second = separator.join((PLATFORM, ACCOUNT, "-200"))
    third = separator.join((PLATFORM, ACCOUNT, "-300"))
    store.migrate_binding_prefix(
        first,
        second,
        group_authorization=(PLATFORM, ACCOUNT, "-100", "-200"),
        now=1,
    )
    store.migrate_binding_prefix(
        second,
        third,
        group_authorization=(PLATFORM, ACCOUNT, "-200", "-300"),
        now=2,
    )

    assert store.is_group_authorized(
        platform=PLATFORM,
        account_id=ACCOUNT,
        chat_id="-300",
        allowed_source_chat_ids=frozenset({"-100"}),
    )
    assert not store.is_group_authorized(
        platform=PLATFORM,
        account_id=ACCOUNT,
        chat_id="-300",
        allowed_source_chat_ids=frozenset({"-999"}),
    )


def test_pairing_is_hashed_dm_only_single_use_and_revocable(
    store: ChannelStore,
) -> None:
    code = "Penguin-123456"
    pairing = store.create_pairing(
        code,
        account_id=ACCOUNT,
        expected_user_id="7",
        expires_at=100,
        now=1,
    )
    assert pairing.code_hash != code
    assert store.can_consume_pairing(
        code,
        account_id=ACCOUNT,
        user_id="7",
        chat_id="7",
        now=2,
    )
    assert not store.can_consume_pairing(
        code,
        account_id=ACCOUNT,
        user_id="8",
        chat_id="8",
        now=2,
    )

    with sqlite3.connect(store.path) as conn:
        persisted = conn.execute(
            """
            SELECT code_hash, account_id, expected_user_id, state
            FROM channel_pairings
            """
        ).fetchone()
    assert persisted is not None
    assert code not in "|".join(str(value) for value in persisted)

    assert (
        store.consume_pairing(
            code,
            account_id=ACCOUNT,
            user_id="7",
            chat_id="group-9",
            now=2,
        )
        is None
    )
    assert (
        store.consume_pairing(
            code,
            account_id=ACCOUNT,
            user_id="8",
            chat_id="8",
            now=2,
        )
        is None
    )

    consumed = store.consume_pairing(
        code, account_id=ACCOUNT, user_id="7", chat_id="7", now=2
    )
    assert consumed is not None
    assert consumed.state == "consumed"
    assert not store.can_consume_pairing(
        code,
        account_id=ACCOUNT,
        user_id="7",
        chat_id="7",
        now=3,
    )
    assert store.is_dm_authorized(account_id=ACCOUNT, user_id="7")
    assert (
        store.consume_pairing(
            code,
            account_id=ACCOUNT,
            user_id="7",
            chat_id="7",
            now=3,
        )
        is None
    )

    assert store.revoke_dm_authorization(account_id=ACCOUNT, user_id="7", now=4)
    assert not store.is_dm_authorized(account_id=ACCOUNT, user_id="7")

    store.create_pairing("revoke-me", account_id=ACCOUNT, expires_at=100, now=1)
    assert store.revoke_pairing("revoke-me", account_id=ACCOUNT, now=2)
    assert (
        store.consume_pairing(
            "revoke-me",
            account_id=ACCOUNT,
            user_id="9",
            chat_id="9",
            now=3,
        )
        is None
    )


def test_expired_pairing_cannot_authorize(store: ChannelStore) -> None:
    store.create_pairing("expires", account_id=ACCOUNT, expires_at=10, now=1)
    assert (
        store.consume_pairing(
            "expires",
            account_id=ACCOUNT,
            user_id="7",
            chat_id="7",
            now=10,
        )
        is None
    )
    assert not store.is_dm_authorized(account_id=ACCOUNT, user_id="7")


def test_callback_claim_checks_full_recipient_scope_and_is_single_use(
    store: ChannelStore,
) -> None:
    store.create_callback(
        "callback-1",
        account_id=ACCOUNT,
        chat_id="chat-1",
        topic_id="topic-1",
        user_id="user-1",
        request_id="request-1",
        tool_call_id="tool-1",
        payload={"choice": "approve"},
        expires_at=100,
        now=1,
    )

    wrong_scopes = [
        {
            "account_id": "other",
            "chat_id": "chat-1",
            "topic_id": "topic-1",
            "user_id": "user-1",
        },
        {
            "account_id": ACCOUNT,
            "chat_id": "other",
            "topic_id": "topic-1",
            "user_id": "user-1",
        },
        {
            "account_id": ACCOUNT,
            "chat_id": "chat-1",
            "topic_id": "other",
            "user_id": "user-1",
        },
        {
            "account_id": ACCOUNT,
            "chat_id": "chat-1",
            "topic_id": "topic-1",
            "user_id": "other",
        },
    ]
    for scope in wrong_scopes:
        assert (
            store.claim_callback("callback-1", owner_id="worker", now=2, **scope)
            is None
        )

    claimed = store.claim_callback(
        "callback-1",
        account_id=ACCOUNT,
        chat_id="chat-1",
        topic_id="topic-1",
        user_id="user-1",
        owner_id="worker-1",
        now=2,
    )
    assert claimed is not None
    assert claimed.request_id == "request-1"
    assert claimed.tool_call_id == "tool-1"
    assert claimed.payload == {"choice": "approve"}
    assert (
        store.claim_callback(
            "callback-1",
            account_id=ACCOUNT,
            chat_id="chat-1",
            topic_id="topic-1",
            user_id="user-1",
            owner_id="worker-2",
            now=2,
        )
        is None
    )
    with pytest.raises(LeaseLostError):
        store.complete_callback("callback-1", owner_id="worker-2", now=3)
    store.complete_callback("callback-1", owner_id="worker-1", now=3)


def test_callback_claim_is_atomic_across_workers(store: ChannelStore) -> None:
    store.create_callback(
        "callback-race",
        account_id=ACCOUNT,
        chat_id="7",
        topic_id=None,
        user_id="7",
        request_id="request",
        payload={"answer": "yes"},
        expires_at=100,
        now=1,
    )

    def claim(owner: str) -> bool:
        return (
            store.claim_callback(
                "callback-race",
                account_id=ACCOUNT,
                chat_id="7",
                topic_id=None,
                user_id="7",
                owner_id=owner,
                now=2,
            )
            is not None
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, ["worker-1", "worker-2"]))
    assert sorted(results) == [False, True]


def test_callback_lease_renewal_uses_owner_and_account_cas(
    store: ChannelStore,
) -> None:
    store.create_callback(
        "callback-renew",
        account_id=ACCOUNT,
        chat_id="7",
        topic_id=None,
        user_id="7",
        request_id="request",
        payload={"answer": "yes"},
        expires_at=100,
        now=1,
    )
    assert store.claim_callback(
        "callback-renew",
        account_id=ACCOUNT,
        chat_id="7",
        topic_id=None,
        user_id="7",
        owner_id="worker",
        lease_seconds=2,
        now=2,
    )
    assert store.renew_callback_lease(
        "callback-renew",
        platform=PLATFORM,
        account_id=ACCOUNT,
        owner_id="worker",
        lease_seconds=2,
        now=3,
    )
    assert not store.renew_callback_lease(
        "callback-renew",
        platform=PLATFORM,
        account_id="other",
        owner_id="worker",
        lease_seconds=2,
        now=3,
    )
    assert not store.renew_callback_lease(
        "callback-renew",
        platform=PLATFORM,
        account_id=ACCOUNT,
        owner_id="other",
        lease_seconds=2,
        now=3,
    )
    assert (
        store.recover_expired_callbacks(
            platform=PLATFORM,
            account_id=ACCOUNT,
            now=4.5,
        )
        == []
    )
    recovered = store.recover_expired_callbacks(
        platform=PLATFORM,
        account_id=ACCOUNT,
        now=5,
    )
    assert [record.state for record in recovered] == ["dead"]
    assert not store.renew_callback_lease(
        "callback-renew",
        platform=PLATFORM,
        account_id=ACCOUNT,
        owner_id="worker",
        lease_seconds=2,
        now=5,
    )


def test_callback_recovery_terminalizes_expired_and_dead_once(
    store: ChannelStore,
) -> None:
    def create(callback_id: str, expires_at: float) -> None:
        projection_id = f"projection-{callback_id}"
        store.create_callback_with_delivery(
            callback_id,
            account_id=ACCOUNT,
            chat_id="7",
            topic_id=None,
            user_id="7",
            request_id=f"request-{callback_id}",
            payload={
                "kind": "approval",
                "projection_delivery_id": projection_id,
                "lane_key": "lane",
                "platform": PLATFORM,
                "session_id": "session",
            },
            expires_at=expires_at,
            projection_delivery_id=projection_id,
            lane_key="lane",
            delivery_payload={"chat_id": "7", "text": "Approve?"},
            platform=PLATFORM,
            source_session_id="session",
            now=1,
        )

    create("expired", 3)
    create("dead", 100)
    assert store.claim_callback(
        "dead",
        account_id=ACCOUNT,
        chat_id="7",
        topic_id=None,
        user_id="7",
        owner_id="worker",
        lease_seconds=1,
        now=2,
    )

    recovered = store.recover_expired_callbacks(
        platform=PLATFORM,
        account_id=ACCOUNT,
        now=4,
    )
    assert {record.callback_id: record.state for record in recovered} == {
        "dead": "dead",
        "expired": "expired",
    }
    assert (
        store.recover_expired_callbacks(
            platform=PLATFORM,
            account_id=ACCOUNT,
            now=5,
        )
        == []
    )
    for callback_id in ("expired", "dead"):
        projection = store.get_delivery(
            f"projection-{callback_id}",
            platform=PLATFORM,
            account_id=ACCOUNT,
        )
        terminal = store.get_delivery(
            f"telegram:callback-terminal:{callback_id}",
            platform=PLATFORM,
            account_id=ACCOUNT,
        )
        assert projection is not None
        assert terminal is not None
        assert terminal.sequence > projection.sequence
        assert terminal.kind == "callback_terminal"
        assert terminal.payload["label"] == "Expired"


def test_orphan_recovery_preserves_pending_control_callbacks(
    store: ChannelStore,
) -> None:
    for callback_id, kind in (("approval", "approval"), ("control", "control")):
        store.create_callback(
            callback_id,
            account_id=ACCOUNT,
            chat_id="7",
            topic_id=None,
            user_id="7",
            request_id=f"request-{callback_id}",
            payload={"kind": kind},
            expires_at=100,
            now=1,
        )

    recovered = store.recover_orphaned_callbacks(
        platform=PLATFORM,
        account_id=ACCOUNT,
        now=2,
    )

    assert [record.callback_id for record in recovered] == ["approval"]
    assert (
        store.claim_callback(
            "approval",
            account_id=ACCOUNT,
            chat_id="7",
            topic_id=None,
            user_id="7",
            owner_id="worker",
            now=3,
        )
        is None
    )
    assert (
        store.claim_callback(
            "control",
            account_id=ACCOUNT,
            chat_id="7",
            topic_id=None,
            user_id="7",
            owner_id="worker",
            now=3,
        )
        is not None
    )


def test_ingress_deduplicates_and_rejects_conflicting_reuse(
    store: ChannelStore,
) -> None:
    _admit(store, "event-1", "lane-1", 1)
    assert not store.admit_ingress(
        "event-1",
        "lane-1",
        {"event": "event-1"},
        platform=PLATFORM,
        account_id=ACCOUNT,
        now=2,
    )
    with pytest.raises(IdempotencyConflictError):
        store.admit_ingress(
            "event-1",
            "lane-1",
            {"event": "different"},
            platform=PLATFORM,
            account_id=ACCOUNT,
            now=2,
        )


def test_ingress_claims_preserve_lane_order_without_blocking_other_lanes(
    store: ChannelStore,
) -> None:
    _admit(store, "lane-a-1", "lane-a", 1)
    _admit(store, "lane-a-2", "lane-a", 2)
    _admit(store, "lane-b-1", "lane-b", 3)

    first = store.claim_ingress(
        platform=PLATFORM,
        account_id=ACCOUNT,
        owner_id="worker-1",
        lease_seconds=20,
        now=4,
    )
    independent = store.claim_ingress(
        platform=PLATFORM,
        account_id=ACCOUNT,
        owner_id="worker-2",
        lease_seconds=20,
        now=4,
    )
    assert first is not None and first.event_id == "lane-a-1"
    assert independent is not None and independent.event_id == "lane-b-1"
    assert (
        store.claim_ingress(
            platform=PLATFORM,
            account_id=ACCOUNT,
            owner_id="worker-3",
            lease_seconds=20,
            now=4,
        )
        is None
    )

    store.start_ingress(
        first.event_id,
        platform=PLATFORM,
        account_id=ACCOUNT,
        owner_id="worker-1",
        now=5,
    )
    store.complete_ingress(
        first.event_id,
        platform=PLATFORM,
        account_id=ACCOUNT,
        owner_id="worker-1",
        now=6,
    )
    second = store.claim_ingress(
        platform=PLATFORM,
        account_id=ACCOUNT,
        owner_id="worker-3",
        lease_seconds=20,
        now=7,
    )
    assert second is not None and second.event_id == "lane-a-2"


def test_ingress_claim_filters_reserve_interactive_capacity(
    store: ChannelStore,
) -> None:
    suffix = "\x1finteractive"
    _admit(store, "normal", "chat", 1)
    _admit(store, "interactive", f"chat{suffix}", 2)

    control = store.claim_ingress(
        platform=PLATFORM,
        account_id=ACCOUNT,
        owner_id="control-worker",
        lease_seconds=10,
        lane_suffix=suffix,
        now=3,
    )
    normal = store.claim_ingress(
        platform=PLATFORM,
        account_id=ACCOUNT,
        owner_id="normal-worker",
        lease_seconds=10,
        exclude_lane_suffix=suffix,
        now=3,
    )

    assert control is not None and control.event_id == "interactive"
    assert normal is not None and normal.event_id == "normal"


def test_ingress_claim_is_atomic_across_workers(store: ChannelStore) -> None:
    _admit(store, "event", "lane", 1)

    def claim(owner: str) -> str | None:
        record = store.claim_ingress(
            platform=PLATFORM,
            account_id=ACCOUNT,
            owner_id=owner,
            lease_seconds=10,
            now=2,
        )
        return record.event_id if record is not None else None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, ["worker-1", "worker-2"]))
    assert results.count("event") == 1
    assert results.count(None) == 1


def test_ingress_recovery_retries_unstarted_and_dead_letters_started(
    store: ChannelStore,
) -> None:
    _admit(store, "unstarted", "lane-a", 1)
    _admit(store, "started", "lane-b", 2)
    first = store.claim_ingress(
        platform=PLATFORM,
        account_id=ACCOUNT,
        owner_id="worker-1",
        lease_seconds=5,
        now=3,
    )
    second = store.claim_ingress(
        platform=PLATFORM,
        account_id=ACCOUNT,
        owner_id="worker-2",
        lease_seconds=5,
        now=3,
    )
    assert first is not None and first.event_id == "unstarted"
    assert second is not None and second.event_id == "started"
    store.start_ingress(
        "started",
        platform=PLATFORM,
        account_id=ACCOUNT,
        owner_id="worker-2",
        now=4,
    )

    recovered = store.recover_expired_ingress(now=8)
    assert recovered.retried == 1
    assert recovered.dead == 1
    safe = store.get_ingress("unstarted", platform=PLATFORM, account_id=ACCOUNT)
    uncertain = store.get_ingress("started", platform=PLATFORM, account_id=ACCOUNT)
    assert safe is not None and safe.state == "retry"
    assert uncertain is not None and uncertain.state == "dead"
    assert uncertain.last_error_class == "execution_uncertain"


def test_ingress_dead_letter_operator_controls_are_bounded_and_terminal_only(
    store: ChannelStore,
) -> None:
    for index, event_id in enumerate(("dead-1", "dead-2", "completed", "live")):
        _admit(store, event_id, f"lane-{event_id}", index + 1)

    for index, event_id in enumerate(("dead-1", "dead-2")):
        claimed = store.claim_ingress(
            platform=PLATFORM,
            account_id=ACCOUNT,
            owner_id=f"worker-{index}",
            lease_seconds=10,
            now=5,
        )
        assert claimed is not None and claimed.event_id == event_id
        store.dead_letter_ingress(
            event_id,
            platform=PLATFORM,
            account_id=ACCOUNT,
            owner_id=f"worker-{index}",
            error_class="Rejected",
            error_message="terminal",
            now=6,
        )

    _claim_and_start(store, "completed", "worker-completed", 7)
    store.complete_ingress(
        "completed",
        platform=PLATFORM,
        account_id=ACCOUNT,
        owner_id="worker-completed",
        now=8,
    )

    assert [
        item.event_id
        for item in store.list_dead_ingress(
            platform=PLATFORM, account_id=ACCOUNT, limit=1
        )
    ] == ["dead-1"]
    for invalid_limit in (0, 101, True):
        with pytest.raises(ValueError):
            store.list_dead_ingress(
                platform=PLATFORM,
                account_id=ACCOUNT,
                limit=invalid_limit,
            )

    assert not store.discard_dead_ingress(
        "completed", platform=PLATFORM, account_id=ACCOUNT
    )
    assert not store.discard_dead_ingress("live", platform=PLATFORM, account_id=ACCOUNT)
    assert store.discard_dead_ingress("dead-1", platform=PLATFORM, account_id=ACCOUNT)
    assert store.get_ingress("dead-1", platform=PLATFORM, account_id=ACCOUNT) is None
    assert store.requeue_dead_ingress(
        "dead-2", platform=PLATFORM, account_id=ACCOUNT, now=9
    )
    retried = store.get_ingress("dead-2", platform=PLATFORM, account_id=ACCOUNT)
    assert retried is not None and retried.state == "retry"


def test_delivery_enqueue_is_idempotent_and_lane_ordered(
    store: ChannelStore,
) -> None:
    for delivery_id, lane in [
        ("lane-a-1", "lane-a"),
        ("lane-a-2", "lane-a"),
        ("lane-b-1", "lane-b"),
    ]:
        assert store.enqueue_delivery(
            delivery_id,
            f"key-{delivery_id}",
            lane,
            {"text": delivery_id},
            platform=PLATFORM,
            account_id=ACCOUNT,
            now=1,
        )
    assert not store.enqueue_delivery(
        "lane-a-1",
        "key-lane-a-1",
        "lane-a",
        {"text": "lane-a-1"},
        platform=PLATFORM,
        account_id=ACCOUNT,
        now=2,
    )
    with pytest.raises(IdempotencyConflictError):
        store.enqueue_delivery(
            "lane-a-1",
            "key-lane-a-1",
            "lane-a",
            {"text": "different"},
            platform=PLATFORM,
            account_id=ACCOUNT,
            now=2,
        )

    first = store.claim_delivery(
        platform=PLATFORM,
        account_id=ACCOUNT,
        owner_id="worker-1",
        lease_seconds=10,
        now=3,
    )
    assert first is not None and first.delivery_id == "lane-a-1"
    store.retry_delivery(
        first.delivery_id,
        platform=PLATFORM,
        account_id=ACCOUNT,
        owner_id="worker-1",
        retry_at=100,
        error_class="RateLimit",
        error_message="later",
        now=4,
    )

    independent = store.claim_delivery(
        platform=PLATFORM,
        account_id=ACCOUNT,
        owner_id="worker-2",
        lease_seconds=10,
        now=5,
    )
    assert independent is not None and independent.delivery_id == "lane-b-1"
    store.complete_delivery(
        independent.delivery_id,
        platform=PLATFORM,
        account_id=ACCOUNT,
        owner_id="worker-2",
        external_message_id="telegram-42",
        now=6,
    )
    assert (
        store.claim_delivery(
            platform=PLATFORM,
            account_id=ACCOUNT,
            owner_id="worker-3",
            lease_seconds=10,
            now=7,
        )
        is None
    )

    retried = store.claim_delivery(
        platform=PLATFORM,
        account_id=ACCOUNT,
        owner_id="worker-3",
        lease_seconds=10,
        now=100,
    )
    assert retried is not None and retried.delivery_id == "lane-a-1"
    store.complete_delivery(
        retried.delivery_id,
        platform=PLATFORM,
        account_id=ACCOUNT,
        owner_id="worker-3",
        now=101,
    )
    second = store.claim_delivery(
        platform=PLATFORM,
        account_id=ACCOUNT,
        owner_id="worker-4",
        lease_seconds=10,
        now=102,
    )
    assert second is not None and second.delivery_id == "lane-a-2"


def test_expired_delivery_claim_is_recovered_for_retry(store: ChannelStore) -> None:
    store.enqueue_delivery(
        "delivery",
        "key",
        "lane",
        {"text": "hello"},
        platform=PLATFORM,
        account_id=ACCOUNT,
        now=1,
    )
    claimed = store.claim_delivery(
        platform=PLATFORM,
        account_id=ACCOUNT,
        owner_id="worker",
        lease_seconds=5,
        now=2,
    )
    assert claimed is not None
    assert store.recover_expired_deliveries(now=7) == 1
    record = store.get_delivery("delivery", platform=PLATFORM, account_id=ACCOUNT)
    assert record is not None and record.state == "retry"


def test_delivery_dead_letter_operator_controls_are_bounded_and_terminal_only(
    store: ChannelStore,
) -> None:
    for delivery_id in ("dead-1", "dead-2", "delivered", "live"):
        store.enqueue_delivery(
            delivery_id,
            f"key-{delivery_id}",
            f"lane-{delivery_id}",
            {"text": delivery_id},
            platform=PLATFORM,
            account_id=ACCOUNT,
            now=1,
        )

    for index, delivery_id in enumerate(("dead-1", "dead-2")):
        claimed = store.claim_delivery(
            platform=PLATFORM,
            account_id=ACCOUNT,
            owner_id=f"worker-{index}",
            lease_seconds=10,
            now=2,
        )
        assert claimed is not None and claimed.delivery_id == delivery_id
        store.dead_letter_delivery(
            delivery_id,
            platform=PLATFORM,
            account_id=ACCOUNT,
            owner_id=f"worker-{index}",
            error_class="Forbidden",
            error_message="terminal",
            now=3,
        )

    delivered = store.claim_delivery(
        platform=PLATFORM,
        account_id=ACCOUNT,
        owner_id="worker-delivered",
        lease_seconds=10,
        now=4,
    )
    assert delivered is not None and delivered.delivery_id == "delivered"
    store.complete_delivery(
        "delivered",
        platform=PLATFORM,
        account_id=ACCOUNT,
        owner_id="worker-delivered",
        now=5,
    )

    assert [
        item.delivery_id
        for item in store.list_dead_deliveries(
            platform=PLATFORM, account_id=ACCOUNT, limit=1
        )
    ] == ["dead-1"]
    for invalid_limit in (0, 101, True):
        with pytest.raises(ValueError):
            store.list_dead_deliveries(
                platform=PLATFORM,
                account_id=ACCOUNT,
                limit=invalid_limit,
            )

    assert not store.discard_dead_delivery(
        "delivered", platform=PLATFORM, account_id=ACCOUNT
    )
    assert not store.discard_dead_delivery(
        "live", platform=PLATFORM, account_id=ACCOUNT
    )
    assert store.discard_dead_delivery("dead-1", platform=PLATFORM, account_id=ACCOUNT)
    assert store.get_delivery("dead-1", platform=PLATFORM, account_id=ACCOUNT) is None
    assert store.requeue_dead_delivery(
        "dead-2", platform=PLATFORM, account_id=ACCOUNT, now=6
    )
    retried = store.get_delivery("dead-2", platform=PLATFORM, account_id=ACCOUNT)
    assert retried is not None and retried.state == "retry"


def test_ingress_completion_and_delivery_enqueue_are_atomic(
    store: ChannelStore,
) -> None:
    _admit(store, "event-success", "input-lane", 1)
    _claim_and_start(store, "event-success", "worker", 2)
    assert store.complete_ingress_and_enqueue_delivery(
        "event-success",
        ingress_owner_id="worker",
        delivery_id="delivery-success",
        idempotency_key="request-success:final",
        lane_key="output-lane",
        payload={"text": "done"},
        platform=PLATFORM,
        account_id=ACCOUNT,
        source_request_id="request-success",
        now=3,
    )
    ingress = store.get_ingress("event-success", platform=PLATFORM, account_id=ACCOUNT)
    delivery = store.get_delivery(
        "delivery-success", platform=PLATFORM, account_id=ACCOUNT
    )
    assert ingress is not None and ingress.state == "completed"
    assert delivery is not None and delivery.state == "pending"
    assert delivery.source_event_id == "event-success"

    _admit(store, "event-rollback", "input-lane-2", 4)
    _claim_and_start(store, "event-rollback", "worker-2", 5)
    store.enqueue_delivery(
        "delivery-conflict",
        "conflict-key",
        "other-lane",
        {"text": "existing"},
        platform=PLATFORM,
        account_id=ACCOUNT,
        now=5,
    )
    with pytest.raises(IdempotencyConflictError):
        store.complete_ingress_and_enqueue_delivery(
            "event-rollback",
            ingress_owner_id="worker-2",
            delivery_id="delivery-conflict",
            idempotency_key="conflict-key",
            lane_key="output-lane-2",
            payload={"text": "new"},
            platform=PLATFORM,
            account_id=ACCOUNT,
            now=6,
        )
    rolled_back = store.get_ingress(
        "event-rollback", platform=PLATFORM, account_id=ACCOUNT
    )
    assert rolled_back is not None and rolled_back.state == "started"


def test_atomic_completion_rolls_back_a_new_delivery_after_injected_failure(
    store: ChannelStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _admit(store, "event-fault", "input-lane", 1)
    _claim_and_start(store, "event-fault", "worker", 2)

    def fail_after_enqueue(*_args: object, **_kwargs: object) -> None:
        raise sqlite3.OperationalError("injected completion write failure")

    monkeypatch.setattr(store, "_complete_ingress_conn", fail_after_enqueue)
    with pytest.raises(sqlite3.OperationalError, match="injected"):
        store.complete_ingress_and_enqueue_delivery(
            "event-fault",
            ingress_owner_id="worker",
            delivery_id="delivery-fault",
            idempotency_key="request-fault:final",
            lane_key="output-lane",
            payload={"text": "must roll back"},
            platform=PLATFORM,
            account_id=ACCOUNT,
            now=3,
        )

    ingress = store.get_ingress("event-fault", platform=PLATFORM, account_id=ACCOUNT)
    assert ingress is not None and ingress.state == "started"
    assert (
        store.get_delivery("delivery-fault", platform=PLATFORM, account_id=ACCOUNT)
        is None
    )


def test_poller_lease_conflicts_and_token_rotation_resets_offset(
    store: ChannelStore,
) -> None:
    fingerprint_a = store.fingerprint_token("token-a")
    fingerprint_b = store.fingerprint_token("token-b")
    lease = store.acquire_poller(
        platform=PLATFORM,
        account_id=ACCOUNT,
        token_fingerprint=fingerprint_a,
        owner_id="process-1",
        lease_seconds=10,
        now=1,
    )
    assert lease.update_offset is None
    store.advance_poller_offset(
        42,
        platform=PLATFORM,
        account_id=ACCOUNT,
        token_fingerprint=fingerprint_a,
        owner_id="process-1",
        now=2,
    )

    with pytest.raises(PollerLeaseConflictError):
        store.acquire_poller(
            platform=PLATFORM,
            account_id=ACCOUNT,
            token_fingerprint=fingerprint_a,
            owner_id="process-2",
            lease_seconds=10,
            now=3,
        )
    with pytest.raises(PollerLeaseConflictError):
        store.acquire_poller(
            platform=PLATFORM,
            account_id=ACCOUNT,
            token_fingerprint=fingerprint_b,
            owner_id="process-2",
            lease_seconds=10,
            now=3,
        )

    takeover = store.acquire_poller(
        platform=PLATFORM,
        account_id=ACCOUNT,
        token_fingerprint=fingerprint_a,
        owner_id="process-2",
        lease_seconds=10,
        now=11,
    )
    assert takeover.update_offset == 42
    rotated = store.acquire_poller(
        platform=PLATFORM,
        account_id=ACCOUNT,
        token_fingerprint=fingerprint_b,
        owner_id="process-3",
        lease_seconds=10,
        now=22,
    )
    assert rotated.update_offset is None
    with pytest.raises(PollerLeaseConflictError):
        store.get_poller_offset(
            platform=PLATFORM,
            account_id=ACCOUNT,
            token_fingerprint=fingerprint_a,
        )


def test_poller_admission_and_offset_advance_are_atomic(
    store: ChannelStore,
) -> None:
    fingerprint = store.fingerprint_token("token")
    store.acquire_poller(
        platform=PLATFORM,
        account_id=ACCOUNT,
        token_fingerprint=fingerprint,
        owner_id="process",
        lease_seconds=100,
        now=1,
    )
    assert store.admit_ingress_and_advance_poller(
        "update-10",
        "lane",
        {"update_id": 10},
        platform=PLATFORM,
        account_id=ACCOUNT,
        token_fingerprint=fingerprint,
        owner_id="process",
        new_offset=11,
        now=2,
    )
    assert (
        store.get_ingress("update-10", platform=PLATFORM, account_id=ACCOUNT)
        is not None
    )
    assert (
        store.get_poller_offset(
            platform=PLATFORM,
            account_id=ACCOUNT,
            token_fingerprint=fingerprint,
        )
        == 11
    )

    with pytest.raises(IdempotencyConflictError):
        store.admit_ingress_and_advance_poller(
            "update-10",
            "lane",
            {"update_id": "different"},
            platform=PLATFORM,
            account_id=ACCOUNT,
            token_fingerprint=fingerprint,
            owner_id="process",
            new_offset=12,
            now=3,
        )
    assert (
        store.get_poller_offset(
            platform=PLATFORM,
            account_id=ACCOUNT,
            token_fingerprint=fingerprint,
        )
        == 11
    )


class IngressDurabilityStateMachine(RuleBasedStateMachine):
    """Exercise crash/retry/CAS paths against one durable inbound event."""

    def __init__(self) -> None:
        super().__init__()
        self.temp_dir = tempfile.TemporaryDirectory(prefix="penguin-channel-state-")
        self.store = ChannelStore(Path(self.temp_dir.name) / "channels.db")
        self.now = 1.0
        self.model_state = "pending"
        self.attempt_count = 0
        self.ready_at = self.now
        self.lease_expires_at: float | None = None
        assert self.store.admit_ingress(
            "event",
            "lane",
            {"event": "event"},
            platform=PLATFORM,
            account_id=ACCOUNT,
            now=self.now,
        )

    def teardown(self) -> None:
        self.temp_dir.cleanup()

    @rule()
    def duplicate_admission_never_creates_new_work(self) -> None:
        assert not self.store.admit_ingress(
            "event",
            "lane",
            {"event": "event"},
            platform=PLATFORM,
            account_id=ACCOUNT,
            now=self.now,
        )

    @precondition(
        lambda self: (
            self.model_state in {"pending", "retry"} and self.now >= self.ready_at
        )
    )
    @rule()
    def claim(self) -> None:
        record = self.store.claim_ingress(
            platform=PLATFORM,
            account_id=ACCOUNT,
            owner_id="worker",
            lease_seconds=5,
            now=self.now,
        )
        assert record is not None
        self.model_state = "claimed"
        self.attempt_count += 1
        self.lease_expires_at = self.now + 5

    @precondition(lambda self: self.model_state == "claimed")
    @rule()
    def start(self) -> None:
        self.store.start_ingress(
            "event",
            platform=PLATFORM,
            account_id=ACCOUNT,
            owner_id="worker",
            now=self.now,
        )
        self.model_state = "started"

    @precondition(lambda self: self.model_state in {"claimed", "started"})
    @rule()
    def retry_owned_work(self) -> None:
        self.ready_at = self.now + 1
        self.store.retry_ingress(
            "event",
            platform=PLATFORM,
            account_id=ACCOUNT,
            owner_id="worker",
            retry_at=self.ready_at,
            error_class="Transient",
            error_message="retry",
            now=self.now,
        )
        self.model_state = "retry"
        self.lease_expires_at = None

    @precondition(lambda self: self.model_state == "retry")
    @rule()
    def reach_retry_deadline(self) -> None:
        self.now = self.ready_at

    @precondition(lambda self: self.model_state == "started")
    @rule()
    def complete(self) -> None:
        self.store.complete_ingress(
            "event",
            platform=PLATFORM,
            account_id=ACCOUNT,
            owner_id="worker",
            now=self.now,
        )
        self.model_state = "completed"
        self.lease_expires_at = None

    @precondition(lambda self: self.model_state in {"claimed", "started"})
    @rule()
    def dead_letter(self) -> None:
        self.store.dead_letter_ingress(
            "event",
            platform=PLATFORM,
            account_id=ACCOUNT,
            owner_id="worker",
            error_class="Terminal",
            error_message="dead",
            now=self.now,
        )
        self.model_state = "dead"
        self.lease_expires_at = None

    @precondition(lambda self: self.model_state in {"claimed", "started"})
    @rule()
    def wrong_owner_cannot_transition(self) -> None:
        with pytest.raises(LeaseLostError):
            self.store.retry_ingress(
                "event",
                platform=PLATFORM,
                account_id=ACCOUNT,
                owner_id="intruder",
                retry_at=self.now,
                error_class="Transient",
                error_message="must fail",
                now=self.now,
            )

    @precondition(lambda self: self.model_state in {"claimed", "started"})
    @rule()
    def recover_after_worker_crash(self) -> None:
        assert self.lease_expires_at is not None
        self.now = self.lease_expires_at
        counts = self.store.recover_expired_ingress(now=self.now)
        if self.model_state == "claimed":
            assert (counts.retried, counts.dead) == (1, 0)
            self.model_state = "retry"
            self.ready_at = self.now
        else:
            assert (counts.retried, counts.dead) == (0, 1)
            self.model_state = "dead"
        self.lease_expires_at = None

    @precondition(lambda self: self.model_state == "dead")
    @rule()
    def operator_can_explicitly_retry_dead_work(self) -> None:
        assert self.store.requeue_dead_ingress(
            "event", platform=PLATFORM, account_id=ACCOUNT, now=self.now
        )
        self.model_state = "retry"
        self.ready_at = self.now

    @invariant()
    def durable_record_matches_model(self) -> None:
        record = self.store.get_ingress("event", platform=PLATFORM, account_id=ACCOUNT)
        assert record is not None
        assert record.state == self.model_state
        assert record.attempt_count == self.attempt_count
        expected_owner = (
            "worker" if self.model_state in {"claimed", "started"} else None
        )
        assert record.claim_owner == expected_owner
        if self.model_state in {"completed", "dead"}:
            assert (
                self.store.claim_ingress(
                    platform=PLATFORM,
                    account_id=ACCOUNT,
                    owner_id="replay",
                    lease_seconds=5,
                    now=self.now,
                )
                is None
            )


TestIngressDurabilityStateMachine = IngressDurabilityStateMachine.TestCase
TestIngressDurabilityStateMachine.settings = settings(
    max_examples=20, stateful_step_count=20, deadline=None
)
