.PHONY: sync-safe sync-latest lock-safe lock-latest

# Default path: respect `pyproject.toml`'s `[tool.uv] exclude-newer = "7 days"`.
sync-safe:
	uv sync

# Refresh the lockfile while respecting the default safety rail.
lock-safe:
	uv lock --upgrade

# Intentional override: allow the newest compatible releases for emergency updates.
# Using a far-future timestamp effectively disables the 7-day age filter for this run.
lock-latest:
	uv lock --upgrade --exclude-newer 2999-12-31T23:59:59Z

# Install from the newest compatible lockfile, bypassing the default age filter.
sync-latest: lock-latest
	uv sync --exclude-newer 2999-12-31T23:59:59Z
