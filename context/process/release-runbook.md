# Penguin Release Runbook

## Goal

Ship a coordinated Penguin + Penguin TUI sidecar release after the OpenCode TUI
backend parity merge, with strong pre-release validation and a real clean-install
smoke test for `pip install "penguin-ai[tui]"`.

This runbook assumes the target release is `v0.6.2.2`. Replace the version string if
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
  tests/api/test_opencode_v2_routes.py \
  tests/api/test_opencode_v2_events.py

pytest -q tests/api/test_web_auth_hardening.py \
  -k 'opencode_basic or startup_token_from_non_loopback'

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

For an opt-in OpenCode 2 release, dispatch the isolated workflow separately:

```bash
gh workflow run publish-tui-v2.yml --ref main
v2_run_id="$(
  gh run list --workflow publish-tui-v2.yml --event workflow_dispatch \
    --branch main --limit 1 --json databaseId --jq '.[0].databaseId'
)"
gh run watch "$v2_run_id" --exit-status
```

Verify that every archive is named `opencode2-<platform>`, contains
`opencode2` (or `opencode2.exe`), reports the pinned prerelease from
`--version`, and has an entry in `opencode2-SHA256SUMS.txt`. Never accept a
similarly numbered package that contains the older `lildax` binary.

Download the complete manual-run artifact and smoke the exact sidecar that will
be attached to the release. This example selects Apple Silicon; choose the
matching archive on another host.

```bash
v2_smoke_root="$(mktemp -d)"
gh run download "$v2_run_id" --name opencode2-v2-release-assets \
  --dir "$v2_smoke_root/artifacts"
(
  cd "$v2_smoke_root/artifacts"
  shasum -a 256 -c opencode2-SHA256SUMS.txt
)
unzip -q "$v2_smoke_root/artifacts/opencode2-darwin-arm64.zip" \
  -d "$v2_smoke_root/sidecar"

test "$("$v2_smoke_root/sidecar/bin/opencode2" --version)" = \
  "opencode2 v0.0.0-next-17220"
test -f "$v2_smoke_root/sidecar/plugins/tui/penguin.tsx"

PENGUIN_TUI_V2=1 \
PENGUIN_TUI_BIN_PATH="$v2_smoke_root/sidecar/bin/opencode2" \
OPENCODE_CONFIG_DIR="$v2_smoke_root/sidecar" \
  penguin .
```

In the TUI, run `/penguin` and confirm the Penguin status command appears and
shows the active project. Do not tag unless this extracted-artifact smoke passes.

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

pip install "/path/to/penguin_ai-0.6.2.2-py3-none-any.whl"
```

If you specifically want to verify the legacy compatibility alias still works, use:

```bash
pip install "/path/to/penguin_ai-0.6.2.2-py3-none-any.whl[tui]"
```

The base wheel should now be enough for the default `penguin` launcher path.

If you specifically need the optional LiteLLM path during validation, install it explicitly:

```bash
pip install "penguin-ai[llm_litellm]"
```

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

Repeat the packaged smoke with the manual-workflow V2 sidecar from section 3.
Copy or download that extracted directory into the Codespace, then point the
launcher at it explicitly:

```bash
PENGUIN_TUI_V2=1 \
PENGUIN_TUI_BIN_PATH="/path/to/v2-sidecar/bin/opencode2" \
OPENCODE_CONFIG_DIR="/path/to/v2-sidecar" \
  penguin .
```

Verify Home loads, a text prompt streams to completion, restart reconnects,
and unsetting `PENGUIN_TUI_V2` immediately launches V1 with its original cache.
An explicit binary intentionally bypasses the V2 cache marker; automatic V2
bootstrap and `v2/current.json` are post-tag gates in section 11, after the
matching release assets exist.

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
pip install "/absolute/path/to/dist/penguin_ai-0.6.2.2-py3-none-any.whl"

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
git commit -m "chore: bump version to v0.6.2.2"
git push origin main
```

## 9. Create and Push the Release Tag

```bash
git tag -a v0.6.2.2 -m "Release v0.6.2.2"
git push origin v0.6.2.2
```

This should trigger:
- `.github/workflows/publish.yml`
- `.github/workflows/publish-tui.yml`
- `.github/workflows/publish-tui-v2.yml`

## 10. Watch Release Workflows

```bash
gh run list --limit 10
gh run watch
```

Verify:
- Python package publishes successfully
- V1 and V2 TUI sidecar workflows publish successfully
- release assets are attached to the same `v0.6.2.2` GitHub release

## 11. Post-Tag Verification

### GitHub release assets

```bash
gh release view v0.6.2.2
gh release download v0.6.2.2 --dir /tmp/penguin-release-assets --pattern "*.zip"
gh release download v0.6.2.2 --dir /tmp/penguin-release-assets --pattern "*.tar.gz"
gh release download v0.6.2.2 --dir /tmp/penguin-release-assets \
  --pattern "opencode2-SHA256SUMS.txt"
ls -lah /tmp/penguin-release-assets
(
  cd /tmp/penguin-release-assets
  shasum -a 256 -c opencode2-SHA256SUMS.txt
)
```

Confirm all 11 `opencode2-*` archives and the checksum file are present. Then
run the post-tag automatic-bootstrap gate from a clean installed environment:

```bash
PENGUIN_TUI_V2=1 penguin .
cat ~/.cache/penguin/tui/v2/current.json
```

Verify the marker records protocol generation `v2`, the pinned upstream and
artifact identities, and the selected platform archive. Unset
`PENGUIN_TUI_V2` and verify the V1 marker and launcher remain unchanged.

### PyPI availability

```bash
python -m pip index versions penguin-ai | head -40
```

## 12. If Something Fails

### Sidecar workflow fails

- inspect `.github/workflows/publish-tui.yml` and
  `.github/workflows/publish-tui-v2.yml`
- inspect platform-specific sidecar artifact names vs `_sidecar_platform_candidates()` in
  `penguin/cli/opencode_launcher.py`

### Installed launcher still uses local source unexpectedly

- check `PENGUIN_OPENCODE_DIR`
- ensure you are not running from a checkout that contains `penguin-tui/packages/opencode`
- confirm `_find_local_opencode_dir()` returns `None`

### Exact-version lookup fails

- confirm the GitHub release tag exists: `v0.6.2.2`
- confirm sidecar assets were attached to that exact release
- inspect `~/.cache/penguin/tui/current.json`
- for V2, inspect `~/.cache/penguin/tui/v2/current.json` and the
  `opencode2-SHA256SUMS.txt` release asset

### PyPI package is live but sidecar assets are missing

- do not treat the release as fully validated
- either patch the GitHub release assets immediately or cut a follow-up release after fix

## Exit Criteria

The release is good when all of the following are true:

- targeted tests pass locally
- workflow dry runs on `main` pass
- Codespaces clean-install test passes
- local macOS clean-venv test passes
- `v0.6.2.2` tag publishes both Python package and matching sidecar assets
- the installed launcher pulls a version-matched sidecar by default
- the opt-in V2 launcher verifies and caches one of the 11 pinned V2 archives
  without changing the V1 cache or default
