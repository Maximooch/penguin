"""
Quick headless probe to verify that tool widgets don't reserve excess height.

Run: python -m penguin.cli.layout_probe
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

# Support running both as a module and a direct script.
try:  # when run as module: python -m penguin.cli.layout_probe
    from .widgets import ToolExecutionWidget
    from .widgets.unified_display import ExecutionAdapter, ExecutionStatus
except Exception:  # when run as script: python layout_probe.py
    pkg_root = Path(__file__).resolve().parents[1]  # inner 'penguin' package dir
    sys.path.insert(0, str(pkg_root))
    from penguin.cli.widgets import ToolExecutionWidget  # type: ignore
    from penguin.cli.widgets.unified_display import (  # type: ignore
        ExecutionAdapter,
        ExecutionStatus,
    )


class ProbeApp(App):
    CSS = """
    Screen { background: #0c141f; }
    #area { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="area")

    async def on_mount(self) -> None:
        exec_ = ExecutionAdapter.from_tool(
            "workspace_search",
            {"query": "needle in haystack", "max_results": 3},
            tool_id="probe-1",
        )
        exec_.status = ExecutionStatus.SUCCESS
        exec_.result = {
            "matches": [
                {"file": "a.py", "line": 1, "content": "def a(): pass"},
                {"file": "b.py", "line": 2, "content": "def b(): pass"},
            ],
            "total": 2,
        }

        widget = ToolExecutionWidget(exec_)
        self.query_one("#area", VerticalScroll).mount(widget)

        # Let layout settle
        await asyncio.sleep(0.1)

        # Report computed sizes
        tool_size = widget.size
        report: list[str] = [
            f"tool.height={tool_size.height}",
            f"tool.min_height={getattr(widget.styles, 'min_height', None)}",
        ]

        # Inspect collapsibles if present
        try:
            for col in widget.query("Collapsible").results():
                report.append(
                    f"collapsible '{col.title}' height={col.size.height} min_height={getattr(col.styles, 'min_height', None)}"
                )
        except Exception:
            pass

        print("; ".join(report))
        await asyncio.sleep(0.05)
        self.exit()


def main() -> None:
    ProbeApp().run(headless=True)


if __name__ == "__main__":
    main()


