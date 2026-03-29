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
