# Web Startup LibreSSL / urllib3 Investigation Note

## Summary

`uv run penguin-web` currently emits an `urllib3` warning on this machine, but the server still starts successfully.

## Confirmed Findings

- `uv` re-resolves even with an existing lockfile because the repo now defines `[tool.uv] exclude-newer = "7 days"` in `pyproject.toml`.
- That behavior matches the startup message: `Resolving despite existing lockfile due to addition of global exclude newer ...`.
- The SSL warning is **not** caused by Penguin web server failure. It is an environment/runtime compatibility warning.

## Root Cause

- Runtime Python in the local `.venv` is linked against `LibreSSL 2.8.3`.
- Installed packages include:
  - `requests 2.32.4`
  - `urllib3 2.5.0`
- `urllib3 v2` warns when Python is built against LibreSSL instead of OpenSSL 1.1.1+.

## Import Chain Triggering the Warning

The warning appears during web startup because startup imports pull in `requests` earlier than necessary:

- `penguin/web/app.py` imports `ToolManager`
- `penguin/tools/tool_manager.py` eagerly imports `PerplexityProvider`
- `penguin/tools/core/perplexity_tool.py` imports `requests`
- `requests` imports `urllib3`
- `urllib3` emits `NotOpenSSLWarning`

## Practical Interpretation

- This is currently a **warning**, not a startup blocker.
- The deeper issue is a combination of:
  - environment SSL backend mismatch (`LibreSSL`)
  - eager import coupling in tool startup path

## Deferred Fix Options

### Environment-level fix

Use a Python build linked against OpenSSL and recreate the virtual environment.

### Code-level fix

Lazy-load the Perplexity provider so `requests` is not imported during normal web startup unless that tool is actually used.

## Current Decision

Do **not** prioritize this now.
Keep this note as a reminder for later cleanup while focusing on higher-leverage work first.
