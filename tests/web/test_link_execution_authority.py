from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from penguin.web.middleware.auth import (
    AuthConfig,
    authenticate_connection,
    authenticate_link_service_request,
)


def _request(*, api_key: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/chat/message",
            "headers": [(b"x-api-key", api_key.encode())],
        }
    )


def test_link_execution_requires_the_dedicated_link_service_key(monkeypatch) -> None:
    monkeypatch.setenv("LINK_API_KEY", "link-service-secret")
    monkeypatch.setenv("PENGUIN_API_KEYS", "ordinary-client-secret")
    config = AuthConfig()

    auth = authenticate_link_service_request(
        _request(api_key="link-service-secret"),
        config,
    )

    assert auth == {
        "method": "link_service",
        "subject": "link",
        "metadata": {"service": "link"},
    }


def test_ordinary_api_key_cannot_authorize_link_execution(monkeypatch) -> None:
    monkeypatch.setenv("LINK_API_KEY", "link-service-secret")
    monkeypatch.setenv("PENGUIN_API_KEYS", "ordinary-client-secret")
    config = AuthConfig()

    with pytest.raises(HTTPException) as raised:
        authenticate_link_service_request(
            _request(api_key="ordinary-client-secret"),
            config,
        )

    assert raised.value.status_code == 403
    assert (
        authenticate_connection(
            _request(api_key="ordinary-client-secret"),
            config,
        )["subject"]
        == "api_client"
    )
