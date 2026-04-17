import sys
import types

from penguin.web import server


def test_main_debug_uses_reload_safe_import_string(monkeypatch, capsys):
    calls = []

    fake_uvicorn = types.SimpleNamespace(
        run=lambda *args, **kwargs: calls.append((args, kwargs))
    )
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
    monkeypatch.setattr(server, "create_app_factory", lambda: object())
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "true")

    assert server.main() == 0

    output = capsys.readouterr().out
    assert "http://localhost:8080" in output
    assert calls[0][0][0] == "penguin.web.server:create_app_factory"
    assert calls[0][1]["reload"] is True
    assert calls[0][1]["factory"] is True
    assert calls[0][1]["port"] == 8080


def test_start_server_non_debug_uses_app_instance(monkeypatch):
    calls = []
    app = object()

    fake_uvicorn = types.SimpleNamespace(
        run=lambda *args, **kwargs: calls.append((args, kwargs))
    )
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
    monkeypatch.setattr(server, "create_app_factory", lambda: app)

    server.start_server(host="127.0.0.1", port=9000, debug=False)

    assert calls[0][0][0] is app
    assert calls[0][1]["host"] == "127.0.0.1"
    assert calls[0][1]["port"] == 9000
    assert calls[0][1]["reload"] is False


def test_validate_startup_security_allows_local_without_auth(monkeypatch):
    monkeypatch.delenv("PENGUIN_AUTH_ENABLED", raising=False)
    monkeypatch.delenv("PENGUIN_ALLOW_INSECURE_NO_AUTH", raising=False)

    server.validate_startup_security("127.0.0.1")


def test_validate_startup_security_blocks_non_local_without_auth(monkeypatch):
    monkeypatch.delenv("PENGUIN_AUTH_ENABLED", raising=False)
    monkeypatch.delenv("PENGUIN_ALLOW_INSECURE_NO_AUTH", raising=False)

    try:
        server.validate_startup_security("0.0.0.0")
    except RuntimeError as exc:
        assert "PENGUIN_AUTH_ENABLED=true" in str(exc)
    else:
        raise AssertionError("Expected insecure startup to be blocked")


def test_validate_startup_security_allows_non_local_with_auth(monkeypatch):
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "true")
    monkeypatch.delenv("PENGUIN_ALLOW_INSECURE_NO_AUTH", raising=False)

    server.validate_startup_security("0.0.0.0")


def test_validate_startup_security_allows_override(monkeypatch):
    monkeypatch.delenv("PENGUIN_AUTH_ENABLED", raising=False)
    monkeypatch.setenv("PENGUIN_ALLOW_INSECURE_NO_AUTH", "true")

    server.validate_startup_security("0.0.0.0")
