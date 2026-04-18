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


def test_main_defaults_to_localhost_without_auth(monkeypatch, capsys):
    calls = []
    app = object()

    fake_uvicorn = types.SimpleNamespace(
        run=lambda *args, **kwargs: calls.append((args, kwargs))
    )
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
    monkeypatch.setattr(server, "create_app_factory", lambda: app)
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.delenv("PENGUIN_AUTH_ENABLED", raising=False)
    monkeypatch.delenv("PENGUIN_ALLOW_INSECURE_NO_AUTH", raising=False)
    monkeypatch.delenv("PENGUIN_API_KEYS", raising=False)
    monkeypatch.delenv("PENGUIN_AUTH_STARTUP_TOKEN", raising=False)

    assert server.main() == 0

    output = capsys.readouterr().out
    assert "http://127.0.0.1:9000" in output
    assert "Penguin local web auth is enabled." in output
    assert (
        "Browser/dashboard only: open this local authorization URL once for this browser."
        in output
    )
    assert "TUI/CLI: local Penguin sessions authenticate automatically." in output
    assert "CI/headless: use PENGUIN_API_KEYS with X-API-Key header auth." in output
    assert "PENGUIN_AUTH_ENABLED=false uv run penguin-web" in output
    assert calls[0][0][0] is app
    assert calls[0][1]["host"] == "127.0.0.1"
    assert calls[0][1]["port"] == 9000


def test_main_explicit_false_prints_unsecured_warning(monkeypatch, capsys):
    calls = []
    app = object()

    fake_uvicorn = types.SimpleNamespace(
        run=lambda *args, **kwargs: calls.append((args, kwargs))
    )
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
    monkeypatch.setattr(server, "create_app_factory", lambda: app)
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "false")
    monkeypatch.delenv("PENGUIN_ALLOW_INSECURE_NO_AUTH", raising=False)

    assert server.main() == 0

    output = capsys.readouterr().out
    assert (
        "Warning: Penguin local web auth is explicitly disabled for this session."
        in output
    )
    assert "Protected local startup is the default: uv run penguin-web" in output
    assert "PENGUIN_AUTH_ENABLED=false uv run penguin-web" in output
    assert calls[0][0][0] is app


def test_main_prints_startup_token_when_auth_bootstrap_enabled(monkeypatch, capsys):
    calls = []
    app = object()

    fake_uvicorn = types.SimpleNamespace(
        run=lambda *args, **kwargs: calls.append((args, kwargs))
    )
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
    monkeypatch.setattr(server, "create_app_factory", lambda: app)
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.setenv("PORT", "9000")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "true")
    monkeypatch.delenv("PENGUIN_API_KEYS", raising=False)
    monkeypatch.delenv("PENGUIN_AUTH_STARTUP_TOKEN", raising=False)

    assert server.main() == 0

    output = capsys.readouterr().out
    assert "Penguin local web auth is enabled." in output
    assert (
        "Browser/dashboard only: open this local authorization URL once for this browser."
        in output
    )
    assert "http://127.0.0.1:9000/authorize#local_token=" in output
    assert "Startup token (debug fallback):" in output
    assert "TUI/CLI: local Penguin sessions authenticate automatically." in output
    assert calls[0][0][0] is app


def test_main_writes_local_auth_token_cache_when_bootstrap_enabled(
    monkeypatch, capsys, tmp_path
):
    calls = []
    app = object()

    fake_uvicorn = types.SimpleNamespace(
        run=lambda *args, **kwargs: calls.append((args, kwargs))
    )
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
    monkeypatch.setattr(server, "create_app_factory", lambda: app)
    monkeypatch.setenv("PENGUIN_LOCAL_AUTH_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.setenv("PORT", "9000")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.delenv("PENGUIN_AUTH_ENABLED", raising=False)
    monkeypatch.delenv("PENGUIN_API_KEYS", raising=False)
    monkeypatch.setenv("PENGUIN_AUTH_STARTUP_TOKEN", "cached-startup-token")

    assert server.main() == 0

    capsys.readouterr()
    assert (tmp_path / "127.0.0.1-9000.token").read_text() == "cached-startup-token"
    assert calls[0][0][0] is app


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


def test_start_server_defaults_to_localhost(monkeypatch):
    calls = []
    app = object()

    fake_uvicorn = types.SimpleNamespace(
        run=lambda *args, **kwargs: calls.append((args, kwargs))
    )
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
    monkeypatch.setattr(server, "create_app_factory", lambda: app)

    server.start_server(port=9000, debug=False)

    assert calls[0][0][0] is app
    assert calls[0][1]["host"] == "127.0.0.1"
    assert calls[0][1]["port"] == 9000


def test_validate_startup_security_allows_local_without_auth(monkeypatch):
    monkeypatch.delenv("PENGUIN_AUTH_ENABLED", raising=False)
    monkeypatch.delenv("PENGUIN_ALLOW_INSECURE_NO_AUTH", raising=False)

    server.validate_startup_security("127.0.0.1")


def test_validate_startup_security_blocks_non_local_without_auth(monkeypatch):
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "false")
    monkeypatch.delenv("PENGUIN_ALLOW_INSECURE_NO_AUTH", raising=False)

    try:
        server.validate_startup_security("0.0.0.0")
    except RuntimeError as exc:
        assert "PENGUIN_AUTH_ENABLED=false" in str(exc)
        assert "HOST=127.0.0.1" in str(exc)
    else:
        raise AssertionError("Expected insecure startup to be blocked")


def test_validate_startup_security_allows_non_local_with_auth(monkeypatch):
    monkeypatch.delenv("PENGUIN_AUTH_ENABLED", raising=False)
    monkeypatch.delenv("PENGUIN_ALLOW_INSECURE_NO_AUTH", raising=False)

    server.validate_startup_security("0.0.0.0")


def test_validate_startup_security_allows_override(monkeypatch):
    monkeypatch.delenv("PENGUIN_AUTH_ENABLED", raising=False)
    monkeypatch.setenv("PENGUIN_ALLOW_INSECURE_NO_AUTH", "true")

    server.validate_startup_security("0.0.0.0")
