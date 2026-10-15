"""Deterministic catalog probe tests; no live requests or real credentials."""

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

spec = importlib.util.spec_from_file_location(
    "codex_tier_probe",
    Path(__file__).parents[1] / "scripts/probe_codex_service_tiers.py",
)
assert spec is not None and spec.loader is not None
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_catalog_metadata_classification() -> None:
    report = probe.summarize_catalog(
        {
            "models": [
                {"slug": "astra", "service_tiers": [{"id": "ultrafast"}]},
                {"slug": "legacy", "additional_speed_tiers": ["ultrafast"]},
                {"slug": "default", "default_service_tier": "ultrafast"},
                {"slug": "priority", "service_tiers": [{"id": "priority"}]},
                {"slug": "empty", "service_tiers": []},
                {"slug": "unknown", "private_value": "must-not-be-reported"},
            ]
        }
    )
    statuses = {m["model"]: m["ultrafast"] for m in report}
    assert statuses == {
        "astra": "advertised",
        "legacy": "advertised",
        "default": "advertised",
        "priority": "not_advertised",
        "empty": "not_advertised",
        "unknown": "unknown",
    }
    assert "must-not-be-reported" not in json.dumps(report)


@pytest.mark.parametrize(
    "payload", [{}, {"models": {}}, {"models": [None]}, {"models": [{}]}]
)
def test_rejects_invalid_catalog(payload: object) -> None:
    with pytest.raises(ValueError):
        probe.summarize_catalog(payload)


def test_request_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.host == "chatgpt.com"
        assert request.url.params["client_version"] == "1.0.0"
        assert request.headers["Authorization"] == "Bearer fake-token"
        assert request.headers["ChatGPT-Account-ID"] == "fake-account"
        return httpx.Response(200, json={"models": [{"slug": "astra"}]})

    result = probe.query_catalog(
        "fake-token", "fake-account", transport=httpx.MockTransport(handler)
    )
    assert result[0]["ultrafast"] == "unknown"


@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
def test_http_errors_never_log_body_or_follow_redirects(status: int) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            status,
            text="secret-response-body",
            headers={"Location": "https://example.com"},
        )

    with pytest.raises(ValueError) as exc:
        probe.query_catalog("fake-token", None, transport=httpx.MockTransport(handler))
    assert len(requests) == 1
    assert "secret-response-body" not in str(exc.value)
    assert "fake-token" not in str(exc.value)


def test_response_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe, "MAX_RESPONSE_BYTES", 4)
    with pytest.raises(ValueError, match="size limit"):
        probe.query_catalog(
            "fake-token",
            None,
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, content=b"12345")
            ),
        )


def test_invalid_json_is_redacted() -> None:
    with pytest.raises(ValueError, match="invalid JSON") as exc:
        probe.query_catalog(
            "fake-token",
            None,
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, content=b"secret invalid body")
            ),
        )
    assert "secret invalid body" not in str(exc.value)


@pytest.mark.parametrize(
    "payload",
    [
        {"tokens": {"access_token": "fake-token", "account_id": "fake-account"}},
        {
            "providers": {
                "openai": {
                    "type": "oauth",
                    "access": "fake-token",
                    "accountId": "fake-account",
                }
            }
        },
    ],
)
def test_auth_file_formats(tmp_path: Path, payload: dict) -> None:
    path = tmp_path / "auth.json"
    path.write_text(json.dumps(payload))
    assert probe.load_credentials(path) == ("fake-token", "fake-account")
    assert json.loads(path.read_text()) == payload


def test_api_key_not_used(tmp_path: Path) -> None:
    path = tmp_path / "auth.json"
    path.write_text(json.dumps({"OPENAI_API_KEY": "fake-key"}))
    with pytest.raises(ValueError, match="No OAuth"):
        probe.load_credentials(path)


def test_environment_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_OAUTH_ACCESS_TOKEN", "fake-token")
    monkeypatch.setenv("OPENAI_ACCOUNT_ID", "fake-account")
    assert probe.load_credentials() == ("fake-token", "fake-account")
