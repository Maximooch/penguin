# Penguin Web Server & TUI Startup Performance Plan

**Status:** Proposed
**Scope:** `penguin-web` cold/warm startup, TUI launcher path, TUI bootstrap fetches
**Primary surfaces:** `penguin.web.server`, `penguin.web.app`, `penguin.core_runtime.startup`,
`penguin.system.session_manager`, `penguin.cli.opencode_launcher`, `penguin-tui` bootstrap
**Goal:** Make a cold `penguin` (TUI) start feel immediate, and make `penguin-web`
bind its port and answer `/api/v1/health` in low single-digit seconds regardless of
how many historical sessions the workspace holds.

## Executive summary

Startup cost is dominated by one synchronous, workspace-scaling operation on the
critical path before uvicorn binds the port:

1. **Session-index rebuild parses every conversation JSON file at boot.**
   `_load_or_create_index()` → `_session_index_is_stale()` → `_rebuild_index()`
   (`penguin/system/session_manager.py`). On this checkout's real workspace
   (3,453 files, 1.5 GB), a rebuild costs **5.2–6.6 s** measured repeatedly.
2. **The staleness check is too fragile for a multi-process reality.**
   Any divergence — one deleted file whose index entry lingers, or any session
   file written by another live Penguin process between index save and boot —
   flips the whole index to "stale" and forces the full rebuild. A running
   server + a second boot is the normal daily case (launcher autostart, dev
   restarts), so the rebuild path fires far more often than "corrupt index" ever
   justified. The staleness check itself (glob + stat of 3,453 files) still
   costs ~0.2 s even when it passes.
3. **Core construction happens synchronously inside FastAPI app creation.**
   `create_app()` → `get_or_create_core()` → `PenguinCore.create()` runs to
   completion *before* uvicorn binds the port. Nothing is reachable — not even
   `/api/v1/health` used by the launcher's readiness loop — until all of core
   init finishes.
4. **Module imports add ~1.3–2.9 s**, including several that do not belong on
   the web-server path: IPython (~200 ms via `utils/notebook.py`, imported
   eagerly by `tools/tool_manager.py` despite lazy instantiation), PyGithub
   (~78 ms via `project/git_manager.py` → `repository_tools.py`), networkx
   (~130 ms), prompt_toolkit (~67 ms).
5. **The TUI side adds little Python-side overhead** (launcher warm overhead
   ~112 ms; bootstrap fetches already parallelized with `Promise.all`) but
   inherits the full server wait when no server is running: measured cold
   spawn-to-health **10.3 s** (unprofiled) / **10.8 s** under cProfile.

Measured on this checkout on August 25, 2026 (macOS, Python 3.12):

| Measurement | Result |
|---|---:|
| Cold `python -m penguin.web.server` → first 200 from `/api/v1/health` | **10.3 s** |
| Same, empty temp workspace | **2.5 s** |
| `create_app()` total (in-process, warm OS cache) | 6.1–7.6 s |
| └ `_load_or_create_index` → `_rebuild_index` (3,453 JSON files) | **5.2–6.6 s** |
| └ `PenguinCore.__init__` excluding index rebuild | ~0.5 s |
| Module import of `penguin.web.server` | 1.3–1.6 s |
| Fresh-index boot path (glob+stat staleness pass) | ~0.22 s |
| Warm launcher Python overhead (health probe + auth env + cmd build) | ~112 ms |
| Live bootstrap endpoints: `/path` | **667 ms** (253 B payload) |
| Live bootstrap endpoints: `/vcs`, `/lsp`, `/config/providers` | 164 / 134 / 44 ms (338 KB) |

## Root causes

### RC1 — Index staleness policy converts routine concurrency into a 5–7s penalty

`_session_index_is_stale()` returns true if either:
- the set of session-file stems differs from index keys (one stale entry after
  an out-of-band delete = full rebuild), or
- any session file mtime > index mtime (any concurrent writer between index
  save and next boot = full rebuild).

Both conditions are routine in a multi-process setup (live :9000 server while
launching a second instance; crash between file write and index update). The
index is rebuilt by re-parsing **every** session file with stdlib `json.load`.

### RC2 — Core init sits before port bind

`server.main()` → `uvicorn.run(factory=...)`-shaped flow where the factory
(`create_app_factory` → `create_app`) calls `get_or_create_core()`. Uvicorn's
lifespan would allow deferred init; today the health endpoint — the launcher's
readiness signal — cannot respond until core exists.

### RC3 — Eager heavy imports on the web path

Import chain evidence (`-X importtime`):
- `penguin.web.app` → `penguin.tools.tool_manager` → `penguin.utils.notebook`
  → **IPython** (~200 ms). NotebookExecutor is instantiated lazily via property;
  only the module import is eager.
- `penguin.tools.repository_tools` → `penguin.project.git_manager` →
  **PyGithub** (~78 ms). Import is failure-guarded but not cost-guarded.
- `penguin.project.manager` → **networkx** (~130 ms) — needed eventually for
  task DAGs but not during the first hundreds of milliseconds.
- CLI-only modules (`prompt_toolkit` via cli modules) appear in some paths.

### RC4 — Bootstrap endpoints block the event loop

`/path`, `/vcs`, `/formatter`, `/lsp` routes are `async def` but call
`_run_git(...)` = `subprocess.run(...)` directly (2s timeout each). Measured
`/path` p50 ≈ 667 ms on a busy server; these run serially-ish during TUI
bootstrap alongside the parallel fetches.

## Recommendations (ordered by leverage)

### P0 — Make the index rebuild impossible to hit on the hot path

1. **Repair-forward instead of rebuild-on-mismatch.** When the key-set differs,
   reconcile incrementally: stat-only pass to find added/removed/modified files;
   parse *only* those files; merge into the existing index; save. A single new
   session then costs one file parse (~ms), not 3,453.
2. **Move the freshness scan off the request/boot critical path.** Options in
   increasing ambition:
   a. Accept the index optimistically, schedule a background reconciliation
      task post-startup (uvicorn lifespan or the existing auto-save thread),
      emit `server.replay_gap`-style correction if listing changes.
   b. Store per-session metadata as small sidecar files (e.g.
     `<id>.meta.json` written alongside the transcript) so listing never needs
      to open transcripts at all; keep `session_index.json` as a derived cache.
3. **Harden against the missing-file case:** treat index entries without files
   as prunable during background reconciliation, not as a boot-time emergency.

*Acceptance:* with 3,500+ sessions and a concurrently-running writer, a fresh
boot logs no `Rebuilding session index` and reaches healthy in ≤ 4 s.

### P0 — Defer core construction until after uvicorn binds

Bind first, serve `/api/v1/health` immediately with a `status: starting`
payload, construct core in a background task, flip readiness when done. The
launcher's `_wait_for_server` loop then succeeds early; the TUI's own bootstrap
already retries/degrades gracefully (`fetchBootstrapJson` optional-failure
semantics). Endpoints needing core can await an asyncio event with a timeout.

This alone removes most of the *perceived* latency from the TUI cold-start path
and unblocks container orchestrations that use health-gated readiness.

*Caveat:* keep auth middleware ordering correct so the starting-state health
response remains reachable under local-auth defaults.

### P1 — Lazy-import the heavy web-path modules

- `tool_manager.py`: move `from penguin.utils.notebook import NotebookExecutor`
  into the `notebook_executor` property (pattern already used for the instance).
- `repository_tools.py`: defer PyGithub import into functions (or gate behind
  tool registration when the repo tools are actually enabled).
- Evaluate deferring `networkx` in `project/manager.py` to DAG-construction
  call sites.

Expected saving ~300–400 ms of import time plus reduced memory footprint.

### P1 — Faster parse path for the remaining bulk reads

Add `orjson` as a dependency and use it in `session_manager` bulk paths
(measured ~2× on this machine's mixed-size sample). Keep stdlib `json` for
small/single-file operations where import cost matters more than speed.
Pair with P0.1 so bulk parsing becomes rare rather than routine.

### P2 — Stop rewriting the 800KB index on every message save

`save_session` currently updates the in-memory index and rewrites
`session_index.json` atomically per save. Batch/debounce index persistence
(e.g., piggyback on the existing auto-save thread cadence, flush on shutdown)
while keeping the atomic-rename safety. This reduces steady-state disk churn
and shrinks the window that makes other processes' staleness checks fail.

### P2 — Move blocking git subprocesses off the event loop

`system_status._run_git` callers should use `asyncio.to_thread(...)` or cached
results (branch/worktree rarely change within seconds). This mirrors the
existing file-search plan's lifecycle-service direction.

### P3 — Trim the bootstrap payload

`/config/providers` returns 338 KB and `/provider` 155 KB at every TUI start.
Cache headers (these are effectively static per process lifetime) or an
ETag/If-None-Match exchange would cut transfer and client parse time. Verify
against the TUI's normalization code before changing shapes.

## Non-goals

- No change to the on-disk session format or index schema in P0/P1 (sidecar
  metadata in P0.2b is opt-in future work).
- No provider/network behavior changes.
- No TUI-side protocol redesign; the alignment plan owns that.

## Verification plan

Deterministic, no live-provider dependency:

1. Unit tests around `SessionManager._load_or_create_index`: fresh dir, valid
   index, one-added-file, one-removed-file, concurrent-writer mtimes — assert
   no full-parse path (patch `json.load` counter or time the call).
2. Boot-time regression test: create N synthetic session files (e.g., 200),
   measure `_load_or_create_index` wall time stays flat vs N after P0.1.
3. Web smoke: spawn server on a non-reserved port against a synthetic
   workspace; assert health 200 < 4 s and no rebuild log line.
4. Existing suites: `pytest tests -q`; targeted additions under
   `tests/system/` next to current session-manager coverage.

## Open questions

- Should the launcher prefer `PENGUIN_WEB_URL` reachability over spawning when
  a foreign server occupies :9000? (Today it health-checks the URL, which is
  correct, but the 0.25s blind sleep in `_start_web_server` could race.)
- Is there a supported deployment mode where conversations live on slow NFS?
  If yes, sidecar metadata (P0.2b) becomes materially more valuable.
