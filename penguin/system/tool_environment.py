"""Explicit child environments. This module does not provide an OS sandbox."""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

__all__ = [
    "build_tool_environment",
    "hosted_tools_enabled",
    "tool_environment_capabilities",
    "tool_environment_scope",
]

_TRUSTED_ENV: ContextVar[Mapping[str, str]] = ContextVar(
    "trusted_tool_environment", default=MappingProxyType({})
)
_INHERITED = frozenset(
    {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "SYSTEMROOT", "WINDIR"}
)
_RESERVED = _INHERITED | frozenset(
    {
        "HOME",
        "USERPROFILE",
        "SHELL",
        "BASH_ENV",
        "ENV",
        "CDPATH",
        "IFS",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "SSH_AUTH_SOCK",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
    }
)
_RESERVED_PREFIXES = (
    "LINK_",
    "LK_",
    "PENGUIN_",
    "LD_",
    "DYLD_",
    "PYTHON",
    "NODE_",
    "GIT_",
    "BASH_FUNC_",
    "XDG_",
)


def hosted_tools_enabled() -> bool:
    """Return whether the operator enabled restricted child environments.

    Returns:
        True for hosted mode, False for the default local mode.

    Raises:
        ValueError: The operator supplied an unknown mode.
    """
    mode = os.environ.get("PENGUIN_TOOL_ENVIRONMENT", "local")
    if mode not in {"local", "hosted"}:
        raise ValueError("PENGUIN_TOOL_ENVIRONMENT must be local or hosted")
    return mode == "hosted"


def tool_environment_capabilities() -> dict[str, object]:
    """Return environment support without asserting execution isolation.

    Returns:
        Versioned support and the current operator-selected mode.

    Raises:
        ValueError: The operator selected an unknown mode.
    """
    return {
        "version": 1,
        "mode": "hosted" if hosted_tools_enabled() else "local",
        "execution_isolation": False,
        "remote_credential_delivery": False,
    }


@contextmanager
def tool_environment_scope(environment: Mapping[str, str]) -> Iterator[None]:
    """Bind trusted bootstrap values to this execution without global mutation.

    Only trusted launch code can call this function. It is not a tool argument
    or a request payload field. Thread launchers must propagate context explicitly.

    Args:
        environment: Per-execution values from trusted bootstrap code.

    Yields:
        None while the immutable environment snapshot is active.
    """
    token = _TRUSTED_ENV.set(MappingProxyType(dict(environment)))
    try:
        yield
    finally:
        _TRUSTED_ENV.reset(token)


def build_tool_environment(
    overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build a child environment without exposing hosted server credentials.

    Args:
        overrides: Untrusted tool-supplied variables, never bootstrap authority.

    Returns:
        A new environment dictionary. Local mode preserves legacy inheritance.

    Raises:
        ValueError: Hosted overrides contain an invalid or reserved name, or the
            operator selected an unknown mode. Errors never include values.
    """
    if not hosted_tools_enabled():
        return {**os.environ, **(overrides or {})}
    trusted = _TRUSTED_ENV.get()
    for key, value in (overrides or {}).items():
        normalized = key.upper()
        if (
            not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
            or not isinstance(value, str)
            or "\0" in value
            or normalized in _RESERVED
            or normalized.startswith(_RESERVED_PREFIXES)
            or normalized in {name.upper() for name in trusted}
        ):
            raise ValueError("Tool environment override is invalid or reserved")
    inherited = {name: os.environ[name] for name in _INHERITED if name in os.environ}
    return {**inherited, **trusted, **(overrides or {})}
