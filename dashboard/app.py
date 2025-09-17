"""Minimal Penguin telemetry dashboard (standalone FastAPI app)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from penguin.web.app import get_or_create_core
from penguin.telemetry.collector import ensure_telemetry

app = FastAPI(title="Penguin Telemetry Dashboard", version="0.1.0")


def _get_core():
    core = get_or_create_core()
    ensure_telemetry(core)
    return core


@app.get("/", response_class=HTMLResponse)
async def dashboard_page() -> HTMLResponse:
    html = Path(__file__).with_name("dashboard.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.get("/telemetry")
async def telemetry_summary(core=Depends(_get_core)) -> Dict[str, Any]:  # type: ignore[valid-type]
    try:
        summary = await core.get_telemetry_summary()
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=f"Failed to collect telemetry: {exc}") from exc
    return summary


@app.get("/telemetry/raw", response_class=HTMLResponse)
async def telemetry_raw(core=Depends(_get_core)) -> HTMLResponse:  # type: ignore[valid-type]
    summary = await core.get_telemetry_summary()
    formatted = json.dumps(summary, indent=2)
    return HTMLResponse(f"<pre>{formatted}</pre>")


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("dashboard.app:app", host="0.0.0.0", port=8081, reload=True)
