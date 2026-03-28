# uv Exclude-Newer Compatibility Note

## Goal

- Keep the 7-day `exclude-newer` safety rail.
- Track the compatibility gap with older `uv` builds that fail to parse the friendly-duration project setting.

## Current State

- The repo intentionally keeps `[tool.uv] exclude-newer = "7 days"` in `pyproject.toml`.
- Some older `uv` versions can warn or fail while parsing that project setting.
- The documented intent is still correct; the practical fix is upgrading `uv` to a version that supports the setting in project metadata parsing.

## Immediate Plan

- Do not remove the 7-day guardrail.
- Treat this as an environment/tooling compatibility issue rather than an application-runtime bug.
- Keep the runtime fixes focused on provider auth and streaming/tool-call behavior.

## Follow-Up

- After local `uv` cleanup/upgrade, re-verify `uv run penguin-web` startup without the parse warning.
- If needed later, document a minimum supported `uv` version explicitly.
