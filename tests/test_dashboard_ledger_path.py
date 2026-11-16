"""The dashboard reads the runtime event ledger the server writes.

Covers SM-108 (dashboard): the dashboard built the ledger path from
``PENGUIN_WORKSPACE`` only, ignoring ``PENGUIN_RUNTIME_EVENT_LEDGER_PATH``,
so it could read a different database than the server wrote.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest

QUERIES = (
    Path(__file__).resolve().parents[1]
    / "penguin"
    / "dashboard"
    / "queries"
    / "runtime_events.py"
)


def test_the_dashboard_uses_the_server_ledger_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    streamlit: Any = ModuleType("streamlit")
    streamlit.cache_resource = lambda **_kwargs: lambda function: function
    monkeypatch.setitem(sys.modules, "streamlit", streamlit)
    ledger = tmp_path / "custom" / "events.db"
    monkeypatch.setenv("PENGUIN_RUNTIME_EVENT_LEDGER_PATH", str(ledger))
    # Loaded from its file: the dashboard package imports plotly components.
    spec = importlib.util.spec_from_file_location("dashboard_queries", QUERIES)
    assert spec is not None and spec.loader is not None
    queries = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(queries)

    assert queries.get_event_db_path() == str(ledger)
