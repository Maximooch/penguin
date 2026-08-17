"""Interactive callback persistence mixed into :mod:`penguin.channels.store`."""

from __future__ import annotations

import sqlite3
from typing import Any, Mapping

from penguin.channels.store_models import (
    CallbackRecord,
    IdempotencyConflictError,
    LeaseLostError,
    callback_record_from_row,
)


class CallbackStoreMixin:
    """SQLite callback transitions and their ordered terminal deliveries."""

    def _callback_values(
        self,
        callback_id: str,
        *,
        account_id: str,
        chat_id: str,
        topic_id: str | None,
        user_id: str,
        request_id: str,
        payload: Mapping[str, Any],
        expires_at: float,
        tool_call_id: str | None,
        now: float | None,
    ) -> dict[str, Any]:
        timestamp = self._now(now)
        if expires_at <= timestamp:
            raise ValueError("expires_at must be in the future")
        return {
            "callback_id": self._required(callback_id, "callback_id", 128),
            "account_id": self._required(account_id, "account_id"),
            "chat_id": self._required(chat_id, "chat_id"),
            "topic_id": self._optional(topic_id, "topic_id") or "",
            "user_id": self._required(user_id, "user_id"),
            "request_id": self._required(request_id, "request_id"),
            "tool_call_id": self._optional(tool_call_id, "tool_call_id"),
            "payload_json": self._encode_payload(payload),
            "expires_at": expires_at,
            "timestamp": timestamp,
        }

    @staticmethod
    def _insert_callback_conn(
        conn: sqlite3.Connection, values: Mapping[str, Any]
    ) -> None:
        try:
            conn.execute(
                """
                INSERT INTO channel_callbacks (
                    callback_id, account_id, chat_id, topic_id, user_id,
                    request_id, tool_call_id, payload_json, state,
                    expires_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                """,
                (
                    values["callback_id"],
                    values["account_id"],
                    values["chat_id"],
                    values["topic_id"],
                    values["user_id"],
                    values["request_id"],
                    values["tool_call_id"],
                    values["payload_json"],
                    values["expires_at"],
                    values["timestamp"],
                    values["timestamp"],
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise IdempotencyConflictError(
                f"callback {values['callback_id']!r} already exists"
            ) from exc

    def create_callback(
        self,
        callback_id: str,
        *,
        account_id: str,
        chat_id: str,
        topic_id: str | None,
        user_id: str,
        request_id: str,
        payload: Mapping[str, Any],
        expires_at: float,
        tool_call_id: str | None = None,
        now: float | None = None,
    ) -> CallbackRecord:
        """Create a bounded callback addressed to exactly one recipient."""

        values = self._callback_values(
            callback_id,
            account_id=account_id,
            chat_id=chat_id,
            topic_id=topic_id,
            user_id=user_id,
            request_id=request_id,
            payload=payload,
            expires_at=expires_at,
            tool_call_id=tool_call_id,
            now=now,
        )
        with self._write() as conn:
            self._insert_callback_conn(conn, values)
            row = conn.execute(
                "SELECT * FROM channel_callbacks WHERE callback_id = ?",
                (values["callback_id"],),
            ).fetchone()
            assert row is not None
            return callback_record_from_row(row)

    def create_callback_with_delivery(
        self,
        callback_id: str,
        *,
        account_id: str,
        chat_id: str,
        topic_id: str | None,
        user_id: str,
        request_id: str,
        payload: Mapping[str, Any],
        expires_at: float,
        projection_delivery_id: str,
        lane_key: str,
        delivery_payload: Mapping[str, Any],
        platform: str,
        source_session_id: str | None,
        tool_call_id: str | None = None,
        now: float | None = None,
    ) -> CallbackRecord:
        """Atomically create a callback and its preceding prompt delivery."""

        values = self._callback_values(
            callback_id,
            account_id=account_id,
            chat_id=chat_id,
            topic_id=topic_id,
            user_id=user_id,
            request_id=request_id,
            payload=payload,
            expires_at=expires_at,
            tool_call_id=tool_call_id,
            now=now,
        )
        delivery = self._delivery_values(
            delivery_id=projection_delivery_id,
            idempotency_key=projection_delivery_id,
            lane_key=lane_key,
            payload=delivery_payload,
            platform=platform,
            account_id=account_id,
            kind="text",
            source_event_id=None,
            source_session_id=source_session_id,
            source_request_id=request_id,
        )
        with self._write() as conn:
            self._insert_callback_conn(conn, values)
            self._insert_delivery_conn(
                conn,
                **delivery,
                ready_at=values["timestamp"],
                timestamp=values["timestamp"],
            )
            row = conn.execute(
                "SELECT * FROM channel_callbacks WHERE callback_id = ?",
                (values["callback_id"],),
            ).fetchone()
            assert row is not None
            return callback_record_from_row(row)

    def claim_callback(
        self,
        callback_id: str,
        *,
        account_id: str,
        chat_id: str,
        topic_id: str | None,
        user_id: str,
        owner_id: str,
        lease_seconds: float = 30.0,
        platform: str | None = None,
        now: float | None = None,
    ) -> CallbackRecord | None:
        """Claim a callback once, only when all recipient fields match."""

        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        timestamp = self._now(now)
        with self._write() as conn:
            expired = conn.execute(
                """
                UPDATE channel_callbacks
                SET state = 'expired', updated_at = ?, completed_at = ?
                WHERE callback_id = ? AND state = 'pending' AND expires_at <= ?
                """,
                (timestamp, timestamp, callback_id, timestamp),
            ).rowcount
            if expired:
                row = conn.execute(
                    "SELECT * FROM channel_callbacks WHERE callback_id = ?",
                    (callback_id,),
                ).fetchone()
                assert row is not None
                self._enqueue_callback_terminal_conn(
                    conn,
                    callback_record_from_row(row),
                    "Expired",
                    platform,
                    timestamp,
                )
            cursor = conn.execute(
                """
                UPDATE channel_callbacks
                SET state = 'claimed', claim_owner = ?, lease_expires_at = ?,
                    updated_at = ?
                WHERE callback_id = ? AND state = 'pending' AND expires_at > ?
                  AND account_id = ? AND chat_id = ? AND topic_id = ?
                  AND user_id = ?
                """,
                (
                    owner_id,
                    timestamp + lease_seconds,
                    timestamp,
                    callback_id,
                    timestamp,
                    account_id,
                    chat_id,
                    topic_id or "",
                    user_id,
                ),
            )
            if cursor.rowcount != 1:
                return None
            row = conn.execute(
                "SELECT * FROM channel_callbacks WHERE callback_id = ?",
                (callback_id,),
            ).fetchone()
            assert row is not None
            return callback_record_from_row(row)

    def complete_callback(
        self,
        callback_id: str,
        *,
        owner_id: str,
        now: float | None = None,
    ) -> None:
        """Mark an owned callback complete; replays cannot claim it again."""

        timestamp = self._now(now)
        with self._write() as conn:
            cursor = conn.execute(
                """
                UPDATE channel_callbacks
                SET state = 'completed', claim_owner = NULL,
                    lease_expires_at = NULL, updated_at = ?, completed_at = ?
                WHERE callback_id = ? AND state = 'claimed'
                  AND claim_owner = ?
                """,
                (timestamp, timestamp, callback_id, owner_id),
            )
            if cursor.rowcount != 1:
                raise LeaseLostError(f"callback {callback_id!r} is not owned")

    def complete_callback_with_terminal(
        self,
        callback_id: str,
        *,
        owner_id: str,
        label: str,
        platform: str,
        now: float | None = None,
    ) -> CallbackRecord:
        """Complete an owned callback and durably enqueue its terminal edit."""

        timestamp = self._now(now)
        with self._write() as conn:
            cursor = conn.execute(
                """
                UPDATE channel_callbacks
                SET state = 'completed', claim_owner = NULL,
                    lease_expires_at = NULL, updated_at = ?, completed_at = ?
                WHERE callback_id = ? AND state = 'claimed'
                  AND claim_owner = ?
                """,
                (timestamp, timestamp, callback_id, owner_id),
            )
            if cursor.rowcount != 1:
                raise LeaseLostError(f"callback {callback_id!r} is not owned")
            row = conn.execute(
                "SELECT * FROM channel_callbacks WHERE callback_id = ?",
                (callback_id,),
            ).fetchone()
            assert row is not None
            record = callback_record_from_row(row)
            self._enqueue_callback_terminal_conn(
                conn, record, label, platform, timestamp
            )
            return record

    def terminalize_callbacks(
        self,
        request_id: str,
        *,
        account_id: str,
        label: str,
        platform: str,
        expired: bool = False,
        now: float | None = None,
    ) -> list[CallbackRecord]:
        """Terminalize pending callbacks for an externally resolved request."""

        timestamp = self._now(now)
        terminal_state = "expired" if expired else "completed"
        records: list[CallbackRecord] = []
        with self._write() as conn:
            rows = conn.execute(
                """SELECT * FROM channel_callbacks
                WHERE account_id = ? AND request_id = ? AND state = 'pending'
                ORDER BY created_at, callback_id""",
                (account_id, request_id),
            ).fetchall()
            for row in rows:
                cursor = conn.execute(
                    """UPDATE channel_callbacks
                    SET state = ?, updated_at = ?, completed_at = ?
                    WHERE callback_id = ? AND state = 'pending'""",
                    (terminal_state, timestamp, timestamp, row["callback_id"]),
                )
                if cursor.rowcount != 1:
                    continue
                updated = conn.execute(
                    "SELECT * FROM channel_callbacks WHERE callback_id = ?",
                    (row["callback_id"],),
                ).fetchone()
                assert updated is not None
                record = callback_record_from_row(updated)
                self._enqueue_callback_terminal_conn(
                    conn, record, label, platform, timestamp
                )
                records.append(record)
        return records

    def recover_expired_callbacks(
        self,
        *,
        platform: str,
        account_id: str,
        now: float | None = None,
    ) -> list[CallbackRecord]:
        """Surface newly expired or uncertain callbacks exactly once."""

        timestamp = self._now(now)
        recovered: list[CallbackRecord] = []
        with self._write() as conn:
            rows = conn.execute(
                """SELECT * FROM channel_callbacks
                WHERE account_id = ? AND (
                    (state = 'pending' AND expires_at <= ?)
                    OR (state = 'claimed' AND lease_expires_at <= ?)
                ) ORDER BY created_at, callback_id""",
                (account_id, timestamp, timestamp),
            ).fetchall()
            for row in rows:
                terminal_state = "expired" if row["state"] == "pending" else "dead"
                cursor = conn.execute(
                    """UPDATE channel_callbacks
                    SET state = ?, claim_owner = NULL, lease_expires_at = NULL,
                        updated_at = ?, completed_at = ?
                    WHERE callback_id = ? AND state = ?""",
                    (
                        terminal_state,
                        timestamp,
                        timestamp,
                        row["callback_id"],
                        row["state"],
                    ),
                )
                if cursor.rowcount != 1:
                    continue
                updated = conn.execute(
                    "SELECT * FROM channel_callbacks WHERE callback_id = ?",
                    (row["callback_id"],),
                ).fetchone()
                assert updated is not None
                record = callback_record_from_row(updated)
                self._enqueue_callback_terminal_conn(
                    conn, record, "Expired", platform, timestamp
                )
                recovered.append(record)
        return recovered

    def recover_orphaned_callbacks(
        self,
        *,
        platform: str,
        account_id: str,
        now: float | None = None,
    ) -> list[CallbackRecord]:
        """Close callbacks whose in-memory waiter was lost across a restart."""

        timestamp = self._now(now)
        recovered: list[CallbackRecord] = []
        with self._write() as conn:
            rows = conn.execute(
                """SELECT * FROM channel_callbacks
                WHERE account_id = ? AND state IN ('pending', 'claimed')
                ORDER BY created_at, callback_id""",
                (account_id,),
            ).fetchall()
            for row in rows:
                terminal_state = "expired" if row["state"] == "pending" else "dead"
                cursor = conn.execute(
                    """UPDATE channel_callbacks
                    SET state = ?, claim_owner = NULL, lease_expires_at = NULL,
                        updated_at = ?, completed_at = ?
                    WHERE callback_id = ? AND state = ?""",
                    (
                        terminal_state,
                        timestamp,
                        timestamp,
                        row["callback_id"],
                        row["state"],
                    ),
                )
                if cursor.rowcount != 1:
                    continue
                updated = conn.execute(
                    "SELECT * FROM channel_callbacks WHERE callback_id = ?",
                    (row["callback_id"],),
                ).fetchone()
                assert updated is not None
                record = callback_record_from_row(updated)
                self._enqueue_callback_terminal_conn(
                    conn, record, "Expired", platform, timestamp
                )
                recovered.append(record)
        return recovered

    def _enqueue_callback_terminal_conn(
        self,
        conn: sqlite3.Connection,
        callback: CallbackRecord,
        label: str,
        platform: str | None,
        timestamp: float,
    ) -> None:
        payload = callback.payload
        projection_id = str(payload.get("projection_delivery_id") or "")
        lane_key = str(payload.get("lane_key") or "")
        platform = str(platform or payload.get("platform") or "")
        if not projection_id or not lane_key or not platform:
            return
        delivery_id = f"{platform}:callback-terminal:{callback.callback_id}"
        terminal_payload = {
            "chat_id": callback.chat_id,
            "topic_id": callback.topic_id or "",
            "projection_delivery_id": projection_id,
            "label": label,
        }
        delivery = self._delivery_values(
            delivery_id=delivery_id,
            idempotency_key=delivery_id,
            lane_key=lane_key,
            payload=terminal_payload,
            platform=platform,
            account_id=callback.account_id,
            kind="callback_terminal",
            source_event_id=None,
            source_session_id=str(payload.get("session_id") or "") or None,
            source_request_id=callback.request_id,
        )
        self._insert_delivery_conn(
            conn,
            **delivery,
            ready_at=timestamp,
            timestamp=timestamp,
        )
