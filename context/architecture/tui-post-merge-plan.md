# Penguin TUI Post-Merge Plan

## Goal

Stabilize the pip-installed Penguin TUI path after the OpenCode parity branch lands on
`main`, with special focus on sidecar artifact publishing and version-aware lookup for
`penguin-ai[tui]` installs.

## Current State

- Local-source TUI launches already work via `PENGUIN_OPENCODE_DIR` or an in-repo
  `penguin-tui/packages/opencode` checkout.
- Non-dev installs already support sidecar bootstrap, cache, and checksum validation
  through `penguin/cli/opencode_launcher.py`.
- The current bootstrap path resolves sidecars from Penguin GitHub `releases/latest`.
- The TUI artifact workflow still includes a temporary branch-specific trigger that
  should be removed after merge.
- Exact installed-version coupling between `penguin-ai` and Penguin TUI sidecar assets
  is still the main remaining packaging/release gap.

## Merge Readiness Checklist

- [ ] Confirm the current launcher-side sidecar bootstrap behavior is acceptable for
      merge as an interim path.
- [ ] Call out in the PR description that stable pip installs still use `latest`
      release lookup until version-aware lookup lands.
- [ ] Keep `I2.e` in `context/architecture/tui-opencode-implementation.md` updated so
      post-merge packaging work is visible.
- [ ] Confirm the current `publish-tui` temporary branch trigger is intentionally left
      in place only until merge.
- [ ] Confirm Windows baseline sidecar coverage remains a documented follow-up and not
      a hidden blocker.

## Immediate Post-Merge Checklist

- [ ] Remove the temporary branch-specific trigger from
      `.github/workflows/publish-tui.yml`.
- [ ] Ensure tagged releases publish both:
  - [ ] Python package artifacts via `.github/workflows/publish.yml`
  - [ ] matching TUI sidecar assets via `.github/workflows/publish-tui.yml`
- [ ] Verify the first merged tag produces all expected sidecar archives for supported
      platforms.
- [ ] Verify GitHub release pages contain the sidecar assets needed by the launcher.
- [ ] Run a fresh-machine smoke test for `pip install "penguin-ai[tui]"`.

## Version-Aware Lookup Checklist

### 1. Lookup Policy

- [ ] Stable installs should prefer the exact installed `penguin-ai` version.
- [ ] Dev installs should continue preferring local source and explicit overrides.
- [ ] Keep launcher precedence explicit:
  1. `PENGUIN_TUI_BIN_PATH`
  2. local source / `PENGUIN_OPENCODE_DIR`
  3. exact Penguin release asset for installed version
  4. explicit `PENGUIN_TUI_RELEASE_URL` override
  5. global `opencode` only when explicitly requested

### 2. Installed Version Resolution

- [ ] Read installed package version from Python package metadata at runtime.
- [ ] Query `releases/tags/v{installed_version}` before any fallback to `latest`.
- [ ] Fail clearly when a matching release exists but does not contain a compatible
      sidecar asset for the current platform.
- [ ] Decide whether `latest` fallback is allowed for stable installs or reserved for
      explicit opt-in / developer overrides.

### 3. Release Coupling

- [ ] Standardize on one GitHub release tag per Penguin version (`vX.Y.Z`).
- [ ] Publish Python package and TUI sidecar assets from the same release tag.
- [ ] Keep sidecar asset names stable and platform-detectable.
- [ ] Ensure release notes/process make it hard to publish Python without the matching
      sidecar set.

### 4. Compatibility Contract

- [ ] Keep the current `--url` compatibility check.
- [ ] Decide whether to add a stronger compatibility contract, such as a manifest or
      embedded version metadata.
- [ ] If added, validate at least:
  - [ ] Penguin package version
  - [ ] TUI build version
  - [ ] supported launcher/protocol mode
  - [ ] artifact digest or manifest digest

### 5. Cache Behavior

- [ ] Make cache markers explicitly release-aware.
- [ ] Invalidate or bypass stale cached sidecars when installed Penguin version changes.
- [ ] Keep cached override behavior predictable when users intentionally pin a binary
      path or custom release URL.

### 6. Checksum / Integrity

- [ ] Confirm release asset digest metadata is present and reliable for production
      GitHub releases.
- [ ] If GitHub digest metadata is insufficient, publish an explicit checksum or
      manifest file and verify against that.
- [ ] Keep unsafe archive path protections in place for zip/tar extraction.

## Validation Checklist

### Fresh Install Validation

- [ ] On a clean machine or clean virtualenv, run `pip install "penguin-ai[tui]"`.
- [ ] Launch `penguin` without local `penguin-tui` sources present.
- [ ] Confirm the sidecar downloads into `~/.cache/penguin/tui` (or configured cache).
- [ ] Confirm checksum verification succeeds.
- [ ] Confirm the launcher starts the TUI against Penguin web successfully.

### Upgrade / Downgrade Validation

- [ ] Install one Penguin version, launch once, and confirm cache population.
- [ ] Upgrade to a newer Penguin version and confirm the launcher does not silently
      reuse an incompatible older sidecar.
- [ ] If downgrades are supported, verify cache/version behavior there too.

### Platform Validation

- [ ] macOS arm64
- [ ] macOS x64
- [ ] Linux x64
- [ ] Linux arm64 if supported in release verification
- [ ] Windows x64
- [ ] Revisit Windows baseline coverage after release stabilization

## Suggested Execution Order

1. Merge branch to `main`
2. Remove temporary branch trigger from `publish-tui.yml`
3. Cut one tagged release that publishes both Python and TUI artifacts
4. Switch stable launcher lookup from `latest` to exact installed version
5. Validate fresh `penguin-ai[tui]` installs on clean environments
6. Decide whether stronger version/manifest compatibility checks are needed
7. Restore or explicitly retire Windows baseline artifact coverage

## Non-Goals For The First Post-Merge Pass

- Reworking local-source developer override behavior
- Replacing the current sidecar bootstrap design
- Broad packaging dependency slimming unrelated to TUI startup
- Polishing unrelated TUI parity items that do not affect artifact bootstrap

## Success Criteria

- A fresh `pip install "penguin-ai[tui]"` can launch Penguin TUI without a local
  `penguin-tui` checkout.
- The downloaded sidecar matches the installed Penguin version by default for stable
  installs.
- The launcher cache behaves predictably across upgrades.
- Tagged releases consistently publish both Python artifacts and matching TUI sidecars.
