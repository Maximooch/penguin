"""Small validation and hashing helpers for the channel store."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from penguin.channels.store_models import PayloadTooLargeError


def fingerprint_token(token: str) -> str:
    """Return a non-reversible bot-token identity safe for persistence."""

    if not token:
        raise ValueError("token must not be empty")
    material = b"penguin-channel-token-v1\0" + token.encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def pairing_hash(code: str) -> str:
    if not code or len(code) > 256:
        raise ValueError("pairing code must contain 1-256 characters")
    material = b"penguin-channel-pairing-v1\0" + code.encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def dead_letter_limit(limit: int) -> int:
    if isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer from 1 through 100")
    return limit


def required_text(value: str, name: str, max_chars: int = 512) -> str:
    if not value:
        raise ValueError(f"{name} must not be empty")
    if len(value) > max_chars:
        raise ValueError(f"{name} exceeds {max_chars} characters")
    return value


def optional_text(value: str | None, name: str, max_chars: int = 2_048) -> str | None:
    if value is not None and len(value) > max_chars:
        raise ValueError(f"{name} exceeds {max_chars} characters")
    return value


def encode_payload(payload: Mapping[str, Any], max_bytes: int) -> str:
    try:
        encoded = json.dumps(
            dict(payload),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("payload must be JSON serializable") from exc
    if len(encoded.encode("utf-8")) > max_bytes:
        raise PayloadTooLargeError(f"payload exceeds {max_bytes} UTF-8 bytes")
    return encoded
