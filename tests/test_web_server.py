import logging
import sys
import types

import pytest

from penguin.web import server


@pytest.fixture(autouse=True)
def isolate_web_server_runtime(monkeypatch, tmp_path):
    """Keep entrypoint tests away from the user's production runtime storage."""

    monkeypatch.setenv("PENGUIN_WEB_LOG_ENABLED", "false")
    monkeypatch.setenv("PENGUIN_WORKSPACE", str(tmp_path))
    monkeypatch.setenv(
        "PENGUIN_RUNTIME_EVENT_LEDGER_PATH",
        str(tmp_path / "runtime_events" / "runtime_events.db"),
    )
    monkeypatch.setenv("PENGUIN_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("PENGUIN_LOCAL_AUTH_CACHE_DIR", str(tmp_path / "auth"))
    monkeypatch.setenv(
        "PENGUIN_PROVIDER_CREDENTIALS_STORE",
        str(tmp_path / "credentials" / "providers.json"),
    )
    monkeypatch.setenv(
        "PENGUIN_PROVIDER_AUTH_STORE",
        str(tmp_path / "credentials" / "provider_auth.json"),
    )
    monkeypatch.delenv("PENGUIN_SERVER_ROLE", raising=False)
    yield
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        if getattr(handler, server.SERVER_LOG_HANDLER_FLAG, False):
            root_logger.removeHandler(handler)
            handler.close()


def test_resolve_runtime_settings_prefers_cli_args(monkeypatch):
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "9000")
    monkeypatch.setenv("DEBUG", "false")

    host, port, debug = server._resolve_runtime_settings(
        ["--host", "127.0.0.1", "--port", "8080", "--debug"]
    )

    assert host == "127.0.0.1"
    assert port == 8080
    assert debug is True


def test_resolve_runtime_settings_uses_env_fallback(monkeypatch):
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "7777")
    monkeypatch.setenv("DEBUG", "true")

    host, port, debug = server._resolve_runtime_settings([])

    assert host == "0.0.0.0"
    assert port == 7777
    assert debug is True


def test_resolve_server_log_path_defaults_to_workspace(monkeypatch, tmp_path):
    monkeypatch.delenv("PENGUIN_WEB_LOG_FILE", raising=False)
    monkeypatch.delenv("PENGUIN_WEB_LOG_DIR", raising=False)
    monkeypatch.setenv("PENGUIN_WORKSPACE", str(tmp_path))

    log_path = server._resolve_server_log_path()

    assert log_path.parent == tmp_path / "server-logs"
    assert log_path.name.startswith("penguin-web-")
    assert log_path.suffix == ".txt"


def test_resolve_server_log_path_uses_log_dir_override(monkeypatch, tmp_path):
    monkeypatch.delenv("PENGUIN_WEB_LOG_FILE", raising=False)
    monkeypatch.setenv("PENGUIN_WEB_LOG_DIR", str(tmp_path / "runs"))

    log_path = server._resolve_server_log_path()

    assert log_path.parent == tmp_path / "runs"
    assert log_path.name.startswith("penguin-web-")
    assert log_path.suffix == ".txt"


def test_resolve_server_log_path_file_override_stays_exact(monkeypatch, tmp_path):
    log_file = tmp_path / "custom" / "logs.txt"
    monkeypatch.setenv("PENGUIN_WEB_LOG_FILE", str(log_file))
    monkeypatch.setenv("PENGUIN_WEB_LOG_DIR", str(tmp_path / "ignored"))

    assert server._resolve_server_log_path() == log_file.resolve()


def test_configure_server_file_logging_can_be_disabled():
    assert server._configure_server_file_logging("info") is None


def test_configure_server_file_logging_creates_uvicorn_log_config(
    monkeypatch, tmp_path
):
    log_dir = tmp_path / "server-logs"
    monkeypatch.setenv("PENGUIN_WEB_LOG_ENABLED", "true")
    monkeypatch.setenv("PENGUIN_WEB_LOG_DIR", str(log_dir))

    log_config = server._configure_server_file_logging("info")

    assert log_config is not None
    log_file = next(log_dir.glob("penguin-web-*.txt"))
    assert log_file.exists()
    assert log_file.parent.exists()
    assert "Penguin web server logs writing to" in log_file.read_text()
    assert log_config["handlers"]["file"]["filename"] == str(log_file.resolve())
    assert "file" in log_config["loggers"]["uvicorn.access"]["handlers"]


def test_main_debug_uses_reload_safe_import_string(monkeypatch, capsys, tmp_path):
    calls = []
    app_factory_calls = 0

    def create_app():
        nonlocal app_factory_calls
        app_factory_calls += 1
        return object()

    fake_uvicorn = types.SimpleNamespace(
        run=lambda *args, **kwargs: calls.append((args, kwargs))
    )
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
    monkeypatch.setattr(server, "create_app_factory", create_app)
    monkeypatch.setattr(server, "_validate_app_factory_import", lambda: None)
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "true")
    monkeypatch.setenv("PENGUIN_SERVER_ROLE", "test")
    monkeypatch.setenv("PENGUIN_WORKSPACE", str(tmp_path))
    monkeypatch.setenv(
        "PENGUIN_RUNTIME_EVENT_LEDGER_PATH",
        str(tmp_path / "runtime_events" / "runtime_events.db"),
    )

    assert server.main(["--debug"]) == 0

    output = capsys.readouterr().out
    assert "http://127.0.0.1:8080" in output
    assert calls[0][0][0] == "penguin.web.server:create_app_factory"
    assert calls[0][1]["reload"] is True
    assert calls[0][1]["factory"] is True
    assert calls[0][1]["port"] == 8080
    assert calls[0][1]["log_config"] is None
    assert app_factory_calls == 0


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
    local_auth_message = (
        "Browser/dashboard only: open this local authorization URL once "
        "for this browser."
    )
    assert local_auth_message in output
    assert "TUI/CLI: local Penguin sessions authenticate automatically." in output
    assert "CI/headless: use PENGUIN_API_KEYS with X-API-Key header auth." in output
    assert "PENGUIN_AUTH_ENABLED=false uv run penguin-web" in output
    assert calls[0][0][0] is app
    assert calls[0][1]["host"] == "127.0.0.1"
    assert calls[0][1]["port"] == 9000
    assert calls[0][1]["log_config"] is None


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
    local_auth_message = (
        "Browser/dashboard only: open this local authorization URL once "
        "for this browser."
    )
    assert local_auth_message in output
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


def test_main_continues_when_local_auth_token_cache_write_fails(
    monkeypatch, capsys, caplog
):
    calls = []
    app = object()

    fake_uvicorn = types.SimpleNamespace(
        run=lambda *args, **kwargs: calls.append((args, kwargs))
    )
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
    monkeypatch.setattr(server, "create_app_factory", lambda: app)
    monkeypatch.setattr(
        server,
        "write_local_auth_token",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.setenv("PORT", "9000")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "true")
    monkeypatch.delenv("PENGUIN_API_KEYS", raising=False)
    monkeypatch.setenv("PENGUIN_AUTH_STARTUP_TOKEN", "cached-startup-token")

    with caplog.at_level(logging.WARNING, logger="penguin.web.server"):
        assert server.main() == 0

    output = capsys.readouterr().out
    assert "http://127.0.0.1:9000/authorize#local_token=" in output
    assert any(
        "Failed to write local auth token cache" in x.message for x in caplog.records
    )
    assert calls[0][0][0] is app


def test_main_returns_error_for_invalid_port(monkeypatch, capsys):
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.setenv("PORT", "not-a-port")
    monkeypatch.setenv("DEBUG", "false")

    assert server.main() == 1

    output = capsys.readouterr().out
    assert "Invalid PORT value 'not-a-port'" in output


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
    assert calls[0][1]["log_config"] is None


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
