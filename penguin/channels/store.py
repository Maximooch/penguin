"""Durable SQLite state for remote channel integrations.

The store deliberately keeps transport payloads bounded and uses short,
explicit compare-and-swap transitions.  Each operation opens its own SQLite
connection so workers may safely use one :class:`ChannelStore` from different
threads.
"""

from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from penguin.channels._store_callbacks import CallbackStoreMixin
from penguin.channels._store_helpers import (
    dead_letter_limit,
    encode_payload,
    fingerprint_token,
    optional_text,
    pairing_hash,
    required_text,
)
from penguin.channels.store_models import (
    BindingRecord,
    CallbackRecord,
    ChannelStoreError,
    CompareAndSwapError,
    DeliveryRecord,
    IdempotencyConflictError,
    IngressRecord,
    LeaseLostError,
    PairingRecord,
    PayloadTooLargeError,
    PollerLease,
    PollerLeaseConflictError,
    RecoveryCounts,
    binding_record_from_row,
    delivery_record_from_row,
    ingress_record_from_row,
    pairing_record_from_row,
    poller_record_from_row,
)
from penguin.channels.store_schema import SCHEMA_SQL

DEFAULT_MAX_PAYLOAD_BYTES = 1_048_576
DEFAULT_MAX_ERROR_CHARS = 4_096
DEFAULT_BUSY_TIMEOUT_MS = 30_000


class ChannelStore(CallbackStoreMixin):
    """Production-oriented SQLite persistence for channel integrations."""

    def __init__(
        self,
        path: Path,
        *,
        max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
        max_error_chars: int = DEFAULT_MAX_ERROR_CHARS,
        busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if max_payload_bytes <= 0:
            raise ValueError("max_payload_bytes must be positive")
        if max_error_chars <= 0:
            raise ValueError("max_error_chars must be positive")
        if busy_timeout_ms <= 0:
            raise ValueError("busy_timeout_ms must be positive")

        self.path = Path(path)
        self.max_payload_bytes = max_payload_bytes
        self.max_error_chars = max_error_chars
        self.busy_timeout_ms = busy_timeout_ms
        self._clock = clock
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name == "posix":
            descriptor = os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600)
            os.close(descriptor)
            self.path.chmod(0o600)
        self._initialize()
        if os.name == "posix":
            self.path.chmod(0o600)

    fingerprint_token = staticmethod(fingerprint_token)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.path),
            timeout=self.busy_timeout_ms / 1000,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    def _initialize(self) -> None:
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA_SQL)
        finally:
            conn.close()

    def _now(self, now: float | None) -> float:
        return self._clock() if now is None else now

    _dead_letter_limit = staticmethod(dead_letter_limit)
    _required = staticmethod(required_text)
    _optional = staticmethod(optional_text)

    def _encode_payload(self, payload: Mapping[str, Any]) -> str:
        return encode_payload(payload, self.max_payload_bytes)

    def _error_fields(self, error_class: str, error_message: str) -> tuple[str, str]:
        bounded_class = self._required(error_class, "error_class", 256)
        return bounded_class, error_message[: self.max_error_chars]

    _pairing_hash = staticmethod(pairing_hash)

    # Bindings -------------------------------------------------------------

    def get_binding(self, address_key: str) -> BindingRecord | None:
        """Return the current binding for an address, if one exists."""

        self._required(address_key, "address_key", 1_024)
        with self._read() as conn:
            row = conn.execute(
                "SELECT * FROM channel_bindings WHERE address_key = ?",
                (address_key,),
            ).fetchone()
        return binding_record_from_row(row) if row is not None else None

    def upsert_binding(
        self,
        address_key: str,
        session_id: str,
        *,
        directory: str | None = None,
        agent_id: str | None = None,
        agent_mode: str | None = None,
        settings: Mapping[str, Any] | None = None,
        expected_version: int | None = None,
        now: float | None = None,
    ) -> BindingRecord:
        """Create or replace a binding, optionally using a version CAS."""

        address_key = self._required(address_key, "address_key", 1_024)
        session_id = self._required(session_id, "session_id")
        directory = self._optional(directory, "directory", 4_096)
        agent_id = self._optional(agent_id, "agent_id")
        agent_mode = self._optional(agent_mode, "agent_mode")
        settings_json = self._encode_payload(settings) if settings is not None else None
        timestamp = self._now(now)

        with self._write() as conn:
            if expected_version is None:
                conn.execute(
                    """
                    INSERT INTO channel_bindings (
                        address_key, session_id, directory, agent_id, agent_mode,
                        settings_json, version, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                    ON CONFLICT(address_key) DO UPDATE SET
                        session_id = excluded.session_id,
                        directory = excluded.directory,
                        agent_id = excluded.agent_id,
                        agent_mode = excluded.agent_mode,
                        settings_json = CASE WHEN ?
                            THEN excluded.settings_json
                            ELSE channel_bindings.settings_json END,
                        version = channel_bindings.version + 1,
                        updated_at = excluded.updated_at
                    """,
                    (
                        address_key,
                        session_id,
                        directory,
                        agent_id,
                        agent_mode,
                        settings_json or "{}",
                        timestamp,
                        timestamp,
                        settings_json is not None,
                    ),
                )
            elif expected_version == 0:
                try:
                    conn.execute(
                        """
                        INSERT INTO channel_bindings (
                            address_key, session_id, directory, agent_id,
                            agent_mode, settings_json, version, created_at,
                            updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                        """,
                        (
                            address_key,
                            session_id,
                            directory,
                            agent_id,
                            agent_mode,
                            settings_json or "{}",
                            timestamp,
                            timestamp,
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise CompareAndSwapError(
                        f"binding {address_key!r} already exists"
                    ) from exc
            elif expected_version > 0:
                cursor = conn.execute(
                    """
                    UPDATE channel_bindings
                    SET session_id = ?, directory = ?, agent_id = ?,
                        agent_mode = ?,
                        settings_json = COALESCE(?, settings_json),
                        version = version + 1, updated_at = ?
                    WHERE address_key = ? AND version = ?
                    """,
                    (
                        session_id,
                        directory,
                        agent_id,
                        agent_mode,
                        settings_json,
                        timestamp,
                        address_key,
                        expected_version,
                    ),
                )
                if cursor.rowcount != 1:
                    raise CompareAndSwapError(
                        f"binding {address_key!r} changed before replacement"
                    )
            else:
                raise ValueError("expected_version must be non-negative")

            row = conn.execute(
                "SELECT * FROM channel_bindings WHERE address_key = ?",
                (address_key,),
            ).fetchone()
            assert row is not None
            return binding_record_from_row(row)

    def migrate_binding_prefix(
        self,
        old_prefix: str,
        new_prefix: str,
        *,
        separator: str = "\x1f",
        expected_versions: Mapping[str, int] | None = None,
        group_authorization: tuple[str, str, str, str] | None = None,
        now: float | None = None,
    ) -> list[BindingRecord]:
        """Atomically migrate bindings and optionally authorize the new group."""

        old_prefix = self._required(old_prefix, "old_prefix", 1_024)
        new_prefix = self._required(new_prefix, "new_prefix", 1_024)
        if old_prefix == new_prefix:
            raise ValueError("binding prefixes must differ")
        if not separator or len(separator) > 8:
            raise ValueError("separator must contain 1-8 characters")
        if old_prefix.startswith(new_prefix + separator) or new_prefix.startswith(
            old_prefix + separator
        ):
            raise ValueError("binding prefixes must not overlap")
        authorization = self._group_authorization(group_authorization)
        timestamp = self._now(now)

        with self._write() as conn:
            rows = conn.execute(
                """
                SELECT * FROM channel_bindings
                WHERE address_key = ? OR address_key LIKE ? ESCAPE '\\'
                ORDER BY address_key
                """,
                (old_prefix, self._like_prefix(old_prefix + separator) + "%"),
            ).fetchall()
            if not rows and group_authorization is None:
                raise CompareAndSwapError(f"binding prefix {old_prefix!r} not found")

            migrations = [
                (row, new_prefix + row["address_key"][len(old_prefix) :])
                for row in rows
            ]
            old_keys = {row["address_key"] for row in rows}
            if expected_versions is not None and {
                key: int(value) for key, value in expected_versions.items()
            } != {row["address_key"]: row["version"] for row in rows}:
                raise CompareAndSwapError("binding versions changed before migration")

            for _, destination in migrations:
                collision = conn.execute(
                    "SELECT 1 FROM channel_bindings WHERE address_key = ?",
                    (destination,),
                ).fetchone()
                if collision is not None and destination not in old_keys:
                    raise CompareAndSwapError(
                        f"binding destination {destination!r} already exists"
                    )

            for row, destination in migrations:
                cursor = conn.execute(
                    """
                    UPDATE channel_bindings
                    SET address_key = ?, version = version + 1, updated_at = ?
                    WHERE address_key = ? AND version = ?
                    """,
                    (
                        destination,
                        timestamp,
                        row["address_key"],
                        row["version"],
                    ),
                )
                if cursor.rowcount != 1:
                    raise CompareAndSwapError("binding changed during migration")

            if authorization is not None:
                self._upsert_group_authorization(conn, authorization, timestamp)

            migrated = conn.execute(
                """
                SELECT * FROM channel_bindings
                WHERE address_key = ? OR address_key LIKE ? ESCAPE '\\'
                ORDER BY address_key
                """,
                (new_prefix, self._like_prefix(new_prefix + separator) + "%"),
            ).fetchall()
            return [binding_record_from_row(row) for row in migrated]

    def is_group_authorized(
        self,
        *,
        platform: str,
        account_id: str,
        chat_id: str,
        allowed_source_chat_ids: frozenset[str],
    ) -> bool:
        """Check whether migration lineage reaches a currently allowed source."""

        if not allowed_source_chat_ids:
            return False
        with self._read() as conn:
            rows = conn.execute(
                """WITH RECURSIVE lineage(chat_id, source_chat_id) AS (
                    SELECT chat_id, source_chat_id
                    FROM channel_group_authorizations
                    WHERE platform = ? AND account_id = ? AND chat_id = ?
                    UNION
                    SELECT parent.chat_id, parent.source_chat_id
                    FROM channel_group_authorizations AS parent
                    JOIN lineage AS child
                      ON parent.chat_id = child.source_chat_id
                    WHERE parent.platform = ? AND parent.account_id = ?
                )
                SELECT source_chat_id FROM lineage""",
                (platform, account_id, chat_id, platform, account_id),
            ).fetchall()
        return any(row["source_chat_id"] in allowed_source_chat_ids for row in rows)

    @staticmethod
    def _like_prefix(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def _group_authorization(
        self, value: tuple[str, str, str, str] | None
    ) -> tuple[str, str, str, str] | None:
        if value is None:
            return None
        platform, account_id, source_chat_id, chat_id = (
            self._required(item, "group authorization") for item in value
        )
        if source_chat_id == chat_id:
            raise ValueError("group migration chat IDs must differ")
        return platform, account_id, source_chat_id, chat_id

    @staticmethod
    def _upsert_group_authorization(
        conn: sqlite3.Connection,
        value: tuple[str, str, str, str],
        timestamp: float,
    ) -> None:
        platform, account_id, source_chat_id, chat_id = value
        conn.execute(
            """INSERT INTO channel_group_authorizations (
                platform, account_id, chat_id, source_chat_id, created_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(platform, account_id, chat_id) DO UPDATE SET
                source_chat_id = excluded.source_chat_id""",
            (platform, account_id, chat_id, source_chat_id, timestamp),
        )

    def resolve_group_source(
        self, *, platform: str, account_id: str, chat_id: str
    ) -> str:
        """Resolve a migrated group ID back to its stable scheduling source."""

        current = self._required(chat_id, "chat_id")
        with self._read() as conn:
            for _ in range(64):
                row = conn.execute(
                    """SELECT source_chat_id FROM channel_group_authorizations
                    WHERE platform = ? AND account_id = ? AND chat_id = ?""",
                    (platform, account_id, current),
                ).fetchone()
                if row is None or row["source_chat_id"] == current:
                    return current
                current = row["source_chat_id"]
        raise ChannelStoreError("group migration lineage is cyclic or too deep")

    def resolve_group_destination(
        self, *, platform: str, account_id: str, chat_id: str
    ) -> str:
        """Resolve an obsolete group ID to its latest known destination."""

        current = self._required(chat_id, "chat_id")
        with self._read() as conn:
            for _ in range(64):
                row = conn.execute(
                    """SELECT chat_id FROM channel_group_authorizations
                    WHERE platform = ? AND account_id = ? AND source_chat_id = ?
                    ORDER BY created_at DESC, chat_id DESC LIMIT 1""",
                    (platform, account_id, current),
                ).fetchone()
                if row is None or row["chat_id"] == current:
                    return current
                current = row["chat_id"]
        raise ChannelStoreError("group migration lineage is cyclic or too deep")

    # Pairing and DM grants -----------------------------------------------

    def create_pairing(
        self,
        code: str,
        *,
        account_id: str,
        expires_at: float,
        expected_user_id: str | None = None,
        now: float | None = None,
    ) -> PairingRecord:
        """Persist only a hash of a short-lived, single-use pairing code."""

        code_hash = self._pairing_hash(code)
        account_id = self._required(account_id, "account_id")
        expected_user_id = self._optional(expected_user_id, "expected_user_id")
        timestamp = self._now(now)
        if expires_at <= timestamp:
            raise ValueError("expires_at must be in the future")

        with self._write() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO channel_pairings (
                        code_hash, account_id, expected_user_id, state,
                        expires_at, created_at, updated_at
                    ) VALUES (?, ?, ?, 'active', ?, ?, ?)
                    """,
                    (
                        code_hash,
                        account_id,
                        expected_user_id,
                        expires_at,
                        timestamp,
                        timestamp,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise IdempotencyConflictError("pairing code already exists") from exc
            row = conn.execute(
                "SELECT * FROM channel_pairings WHERE code_hash = ?", (code_hash,)
            ).fetchone()
            assert row is not None
            return pairing_record_from_row(row)

    def consume_pairing(
        self,
        code: str,
        *,
        account_id: str,
        user_id: str,
        chat_id: str,
        now: float | None = None,
    ) -> PairingRecord | None:
        """Consume a pairing in a matching DM and atomically grant DM access."""

        code_hash = self._pairing_hash(code)
        account_id = self._required(account_id, "account_id")
        user_id = self._required(user_id, "user_id")
        chat_id = self._required(chat_id, "chat_id")
        timestamp = self._now(now)
        if chat_id != user_id:
            return None

        with self._write() as conn:
            conn.execute(
                """
                UPDATE channel_pairings
                SET state = 'expired', updated_at = ?
                WHERE code_hash = ? AND state = 'active' AND expires_at <= ?
                """,
                (timestamp, code_hash, timestamp),
            )
            cursor = conn.execute(
                """
                UPDATE channel_pairings
                SET state = 'consumed', consumed_by_user_id = ?,
                    consumed_chat_id = ?, updated_at = ?
                WHERE code_hash = ? AND account_id = ? AND state = 'active'
                  AND expires_at > ?
                  AND (expected_user_id IS NULL OR expected_user_id = ?)
                """,
                (
                    user_id,
                    chat_id,
                    timestamp,
                    code_hash,
                    account_id,
                    timestamp,
                    user_id,
                ),
            )
            if cursor.rowcount != 1:
                return None
            conn.execute(
                """
                INSERT INTO channel_dm_authorizations (
                    account_id, user_id, pairing_code_hash, created_at, revoked_at
                ) VALUES (?, ?, ?, ?, NULL)
                ON CONFLICT(account_id, user_id) DO UPDATE SET
                    pairing_code_hash = excluded.pairing_code_hash,
                    created_at = excluded.created_at,
                    revoked_at = NULL
                """,
                (account_id, user_id, code_hash, timestamp),
            )
            row = conn.execute(
                "SELECT * FROM channel_pairings WHERE code_hash = ?", (code_hash,)
            ).fetchone()
            assert row is not None
            return pairing_record_from_row(row)

    def can_consume_pairing(
        self,
        code: str,
        *,
        account_id: str,
        user_id: str,
        chat_id: str,
        now: float | None = None,
    ) -> bool:
        """Return whether a pairing may be consumed without changing state."""

        code_hash = self._pairing_hash(code)
        account_id = self._required(account_id, "account_id")
        user_id = self._required(user_id, "user_id")
        chat_id = self._required(chat_id, "chat_id")
        if chat_id != user_id:
            return False
        with self._read() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM channel_pairings
                WHERE code_hash = ? AND account_id = ? AND state = 'active'
                  AND expires_at > ?
                  AND (expected_user_id IS NULL OR expected_user_id = ?)
                """,
                (code_hash, account_id, self._now(now), user_id),
            ).fetchone()
        return row is not None

    def revoke_pairing(
        self, code: str, *, account_id: str, now: float | None = None
    ) -> bool:
        """Revoke an unused pairing code."""

        timestamp = self._now(now)
        with self._write() as conn:
            cursor = conn.execute(
                """
                UPDATE channel_pairings
                SET state = 'revoked', updated_at = ?
                WHERE code_hash = ? AND account_id = ? AND state = 'active'
                """,
                (timestamp, self._pairing_hash(code), account_id),
            )
            return cursor.rowcount == 1

    def is_dm_authorized(self, *, account_id: str, user_id: str) -> bool:
        """Return whether pairing currently grants this user DM access."""

        with self._read() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM channel_dm_authorizations
                WHERE account_id = ? AND user_id = ? AND revoked_at IS NULL
                """,
                (account_id, user_id),
            ).fetchone()
        return row is not None

    def revoke_dm_authorization(
        self, *, account_id: str, user_id: str, now: float | None = None
    ) -> bool:
        """Revoke a previously paired DM identity."""

        with self._write() as conn:
            cursor = conn.execute(
                """
                UPDATE channel_dm_authorizations SET revoked_at = ?
                WHERE account_id = ? AND user_id = ? AND revoked_at IS NULL
                """,
                (self._now(now), account_id, user_id),
            )
            return cursor.rowcount == 1

    # Durable inbound work ------------------------------------------------

    def admit_ingress(
        self,
        event_id: str,
        lane_key: str,
        payload: Mapping[str, Any],
        *,
        platform: str,
        account_id: str,
        group_authorization: tuple[str, str, str, str] | None = None,
        now: float | None = None,
    ) -> bool:
        """Durably admit an event, returning ``False`` for an exact duplicate."""

        platform = self._required(platform, "platform", 64)
        account_id = self._required(account_id, "account_id")
        event_id = self._required(event_id, "event_id")
        lane_key = self._required(lane_key, "lane_key", 1_024)
        payload_json = self._encode_payload(payload)
        authorization = self._group_authorization(group_authorization)
        timestamp = self._now(now)
        with self._write() as conn:
            if authorization is not None:
                self._upsert_group_authorization(conn, authorization, timestamp)
            return self._admit_ingress_conn(
                conn,
                platform=platform,
                account_id=account_id,
                event_id=event_id,
                lane_key=lane_key,
                payload_json=payload_json,
                timestamp=timestamp,
            )

    def _admit_ingress_conn(
        self,
        conn: sqlite3.Connection,
        *,
        platform: str,
        account_id: str,
        event_id: str,
        lane_key: str,
        payload_json: str,
        timestamp: float,
    ) -> bool:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO channel_ingress (
                platform, account_id, event_id, lane_key, payload_json,
                state, attempt_count, next_attempt_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)
            """,
            (
                platform,
                account_id,
                event_id,
                lane_key,
                payload_json,
                timestamp,
                timestamp,
                timestamp,
            ),
        )
        if cursor.rowcount == 1:
            return True
        row = conn.execute(
            """
            SELECT lane_key, payload_json FROM channel_ingress
            WHERE platform = ? AND account_id = ? AND event_id = ?
            """,
            (platform, account_id, event_id),
        ).fetchone()
        if (
            row is None
            or row["lane_key"] != lane_key
            or row["payload_json"] != payload_json
        ):
            raise IdempotencyConflictError(
                f"ingress event {event_id!r} was reused for different work"
            )
        return False

    def get_ingress(
        self, event_id: str, *, platform: str, account_id: str
    ) -> IngressRecord | None:
        """Return one ingress record for diagnostics or state transitions."""

        with self._read() as conn:
            row = conn.execute(
                """
                SELECT * FROM channel_ingress
                WHERE platform = ? AND account_id = ? AND event_id = ?
                """,
                (platform, account_id, event_id),
            ).fetchone()
        return ingress_record_from_row(row) if row is not None else None

    def claim_ingress(
        self,
        *,
        platform: str,
        account_id: str,
        owner_id: str,
        lease_seconds: float,
        lane_suffix: str | None = None,
        exclude_lane_suffix: str | None = None,
        now: float | None = None,
    ) -> IngressRecord | None:
        """Claim the oldest ready event whose lane has no earlier live work."""

        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if lane_suffix is not None and exclude_lane_suffix is not None:
            raise ValueError("lane suffix filters are mutually exclusive")
        owner_id = self._required(owner_id, "owner_id")
        timestamp = self._now(now)
        lease_expires = timestamp + lease_seconds
        lane_filter = ""
        parameters: list[Any] = [platform, account_id, timestamp]
        suffix = lane_suffix if lane_suffix is not None else exclude_lane_suffix
        if suffix is not None:
            suffix = self._required(suffix, "lane_suffix", 128)
            comparison = "=" if lane_suffix is not None else "!="
            lane_filter = f"AND substr(item.lane_key, -?) {comparison} ?"
            parameters.extend((len(suffix), suffix))
        with self._write() as conn:
            row = conn.execute(
                f"""
                SELECT item.*
                FROM channel_ingress AS item
                WHERE item.platform = ? AND item.account_id = ?
                  AND item.state IN ('pending', 'retry')
                  AND item.next_attempt_at <= ?
                  {lane_filter}
                  AND NOT EXISTS (
                      SELECT 1
                      FROM channel_ingress AS prior
                      WHERE prior.platform = item.platform
                        AND prior.account_id = item.account_id
                        AND prior.lane_key = item.lane_key
                        AND prior.sequence < item.sequence
                        AND prior.state IN (
                            'pending', 'retry', 'claimed', 'started'
                        )
                  )
                ORDER BY item.sequence
                LIMIT 1
                """,
                parameters,
            ).fetchone()
            if row is None:
                return None
            cursor = conn.execute(
                """
                UPDATE channel_ingress
                SET state = 'claimed', claim_owner = ?, lease_expires_at = ?,
                    attempt_count = attempt_count + 1, updated_at = ?
                WHERE sequence = ? AND state IN ('pending', 'retry')
                """,
                (owner_id, lease_expires, timestamp, row["sequence"]),
            )
            if cursor.rowcount != 1:
                return None
            claimed = conn.execute(
                "SELECT * FROM channel_ingress WHERE sequence = ?",
                (row["sequence"],),
            ).fetchone()
            assert claimed is not None
            return ingress_record_from_row(claimed)

    def start_ingress(
        self,
        event_id: str,
        *,
        platform: str,
        account_id: str,
        owner_id: str,
        now: float | None = None,
    ) -> IngressRecord:
        """Record that execution is beginning, before invoking Penguin."""

        timestamp = self._now(now)
        with self._write() as conn:
            cursor = conn.execute(
                """
                UPDATE channel_ingress
                SET state = 'started', started_at = ?, updated_at = ?
                WHERE platform = ? AND account_id = ? AND event_id = ?
                  AND state = 'claimed' AND claim_owner = ?
                  AND lease_expires_at > ?
                """,
                (
                    timestamp,
                    timestamp,
                    platform,
                    account_id,
                    event_id,
                    owner_id,
                    timestamp,
                ),
            )
            if cursor.rowcount != 1:
                raise LeaseLostError(f"ingress event {event_id!r} is not owned")
            row = conn.execute(
                """
                SELECT * FROM channel_ingress
                WHERE platform = ? AND account_id = ? AND event_id = ?
                """,
                (platform, account_id, event_id),
            ).fetchone()
            assert row is not None
            return ingress_record_from_row(row)

    def renew_ingress_lease(
        self,
        event_id: str,
        *,
        platform: str,
        account_id: str,
        owner_id: str,
        lease_seconds: float,
        now: float | None = None,
    ) -> bool:
        """Extend a live ingress claim with an owner CAS."""

        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        timestamp = self._now(now)
        with self._write() as conn:
            cursor = conn.execute(
                """
                UPDATE channel_ingress
                SET lease_expires_at = ?, updated_at = ?
                WHERE platform = ? AND account_id = ? AND event_id = ?
                  AND state IN ('claimed', 'started') AND claim_owner = ?
                  AND lease_expires_at > ?
                """,
                (
                    timestamp + lease_seconds,
                    timestamp,
                    platform,
                    account_id,
                    event_id,
                    owner_id,
                    timestamp,
                ),
            )
            return cursor.rowcount == 1

    def complete_ingress(
        self,
        event_id: str,
        *,
        platform: str,
        account_id: str,
        owner_id: str,
        now: float | None = None,
    ) -> None:
        """Complete a started ingress record using an owner CAS."""

        timestamp = self._now(now)
        with self._write() as conn:
            self._complete_ingress_conn(
                conn,
                event_id=event_id,
                platform=platform,
                account_id=account_id,
                owner_id=owner_id,
                timestamp=timestamp,
            )

    def _complete_ingress_conn(
        self,
        conn: sqlite3.Connection,
        *,
        event_id: str,
        platform: str,
        account_id: str,
        owner_id: str,
        timestamp: float,
    ) -> None:
        cursor = conn.execute(
            """
            UPDATE channel_ingress
            SET state = 'completed', claim_owner = NULL,
                lease_expires_at = NULL, updated_at = ?, completed_at = ?
            WHERE platform = ? AND account_id = ? AND event_id = ?
              AND state = 'started' AND claim_owner = ?
            """,
            (timestamp, timestamp, platform, account_id, event_id, owner_id),
        )
        if cursor.rowcount != 1:
            raise LeaseLostError(f"ingress event {event_id!r} is not owned")

    def retry_ingress(
        self,
        event_id: str,
        *,
        platform: str,
        account_id: str,
        owner_id: str,
        retry_at: float,
        error_class: str,
        error_message: str,
        now: float | None = None,
    ) -> None:
        """Release owned ingress work for a bounded, explicit retry."""

        timestamp = self._now(now)
        bounded_class, bounded_message = self._error_fields(error_class, error_message)
        if retry_at < timestamp:
            retry_at = timestamp
        with self._write() as conn:
            cursor = conn.execute(
                """
                UPDATE channel_ingress
                SET state = 'retry', next_attempt_at = ?, claim_owner = NULL,
                    lease_expires_at = NULL, started_at = NULL,
                    last_error_class = ?, last_error_message = ?, updated_at = ?
                WHERE platform = ? AND account_id = ? AND event_id = ?
                  AND state IN ('claimed', 'started') AND claim_owner = ?
                """,
                (
                    retry_at,
                    bounded_class,
                    bounded_message,
                    timestamp,
                    platform,
                    account_id,
                    event_id,
                    owner_id,
                ),
            )
            if cursor.rowcount != 1:
                raise LeaseLostError(f"ingress event {event_id!r} is not owned")

    def dead_letter_ingress(
        self,
        event_id: str,
        *,
        platform: str,
        account_id: str,
        owner_id: str,
        error_class: str,
        error_message: str,
        now: float | None = None,
    ) -> None:
        """Move owned ingress work to a terminal, inspectable state."""

        timestamp = self._now(now)
        bounded_class, bounded_message = self._error_fields(error_class, error_message)
        with self._write() as conn:
            cursor = conn.execute(
                """
                UPDATE channel_ingress
                SET state = 'dead', claim_owner = NULL,
                    lease_expires_at = NULL, last_error_class = ?,
                    last_error_message = ?, updated_at = ?, completed_at = ?
                WHERE platform = ? AND account_id = ? AND event_id = ?
                  AND state IN ('claimed', 'started') AND claim_owner = ?
                """,
                (
                    bounded_class,
                    bounded_message,
                    timestamp,
                    timestamp,
                    platform,
                    account_id,
                    event_id,
                    owner_id,
                ),
            )
            if cursor.rowcount != 1:
                raise LeaseLostError(f"ingress event {event_id!r} is not owned")

    def recover_expired_ingress(self, *, now: float | None = None) -> RecoveryCounts:
        """Retry unstarted claims and dead-letter uncertain started turns."""

        timestamp = self._now(now)
        with self._write() as conn:
            retried = conn.execute(
                """
                UPDATE channel_ingress
                SET state = 'retry', next_attempt_at = ?, claim_owner = NULL,
                    lease_expires_at = NULL, started_at = NULL,
                    last_error_class = 'lease_expired',
                    last_error_message = 'worker lease expired before execution',
                    updated_at = ?
                WHERE state = 'claimed' AND lease_expires_at <= ?
                """,
                (timestamp, timestamp, timestamp),
            ).rowcount
            dead = conn.execute(
                """
                UPDATE channel_ingress
                SET state = 'dead', claim_owner = NULL,
                    lease_expires_at = NULL,
                    last_error_class = 'execution_uncertain',
                    last_error_message =
                        'worker lease expired after execution started',
                    updated_at = ?, completed_at = ?
                WHERE state = 'started' AND lease_expires_at <= ?
                """,
                (timestamp, timestamp, timestamp),
            ).rowcount
            return RecoveryCounts(retried=retried, dead=dead)

    def requeue_dead_ingress(
        self,
        event_id: str,
        *,
        platform: str,
        account_id: str,
        now: float | None = None,
    ) -> bool:
        """Explicitly requeue a dead ingress record for operator recovery."""

        timestamp = self._now(now)
        with self._write() as conn:
            cursor = conn.execute(
                """
                UPDATE channel_ingress
                SET state = 'retry', next_attempt_at = ?, started_at = NULL,
                    last_error_class = NULL, last_error_message = NULL,
                    completed_at = NULL, updated_at = ?
                WHERE platform = ? AND account_id = ? AND event_id = ?
                  AND state = 'dead'
                """,
                (timestamp, timestamp, platform, account_id, event_id),
            )
            return cursor.rowcount == 1

    def list_dead_ingress(
        self, *, platform: str, account_id: str, limit: int = 100
    ) -> list[IngressRecord]:
        """List a bounded oldest-first page of inbound dead letters."""

        with self._read() as conn:
            rows = conn.execute(
                """SELECT * FROM channel_ingress
                WHERE platform = ? AND account_id = ? AND state = 'dead'
                ORDER BY sequence LIMIT ?""",
                (platform, account_id, self._dead_letter_limit(limit)),
            ).fetchall()
        return [ingress_record_from_row(row) for row in rows]

    def discard_dead_ingress(
        self, event_id: str, *, platform: str, account_id: str
    ) -> bool:
        """Delete only a dead ingress record with no referenced deliveries."""

        with self._write() as conn:
            cursor = conn.execute(
                """DELETE FROM channel_ingress AS item
                WHERE platform = ? AND account_id = ? AND event_id = ?
                  AND state = 'dead' AND NOT EXISTS (
                    SELECT 1 FROM channel_deliveries AS delivery
                    WHERE delivery.platform = item.platform
                      AND delivery.account_id = item.account_id
                      AND delivery.source_event_id = item.event_id
                  )""",
                (platform, account_id, event_id),
            )
            return cursor.rowcount == 1

    # Durable outbound work -----------------------------------------------

    def enqueue_delivery(
        self,
        delivery_id: str,
        idempotency_key: str,
        lane_key: str,
        payload: Mapping[str, Any],
        *,
        platform: str,
        account_id: str,
        kind: str = "text",
        source_event_id: str | None = None,
        source_session_id: str | None = None,
        source_request_id: str | None = None,
        available_at: float | None = None,
        now: float | None = None,
    ) -> bool:
        """Idempotently enqueue a bounded outbound delivery."""

        timestamp = self._now(now)
        ready_at = timestamp if available_at is None else max(available_at, timestamp)
        values = self._delivery_values(
            delivery_id=delivery_id,
            idempotency_key=idempotency_key,
            lane_key=lane_key,
            payload=payload,
            platform=platform,
            account_id=account_id,
            kind=kind,
            source_event_id=source_event_id,
            source_session_id=source_session_id,
            source_request_id=source_request_id,
        )
        with self._write() as conn:
            return self._insert_delivery_conn(
                conn, **values, ready_at=ready_at, timestamp=timestamp
            )

    def _delivery_values(
        self,
        *,
        delivery_id: str,
        idempotency_key: str,
        lane_key: str,
        payload: Mapping[str, Any],
        platform: str,
        account_id: str,
        kind: str,
        source_event_id: str | None,
        source_session_id: str | None,
        source_request_id: str | None,
    ) -> dict[str, Any]:
        return {
            "delivery_id": self._required(delivery_id, "delivery_id"),
            "idempotency_key": self._required(
                idempotency_key, "idempotency_key", 1_024
            ),
            "lane_key": self._required(lane_key, "lane_key", 1_024),
            "payload_json": self._encode_payload(payload),
            "platform": self._required(platform, "platform", 64),
            "account_id": self._required(account_id, "account_id"),
            "kind": self._required(kind, "kind", 64),
            "source_event_id": self._optional(source_event_id, "source_event_id"),
            "source_session_id": self._optional(source_session_id, "source_session_id"),
            "source_request_id": self._optional(source_request_id, "source_request_id"),
        }

    def _insert_delivery_conn(
        self,
        conn: sqlite3.Connection,
        *,
        delivery_id: str,
        idempotency_key: str,
        lane_key: str,
        payload_json: str,
        platform: str,
        account_id: str,
        kind: str,
        source_event_id: str | None,
        source_session_id: str | None,
        source_request_id: str | None,
        ready_at: float,
        timestamp: float,
    ) -> bool:
        existing = conn.execute(
            """
            SELECT * FROM channel_deliveries
            WHERE platform = ? AND account_id = ?
              AND (delivery_id = ? OR idempotency_key = ?)
            ORDER BY sequence
            """,
            (platform, account_id, delivery_id, idempotency_key),
        ).fetchall()
        if existing:
            if len(existing) != 1:
                raise IdempotencyConflictError(
                    "delivery id and idempotency key identify different records"
                )
            row = existing[0]
            expected = (
                delivery_id,
                idempotency_key,
                lane_key,
                kind,
                payload_json,
                source_event_id,
                source_session_id,
                source_request_id,
            )
            actual = (
                row["delivery_id"],
                row["idempotency_key"],
                row["lane_key"],
                row["kind"],
                row["payload_json"],
                row["source_event_id"],
                row["source_session_id"],
                row["source_request_id"],
            )
            if actual != expected:
                raise IdempotencyConflictError(
                    f"delivery {delivery_id!r} was reused for different work"
                )
            return False

        conn.execute(
            """
            INSERT INTO channel_deliveries (
                platform, account_id, delivery_id, idempotency_key, lane_key,
                kind, payload_json, source_event_id, source_session_id,
                source_request_id, state, attempt_count, next_attempt_at,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)
            """,
            (
                platform,
                account_id,
                delivery_id,
                idempotency_key,
                lane_key,
                kind,
                payload_json,
                source_event_id,
                source_session_id,
                source_request_id,
                ready_at,
                timestamp,
                timestamp,
            ),
        )
        return True

    def complete_ingress_and_enqueue_delivery(
        self,
        event_id: str,
        *,
        ingress_owner_id: str,
        delivery_id: str,
        idempotency_key: str,
        lane_key: str,
        payload: Mapping[str, Any],
        platform: str,
        account_id: str,
        kind: str = "text",
        source_session_id: str | None = None,
        source_request_id: str | None = None,
        now: float | None = None,
    ) -> bool:
        """Atomically adopt the final delivery and complete its ingress turn."""

        timestamp = self._now(now)
        values = self._delivery_values(
            delivery_id=delivery_id,
            idempotency_key=idempotency_key,
            lane_key=lane_key,
            payload=payload,
            platform=platform,
            account_id=account_id,
            kind=kind,
            source_event_id=event_id,
            source_session_id=source_session_id,
            source_request_id=source_request_id,
        )
        with self._write() as conn:
            inserted = self._insert_delivery_conn(
                conn, **values, ready_at=timestamp, timestamp=timestamp
            )
            self._complete_ingress_conn(
                conn,
                event_id=event_id,
                platform=platform,
                account_id=account_id,
                owner_id=ingress_owner_id,
                timestamp=timestamp,
            )
            return inserted

    def get_delivery(
        self, delivery_id: str, *, platform: str, account_id: str
    ) -> DeliveryRecord | None:
        """Return one delivery for diagnostics or state transitions."""

        with self._read() as conn:
            row = conn.execute(
                """
                SELECT * FROM channel_deliveries
                WHERE platform = ? AND account_id = ? AND delivery_id = ?
                """,
                (platform, account_id, delivery_id),
            ).fetchone()
        return delivery_record_from_row(row) if row is not None else None

    def claim_delivery(
        self,
        *,
        platform: str,
        account_id: str,
        owner_id: str,
        lease_seconds: float,
        now: float | None = None,
    ) -> DeliveryRecord | None:
        """Claim the oldest ready delivery with lane ordering."""

        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        owner_id = self._required(owner_id, "owner_id")
        timestamp = self._now(now)
        with self._write() as conn:
            row = conn.execute(
                """
                SELECT item.*
                FROM channel_deliveries AS item
                WHERE item.platform = ? AND item.account_id = ?
                  AND item.state IN ('pending', 'retry')
                  AND item.next_attempt_at <= ?
                  AND NOT EXISTS (
                      SELECT 1
                      FROM channel_deliveries AS prior
                      WHERE prior.platform = item.platform
                        AND prior.account_id = item.account_id
                        AND prior.lane_key = item.lane_key
                        AND prior.sequence < item.sequence
                        AND prior.state IN ('pending', 'retry', 'claimed')
                  )
                ORDER BY item.sequence
                LIMIT 1
                """,
                (platform, account_id, timestamp),
            ).fetchone()
            if row is None:
                return None
            cursor = conn.execute(
                """
                UPDATE channel_deliveries
                SET state = 'claimed', claim_owner = ?, lease_expires_at = ?,
                    attempt_count = attempt_count + 1, updated_at = ?
                WHERE sequence = ? AND state IN ('pending', 'retry')
                """,
                (
                    owner_id,
                    timestamp + lease_seconds,
                    timestamp,
                    row["sequence"],
                ),
            )
            if cursor.rowcount != 1:
                return None
            claimed = conn.execute(
                "SELECT * FROM channel_deliveries WHERE sequence = ?",
                (row["sequence"],),
            ).fetchone()
            assert claimed is not None
            return delivery_record_from_row(claimed)

    def renew_delivery_lease(
        self,
        delivery_id: str,
        *,
        platform: str,
        account_id: str,
        owner_id: str,
        lease_seconds: float,
        now: float | None = None,
    ) -> bool:
        """Extend an owned delivery lease before it expires."""

        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        timestamp = self._now(now)
        with self._write() as conn:
            cursor = conn.execute(
                """
                UPDATE channel_deliveries
                SET lease_expires_at = ?, updated_at = ?
                WHERE platform = ? AND account_id = ? AND delivery_id = ?
                  AND state = 'claimed' AND claim_owner = ?
                  AND lease_expires_at > ?
                """,
                (
                    timestamp + lease_seconds,
                    timestamp,
                    platform,
                    account_id,
                    delivery_id,
                    owner_id,
                    timestamp,
                ),
            )
            return cursor.rowcount == 1

    def complete_delivery(
        self,
        delivery_id: str,
        *,
        platform: str,
        account_id: str,
        owner_id: str,
        external_message_id: str | None = None,
        now: float | None = None,
    ) -> None:
        """Mark an owned delivery successfully sent."""

        external_message_id = self._optional(external_message_id, "external_message_id")
        timestamp = self._now(now)
        with self._write() as conn:
            cursor = conn.execute(
                """
                UPDATE channel_deliveries
                SET state = 'delivered', claim_owner = NULL,
                    lease_expires_at = NULL, external_message_id = ?,
                    updated_at = ?, completed_at = ?
                WHERE platform = ? AND account_id = ? AND delivery_id = ?
                  AND state = 'claimed' AND claim_owner = ?
                """,
                (
                    external_message_id,
                    timestamp,
                    timestamp,
                    platform,
                    account_id,
                    delivery_id,
                    owner_id,
                ),
            )
            if cursor.rowcount != 1:
                raise LeaseLostError(f"delivery {delivery_id!r} is not owned")

    def retry_delivery(
        self,
        delivery_id: str,
        *,
        platform: str,
        account_id: str,
        owner_id: str,
        retry_at: float,
        error_class: str,
        error_message: str,
        now: float | None = None,
    ) -> None:
        """Release an owned delivery for a later retry."""

        timestamp = self._now(now)
        bounded_class, bounded_message = self._error_fields(error_class, error_message)
        if retry_at < timestamp:
            retry_at = timestamp
        with self._write() as conn:
            cursor = conn.execute(
                """
                UPDATE channel_deliveries
                SET state = 'retry', next_attempt_at = ?, claim_owner = NULL,
                    lease_expires_at = NULL, last_error_class = ?,
                    last_error_message = ?, updated_at = ?
                WHERE platform = ? AND account_id = ? AND delivery_id = ?
                  AND state = 'claimed' AND claim_owner = ?
                """,
                (
                    retry_at,
                    bounded_class,
                    bounded_message,
                    timestamp,
                    platform,
                    account_id,
                    delivery_id,
                    owner_id,
                ),
            )
            if cursor.rowcount != 1:
                raise LeaseLostError(f"delivery {delivery_id!r} is not owned")

    def dead_letter_delivery(
        self,
        delivery_id: str,
        *,
        platform: str,
        account_id: str,
        owner_id: str,
        error_class: str,
        error_message: str,
        now: float | None = None,
    ) -> None:
        """Move an owned delivery to a terminal, inspectable state."""

        timestamp = self._now(now)
        bounded_class, bounded_message = self._error_fields(error_class, error_message)
        with self._write() as conn:
            cursor = conn.execute(
                """
                UPDATE channel_deliveries
                SET state = 'dead', claim_owner = NULL,
                    lease_expires_at = NULL, last_error_class = ?,
                    last_error_message = ?, updated_at = ?, completed_at = ?
                WHERE platform = ? AND account_id = ? AND delivery_id = ?
                  AND state = 'claimed' AND claim_owner = ?
                """,
                (
                    bounded_class,
                    bounded_message,
                    timestamp,
                    timestamp,
                    platform,
                    account_id,
                    delivery_id,
                    owner_id,
                ),
            )
            if cursor.rowcount != 1:
                raise LeaseLostError(f"delivery {delivery_id!r} is not owned")

    def recover_expired_deliveries(self, *, now: float | None = None) -> int:
        """Requeue deliveries abandoned by expired workers."""

        timestamp = self._now(now)
        with self._write() as conn:
            cursor = conn.execute(
                """
                UPDATE channel_deliveries
                SET state = 'retry', next_attempt_at = ?, claim_owner = NULL,
                    lease_expires_at = NULL,
                    last_error_class = 'lease_expired',
                    last_error_message = 'delivery worker lease expired',
                    updated_at = ?
                WHERE state = 'claimed' AND lease_expires_at <= ?
                """,
                (timestamp, timestamp, timestamp),
            )
            return cursor.rowcount

    def requeue_dead_delivery(
        self,
        delivery_id: str,
        *,
        platform: str,
        account_id: str,
        now: float | None = None,
    ) -> bool:
        """Explicitly requeue a dead delivery for operator recovery."""

        timestamp = self._now(now)
        with self._write() as conn:
            cursor = conn.execute(
                """
                UPDATE channel_deliveries
                SET state = 'retry', next_attempt_at = ?,
                    last_error_class = NULL, last_error_message = NULL,
                    completed_at = NULL, updated_at = ?
                WHERE platform = ? AND account_id = ? AND delivery_id = ?
                  AND state = 'dead'
                """,
                (timestamp, timestamp, platform, account_id, delivery_id),
            )
            return cursor.rowcount == 1

    def list_dead_deliveries(
        self, *, platform: str, account_id: str, limit: int = 100
    ) -> list[DeliveryRecord]:
        """List a bounded oldest-first page of outbound dead letters."""

        with self._read() as conn:
            rows = conn.execute(
                """SELECT * FROM channel_deliveries
                WHERE platform = ? AND account_id = ? AND state = 'dead'
                ORDER BY sequence LIMIT ?""",
                (platform, account_id, self._dead_letter_limit(limit)),
            ).fetchall()
        return [delivery_record_from_row(row) for row in rows]

    def discard_dead_delivery(
        self, delivery_id: str, *, platform: str, account_id: str
    ) -> bool:
        """Delete only a terminal dead delivery."""

        with self._write() as conn:
            cursor = conn.execute(
                """DELETE FROM channel_deliveries
                WHERE platform = ? AND account_id = ? AND delivery_id = ?
                  AND state = 'dead'""",
                (platform, account_id, delivery_id),
            )
            return cursor.rowcount == 1

    # Poller ownership and durable watermark ------------------------------

    def acquire_poller(
        self,
        *,
        platform: str,
        account_id: str,
        token_fingerprint: str,
        owner_id: str,
        lease_seconds: float,
        now: float | None = None,
    ) -> PollerLease:
        """Acquire exclusive polling ownership or surface a conflict."""

        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        platform = self._required(platform, "platform", 64)
        account_id = self._required(account_id, "account_id")
        token_fingerprint = self._required(token_fingerprint, "token_fingerprint", 128)
        owner_id = self._required(owner_id, "owner_id")
        timestamp = self._now(now)
        expires_at = timestamp + lease_seconds

        with self._write() as conn:
            row = conn.execute(
                """
                SELECT * FROM channel_pollers
                WHERE platform = ? AND account_id = ?
                """,
                (platform, account_id),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO channel_pollers (
                        platform, account_id, token_fingerprint, lease_owner,
                        lease_expires_at, update_offset, updated_at
                    ) VALUES (?, ?, ?, ?, ?, NULL, ?)
                    """,
                    (
                        platform,
                        account_id,
                        token_fingerprint,
                        owner_id,
                        expires_at,
                        timestamp,
                    ),
                )
            else:
                active = (
                    row["lease_owner"] is not None
                    and row["lease_expires_at"] is not None
                    and row["lease_expires_at"] > timestamp
                )
                same_owner = (
                    row["lease_owner"] == owner_id
                    and row["token_fingerprint"] == token_fingerprint
                )
                if active and not same_owner:
                    raise PollerLeaseConflictError(
                        f"polling is already owned for {platform}/{account_id}"
                    )
                offset = (
                    row["update_offset"]
                    if row["token_fingerprint"] == token_fingerprint
                    else None
                )
                conn.execute(
                    """
                    UPDATE channel_pollers
                    SET token_fingerprint = ?, lease_owner = ?,
                        lease_expires_at = ?, update_offset = ?, updated_at = ?
                    WHERE platform = ? AND account_id = ?
                    """,
                    (
                        token_fingerprint,
                        owner_id,
                        expires_at,
                        offset,
                        timestamp,
                        platform,
                        account_id,
                    ),
                )

            current = conn.execute(
                """
                SELECT * FROM channel_pollers
                WHERE platform = ? AND account_id = ?
                """,
                (platform, account_id),
            ).fetchone()
            assert current is not None
            return poller_record_from_row(current)

    def renew_poller(
        self,
        *,
        platform: str,
        account_id: str,
        token_fingerprint: str,
        owner_id: str,
        lease_seconds: float,
        now: float | None = None,
    ) -> bool:
        """Renew a polling lease while it is still live."""

        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        timestamp = self._now(now)
        with self._write() as conn:
            cursor = conn.execute(
                """
                UPDATE channel_pollers
                SET lease_expires_at = ?, updated_at = ?
                WHERE platform = ? AND account_id = ?
                  AND token_fingerprint = ? AND lease_owner = ?
                  AND lease_expires_at > ?
                """,
                (
                    timestamp + lease_seconds,
                    timestamp,
                    platform,
                    account_id,
                    token_fingerprint,
                    owner_id,
                    timestamp,
                ),
            )
            return cursor.rowcount == 1

    def release_poller(
        self,
        *,
        platform: str,
        account_id: str,
        token_fingerprint: str,
        owner_id: str,
        now: float | None = None,
    ) -> bool:
        """Release polling ownership while retaining the matching offset."""

        with self._write() as conn:
            cursor = conn.execute(
                """
                UPDATE channel_pollers
                SET lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
                WHERE platform = ? AND account_id = ?
                  AND token_fingerprint = ? AND lease_owner = ?
                """,
                (
                    self._now(now),
                    platform,
                    account_id,
                    token_fingerprint,
                    owner_id,
                ),
            )
            return cursor.rowcount == 1

    def get_poller_offset(
        self,
        *,
        platform: str,
        account_id: str,
        token_fingerprint: str,
    ) -> int | None:
        """Return only the offset belonging to this exact bot fingerprint."""

        with self._read() as conn:
            row = conn.execute(
                """
                SELECT token_fingerprint, update_offset FROM channel_pollers
                WHERE platform = ? AND account_id = ?
                """,
                (platform, account_id),
            ).fetchone()
        if row is None:
            return None
        if row["token_fingerprint"] != token_fingerprint:
            raise PollerLeaseConflictError(
                f"stored offset belongs to another token for {platform}/{account_id}"
            )
        return row["update_offset"]

    def advance_poller_offset(
        self,
        new_offset: int,
        *,
        platform: str,
        account_id: str,
        token_fingerprint: str,
        owner_id: str,
        now: float | None = None,
    ) -> int:
        """Advance a live poller's watermark monotonically."""

        if new_offset < 0:
            raise ValueError("new_offset must be non-negative")
        timestamp = self._now(now)
        with self._write() as conn:
            row = self._require_poller_conn(
                conn,
                platform=platform,
                account_id=account_id,
                token_fingerprint=token_fingerprint,
                owner_id=owner_id,
                timestamp=timestamp,
            )
            current_offset = row["update_offset"]
            if current_offset is not None and new_offset < current_offset:
                raise CompareAndSwapError("poller offset cannot move backwards")
            conn.execute(
                """
                UPDATE channel_pollers SET update_offset = ?, updated_at = ?
                WHERE platform = ? AND account_id = ?
                """,
                (new_offset, timestamp, platform, account_id),
            )
            return new_offset

    def admit_ingress_and_advance_poller(
        self,
        event_id: str,
        lane_key: str,
        payload: Mapping[str, Any],
        *,
        platform: str,
        account_id: str,
        token_fingerprint: str,
        owner_id: str,
        new_offset: int,
        group_authorization: tuple[str, str, str, str] | None = None,
        now: float | None = None,
    ) -> bool:
        """Atomically persist an update before advancing its poll watermark."""

        if new_offset < 0:
            raise ValueError("new_offset must be non-negative")
        platform = self._required(platform, "platform", 64)
        account_id = self._required(account_id, "account_id")
        event_id = self._required(event_id, "event_id")
        lane_key = self._required(lane_key, "lane_key", 1_024)
        payload_json = self._encode_payload(payload)
        authorization = self._group_authorization(group_authorization)
        timestamp = self._now(now)
        with self._write() as conn:
            poller = self._require_poller_conn(
                conn,
                platform=platform,
                account_id=account_id,
                token_fingerprint=token_fingerprint,
                owner_id=owner_id,
                timestamp=timestamp,
            )
            current_offset = poller["update_offset"]
            if current_offset is not None and new_offset < current_offset:
                raise CompareAndSwapError("poller offset cannot move backwards")
            if authorization is not None:
                self._upsert_group_authorization(conn, authorization, timestamp)
            inserted = self._admit_ingress_conn(
                conn,
                platform=platform,
                account_id=account_id,
                event_id=event_id,
                lane_key=lane_key,
                payload_json=payload_json,
                timestamp=timestamp,
            )
            conn.execute(
                """
                UPDATE channel_pollers SET update_offset = ?, updated_at = ?
                WHERE platform = ? AND account_id = ?
                """,
                (new_offset, timestamp, platform, account_id),
            )
            return inserted

    @staticmethod
    def _require_poller_conn(
        conn: sqlite3.Connection,
        *,
        platform: str,
        account_id: str,
        token_fingerprint: str,
        owner_id: str,
        timestamp: float,
    ) -> sqlite3.Row:
        row = conn.execute(
            """
            SELECT * FROM channel_pollers
            WHERE platform = ? AND account_id = ?
            """,
            (platform, account_id),
        ).fetchone()
        if (
            row is None
            or row["token_fingerprint"] != token_fingerprint
            or row["lease_owner"] != owner_id
            or row["lease_expires_at"] is None
            or row["lease_expires_at"] <= timestamp
        ):
            raise LeaseLostError(
                f"poller lease is not owned for {platform}/{account_id}"
            )
        return row


__all__ = [
    "BindingRecord",
    "CallbackRecord",
    "ChannelStore",
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
