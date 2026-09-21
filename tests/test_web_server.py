import logging
import sys
import types
from unittest.mock import MagicMock

import pytest

from penguin.web import server


@pytest.fixture(autouse=True)
def disable_web_file_logging(monkeypatch, tmp_path):
    monkeypatch.setenv("PENGUIN_LOCAL_AUTH_CACHE_DIR", str(tmp_path / "auth"))
    monkeypatch.setenv("PENGUIN_WEB_LOG_ENABLED", "false")
    yield
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        if getattr(handler, server.SERVER_LOG_HANDLER_FLAG, False):
            root_logger.removeHandler(handler)
            handler.close()


def _mock_uvicorn(monkeypatch, calls):
    def config(app, **kwargs):
        sock = MagicMock()
        sock.__enter__.return_value = sock
        sock.getsockname.return_value = (kwargs["host"], kwargs["port"])
        return types.SimpleNamespace(
            app=app, backlog=128, bind_socket=lambda: sock, **kwargs
        )

    def runner(config):
        def run(**kwargs):
            calls.append(((config.app,), vars(config)))

        return types.SimpleNamespace(run=run, started=True)

    monkeypatch.setitem(
        sys.modules, "uvicorn", types.SimpleNamespace(Config=config, Server=runner)
    )
    monkeypatch.setitem(
        sys.modules,
        "uvicorn.supervisors",
        types.SimpleNamespace(
            ChangeReload=lambda config, target, sockets: types.SimpleNamespace(
                run=lambda: target(sockets=sockets)
            )
        ),
    )


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


def test_main_debug_uses_reload_safe_import_string(monkeypatch, capsys):
    calls = []

    _mock_uvicorn(monkeypatch, calls)
    monkeypatch.setattr(server, "create_app_factory", lambda: object())
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "true")

    assert server.main(["--debug"]) == 0

    output = capsys.readouterr().out
    assert "http://localhost:8080" in output
    assert calls[0][0][0] == "penguin.web.server:create_app_factory"
    assert calls[0][1]["reload"] is True
    assert calls[0][1]["factory"] is True
    assert calls[0][1]["port"] == 8080
    assert calls[0][1]["log_config"] is None


def test_main_defaults_to_localhost_without_auth(monkeypatch, capsys):
    calls = []
    app = object()

    _mock_uvicorn(monkeypatch, calls)
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

    _mock_uvicorn(monkeypatch, calls)
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

    _mock_uvicorn(monkeypatch, calls)
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

    _mock_uvicorn(monkeypatch, calls)
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

    _mock_uvicorn(monkeypatch, calls)
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

    _mock_uvicorn(monkeypatch, calls)
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

    _mock_uvicorn(monkeypatch, calls)
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


@pytest.mark.parametrize("debug", [False, True])
@pytest.mark.parametrize("entrypoint", ["main", "start_server"])
def test_busy_port_preserves_live_token(monkeypatch, tmp_path, debug, entrypoint):
    import socket

    import uvicorn

    from penguin.local_auth import write_local_auth_token

    monkeypatch.setenv("PENGUIN_LOCAL_AUTH_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "true")
    monkeypatch.setenv("PENGUIN_AUTH_STARTUP_TOKEN", "replacement-token")
    monkeypatch.delenv("PENGUIN_API_KEYS", raising=False)
    monkeypatch.setenv("DEBUG", "false")
    initialized = []
    monkeypatch.setattr(server, "create_app_factory", lambda: initialized.append(True))
    # Keep the old implementation bounded: it would otherwise start a real app.
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: None)
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        port = occupied.getsockname()[1]
        cache = write_local_auth_token("live-token", host="127.0.0.1", port=port)
        with pytest.raises(SystemExit):
            if entrypoint == "main":
                server.main(
                    ["--host", "127.0.0.1", "--port", str(port)]
                    + (["--debug"] if debug else [])
                )
            else:
                server.start_server(host="127.0.0.1", port=port, debug=debug)
        assert cache.read_text() == "live-token"
        assert not initialized


@pytest.mark.parametrize("debug", [False, True])
def test_startup_retains_socket_and_closes_it(monkeypatch, tmp_path, debug):
    import socket

    import uvicorn
    import uvicorn.supervisors

    from penguin.local_auth import read_local_auth_token

    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "true")
    monkeypatch.setenv("PENGUIN_AUTH_STARTUP_TOKEN", "new-test-token")
    monkeypatch.delenv("PENGUIN_API_KEYS", raising=False)
    sockets = []
    bind = uvicorn.Config.bind_socket

    def bind_socket(config):
        sock = bind(config)
        sockets.append(sock)
        return sock

    def assert_reserved():
        with socket.socket() as rival:
            with pytest.raises(OSError):
                rival.bind(sockets[0].getsockname())

    def create_app():
        assert_reserved()
        return object()

    def run(instance, *, sockets):
        assert_reserved()
        port = sockets[0].getsockname()[1]
        assert read_local_auth_token(host="127.0.0.1", port=port) == "new-test-token"
        instance.started = True

    def reload(config, target, sockets):
        assert config.app == "penguin.web.server:create_app_factory"
        assert config.factory is True
        return types.SimpleNamespace(run=lambda: target(sockets=sockets))

    monkeypatch.setattr(uvicorn.Config, "bind_socket", bind_socket)
    monkeypatch.setattr(server, "create_app_factory", create_app)
    monkeypatch.setattr(uvicorn.Server, "run", run)
    monkeypatch.setattr(uvicorn.supervisors, "ChangeReload", reload)
    server.start_server(port=0, debug=debug)
    assert len(sockets) == 1
    assert sockets[0].fileno() == -1


def test_app_initialization_failure_closes_socket_without_publishing(monkeypatch):
    import uvicorn

    sockets = []
    bind = uvicorn.Config.bind_socket

    def bind_socket(config):
        sock = bind(config)
        sockets.append(sock)
        return sock

    def fail():
        raise RuntimeError("app initialization failed")

    published = []
    monkeypatch.setattr(uvicorn.Config, "bind_socket", bind_socket)
    monkeypatch.setattr(server, "create_app_factory", fail)
    monkeypatch.setattr(
        server, "write_local_auth_token", lambda *a, **kw: published.append(kw)
    )
    with pytest.raises(RuntimeError, match="app initialization failed"):
        server.start_server(port=0)
    assert not published
    assert sockets[0].fileno() == -1


@pytest.mark.parametrize("debug", [False, True])
def test_ctrl_c_closes_socket_without_traceback(monkeypatch, debug):
    calls = []
    _mock_uvicorn(monkeypatch, calls)
    import uvicorn

    sock = MagicMock()
    sock.__enter__.return_value = sock
    sock.getsockname.return_value = ("127.0.0.1", 9010)
    original_config = uvicorn.Config

    def config(*args, **kwargs):
        result = original_config(*args, **kwargs)
        result.bind_socket = lambda: sock
        return result

    def interrupted(**kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(uvicorn, "Config", config)
    monkeypatch.setattr(
        uvicorn,
        "Server",
        lambda config: types.SimpleNamespace(run=interrupted, started=True),
    )
    monkeypatch.setattr(server, "create_app_factory", lambda: object())
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "false")
    server.start_server(port=9010, debug=debug)
    sock.__exit__.assert_called_once()
