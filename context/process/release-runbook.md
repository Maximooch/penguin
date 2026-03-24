# Penguin Release Runbook

## Goal

Ship a coordinated Penguin + Penguin TUI sidecar release after the OpenCode TUI
backend parity merge, with strong pre-release validation and a real clean-install
smoke test for `pip install "penguin-ai[tui]"`.

This runbook assumes the target release is `v0.6.1`. Replace the version string if
 needed.

## Preconditions

- You are on `main` and it is up to date.
- All intended post-merge fixes are already merged.
- GitHub CLI (`gh`), Python build tooling, and Bun are available locally.
- You are ready to do one manual clean-environment validation in GitHub Codespaces
  and one local clean-venv smoke test before the real tag push.

## 1. Sync and Inspect Main

```bash
git checkout main
git pull --ff-only origin main
git status
```

Expected:
- clean worktree
- branch is `main`

## 2. Run Focused Validation Locally

Run the core launcher/packaging and subagent/TUI parity suites first.

```bash
pytest -q tests/test_opencode_launcher.py tests/test_cli_entrypoint_dispatcher.py

pytest -q \
  tests/test_core_tool_mapping.py \
  tests/test_action_executor_subagent_events.py \
  tests/tools/test_sub_agent_tools.py \
  tests/multi/test_executor.py

pytest -q \
  tests/api/test_opencode_session_routes.py \
  tests/api/test_session_view_service.py \
  tests/api/test_concurrent_session_isolation.py

ruff check .
```

If any of these fail, stop and fix before continuing.

## 3. Run Mainline Workflow Dry Runs

### 3a. TUI sidecar workflow

Dispatch the TUI artifact workflow on `main`.

```bash
gh workflow run publish-tui.yml --ref main
gh run list --workflow publish-tui.yml --limit 5
gh run watch
```

What to verify:
- all expected platform jobs succeed
- sidecar archives are produced
- no branch-specific trigger assumptions remain

### 3b. Python publish workflow sanity check

Dispatch the Python publish workflow as a non-tag smoke check.

```bash
gh workflow run publish.yml --ref main
gh run list --workflow publish.yml --limit 5
gh run watch
```

What to verify:
- wheel/sdist build succeeds
- install smoke step succeeds

Note: without a tag, this is mainly a build/install confidence check, not a real
publish.

## 4. Prepare Release Notes

Summarize:
- OpenCode-compatible Penguin TUI integration
- launcher + sidecar bootstrap/cache/checksum flow
- session/history/tool/provider/auth parity improvements
- concurrent session hardening
- isolated subagent task-card + child-session routing parity
- known follow-ups (exact version-aware sidecar lookup validation, Windows baseline
  artifact decision, any deferred parity work)

## 5. GitHub Codespaces Clean-Install Test

This is the most important pre-release manual gate for the pip-installed path.

### 5a. Open a clean Codespace

- Start a fresh Codespace on `main`.
- Do not rely on editable install behavior.
- Do not test from inside a source tree that still lets the launcher prefer local
  `penguin-tui` sources.

### 5b. Build a wheel locally first (or from CI artifact)

From your local machine or the repo shell:

```bash
python -m build
ls dist/
```

You need the generated wheel available to the Codespace, either by:
- uploading it to the Codespace
- copying it into the Codespace workspace
- or downloading the artifact from CI if you prefer

### 5c. Install in a clean environment in Codespaces

Inside Codespaces, outside the repo checkout if possible:

```bash
mkdir -p ~/penguin-release-test
cd ~/penguin-release-test

python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip

pip install "/path/to/penguin_ai-0.6.1-py3-none-any.whl[tui]"
```

If shell extra syntax is awkward with a wheel path, use:

```bash
pip install "/path/to/penguin_ai-0.6.1-py3-none-any.whl"
pip install fastapi uvicorn websockets jinja2 python-multipart
```

Only use the fallback two-step install if needed for the environment.

### 5d. Validate installed path behavior

Check that local-source fallback is not masking sidecar bootstrap:

```bash
python - <<'PY'
from penguin.cli import opencode_launcher
print(opencode_launcher._find_local_opencode_dir())
PY
```

Expected:
- `None`, or at least not a path that would make this a local-source launch test

Now launch:

```bash
penguin --help
penguin .
```

What to verify:
- sidecar downloads into `~/.cache/penguin/tui`
- no Bun install is required
- launcher starts Penguin web and/or connects as expected
- TUI opens successfully

Check cache contents:

```bash
ls -R ~/.cache/penguin/tui
cat ~/.cache/penguin/tui/current.json
```

Verify:
- cached sidecar exists
- `current.json` points at the expected tagged release/version metadata

### 5e. Optional interactive validation

Inside the installed TUI, do one quick smoke test:
- create a session
- confirm streaming works
- if practical, confirm a lightweight background isolated subagent still opens a child
  session from a task card

If Codespaces passes, continue.

## 6. Local macOS Clean-Venv Test

Do one local non-editable install test on macOS before tagging.

```bash
mkdir -p ~/tmp/penguin-release-test
cd ~/tmp/penguin-release-test

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install "/absolute/path/to/dist/penguin_ai-0.6.1-py3-none-any.whl[tui]"

python - <<'PY'
from penguin.cli import opencode_launcher
print(opencode_launcher._find_local_opencode_dir())
PY

penguin .
```

Verify the same things as Codespaces:
- no local-source masking
- sidecar download/cache works
- launcher starts cleanly

## 7. Bump Version

Update version strings:

- `pyproject.toml`
- `penguin/_version.py`

Then verify:

```bash
grep -n "version =" pyproject.toml
grep -n "__version__" penguin/_version.py
```

## 8. Commit the Version Bump

```bash
git add pyproject.toml penguin/_version.py
git commit -m "chore: bump version to v0.6.1"
git push origin main
```

## 9. Create and Push the Release Tag

```bash
git tag -a v0.6.1 -m "Release v0.6.1"
git push origin v0.6.1
```

This should trigger:
- `.github/workflows/publish.yml`
- `.github/workflows/publish-tui.yml`

## 10. Watch Release Workflows

```bash
gh run list --limit 10
gh run watch
```

Verify:
- Python package publishes successfully
- TUI sidecar assets publish successfully
- release assets are attached to the same `v0.6.1` GitHub release

## 11. Post-Tag Verification

### GitHub release assets

```bash
gh release view v0.6.1
gh release download v0.6.1 --dir /tmp/penguin-release-assets --pattern "*.zip"
gh release download v0.6.1 --dir /tmp/penguin-release-assets --pattern "*.tar.gz"
ls -lah /tmp/penguin-release-assets
```

### PyPI availability

```bash
python -m pip index versions penguin-ai | head -40
```

## 12. If Something Fails

### Sidecar workflow fails

- inspect `.github/workflows/publish-tui.yml`
- inspect platform-specific sidecar artifact names vs `_sidecar_platform_candidates()` in
  `penguin/cli/opencode_launcher.py`

### Installed launcher still uses local source unexpectedly

- check `PENGUIN_OPENCODE_DIR`
- ensure you are not running from a checkout that contains `penguin-tui/packages/opencode`
- confirm `_find_local_opencode_dir()` returns `None`

### Exact-version lookup fails

- confirm the GitHub release tag exists: `v0.6.1`
- confirm sidecar assets were attached to that exact release
- inspect `~/.cache/penguin/tui/current.json`

### PyPI package is live but sidecar assets are missing

- do not treat the release as fully validated
- either patch the GitHub release assets immediately or cut a follow-up release after fix

## Exit Criteria

The release is good when all of the following are true:

- targeted tests pass locally
- workflow dry runs on `main` pass
- Codespaces clean-install test passes
- local macOS clean-venv test passes
- `v0.6.1` tag publishes both Python package and matching sidecar assets
- the installed launcher pulls a version-matched sidecar by default
