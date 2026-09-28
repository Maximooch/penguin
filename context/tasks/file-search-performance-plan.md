# Penguin TUI / Webserver File Search Performance Plan

**Status:** Proposed  
**Scope:** `@` file autocomplete and `/find/file` (`/api/v1/find/file`)  
**Primary surfaces:** Penguin TUI, Penguin FastAPI webserver  
**Goal:** Make warm file search feel immediate and prevent file indexing from stalling the webserver.

## Executive summary

The current path is slow for structural reasons, not because file search inherently needs to be slow:

1. The TUI calls the webserver again whenever the active `@` query changes.
2. The FastAPI `async` route performs blocking filesystem traversal and CPU-heavy scoring on the event-loop thread.
3. The server cache expires every five seconds and rebuilds the entire tree synchronously.
4. The expiry timestamp is calculated before the scan. If a scan takes longer than five seconds, the newly stored entry is already expired.
5. Cache misses are not single-flight, so concurrent requests can independently scan the same directory.
6. Every warm query lowercases and decomposes every path, scores the full corpus in Python, stores all matches, and fully sorts them even though the UI normally needs only ten results.
7. The TUI has no explicit request debounce/cancellation policy, so fast typing can create avoidable work and stale in-flight responses.

Measured on this checkout on August 25, 2026:

- Python `os.walk` index build after the current skip rules: **~1.1–1.65 seconds** for **54,262 files + 8,108 directories**.
- Warm Python fuzzy query over those 62,370 entries: **~48–81 ms per query** before HTTP and rendering overhead.
- `rg --files --hidden -g '!.git/*'`: **~20–30 ms** as a comparison point.
- `git ls-files -co --exclude-standard`: **~50–100 ms** as another comparison point.

The recommended design is a lifecycle-owned `FileSearchService` in the Python backend. It should build one immutable index per active workspace, keep it fresh from filesystem events, and make requests query already-normalized entries. TUI changes should reduce duplicate requests, but the server must be fast independently; debouncing a slow backend only makes the delay arrive slightly later.

## Performance targets

Measure these on synthetic 10k, 100k, and 250k-entry workspaces and on this repository.

| Path | Target |
|---|---:|
| Warm server query, 100k entries, common 2+ character query | p50 <= 10 ms, p95 <= 25 ms |
| Warm server query, worst-case fuzzy fallback, 100k entries | p95 <= 60 ms |
| Local TUI keypress to updated suggestions | p50 <= 40 ms, p95 <= 80 ms |
| Cold Git/ripgrep-backed index build, 100k entries | p95 <= 250 ms |
| Cold Python fallback scan | No event-loop blocking; report separately rather than hiding it |
| Index freshness after create/delete/move | <= 250 ms normally |
| Duplicate concurrent cold requests | Exactly one index build per normalized root |
| Event-loop stall caused by indexing/search | No blocking section above 20 ms |

“Near instant” should mean warm search is normally below a terminal frame or two. Cold search cannot be guaranteed instant on every filesystem, especially network mounts, so Penguin should prewarm likely workspaces and never block unrelated requests while building.

## Current flow and ownership

```text
TUI prompt autocomplete / DialogTag
  -> sdk.client.find.files({ query, directory, session_id })
  -> GET /find/file
  -> resolve session-authoritative directory
  -> _get_find_file_index(directory)
       -> five-second cache hit, or synchronous os.walk
  -> score every selected file/directory
  -> sort every match
  -> return top 10
  -> TUI applies frecency/depth ordering and renders
```

Relevant code:

- `penguin-tui/packages/opencode/src/cli/cmd/tui/component/prompt/autocomplete.tsx`
- `penguin-tui/packages/opencode/src/cli/cmd/tui/component/dialog-tag.tsx`
- `penguin/web/routes.py` (`_scan_find_file_index`, `_get_find_file_index`, `_search_find_file_items`, `opencode_find_files`)
- `tests/api/test_find_file_routes.py`
- `penguin-tui/packages/opencode/src/file/index.ts` is useful upstream/reference behavior, but the active Penguin TUI calls the Python API and the Python backend must retain workspace/session authority.

The architecture documents require API-first behavior and thin UI clients. Therefore the canonical index belongs in the backend service layer, not only in TUI process memory. This also preserves remote/attach-mode behavior, where the TUI may not share the server filesystem.

## Proposed target architecture

```text
FastAPI lifespan
  -> FileSearchService.start()
       -> shared watchdog observer
       -> workspace-index LRU

session/workspace becomes active
  -> FileSearchService.prewarm(root)       # asynchronous, single-flight

GET /find/file
  -> existing session-authoritative root resolution
  -> await FileSearchService.search(root, query, kind, limit)
       -> immutable current snapshot
       -> normalized/precomputed entry fields
       -> staged candidate selection
       -> bounded top-K ranking
       -> small query-result LRU
  -> return results

filesystem create/delete/move
  -> debounce event batch
  -> copy-on-write snapshot update
  -> atomically publish new generation

watcher overflow/error or uncertain bulk change
  -> mark index dirty
  -> keep serving previous snapshot
  -> rebuild once in background
```

Create `penguin/web/services/file_search.py` rather than growing `routes.py`. The route should only validate parameters, resolve the authoritative directory, and call the service.

### Suggested core types

```python
@dataclass(frozen=True, slots=True)
class SearchEntry:
    path: str
    normalized: str
    basename: str
    basename_normalized: str
    is_directory: bool
    is_hidden: bool
    depth: int

@dataclass(frozen=True, slots=True)
class IndexSnapshot:
    generation: int
    built_at: float
    entries: tuple[SearchEntry, ...]
    file_ids: tuple[int, ...]
    directory_ids: tuple[int, ...]
    # Optional compact candidate indexes added only after benchmarking.

@dataclass
class WorkspaceIndex:
    root: str
    snapshot: IndexSnapshot | None
    build_task: asyncio.Task[IndexSnapshot] | None
    dirty: bool
    last_access: float
    query_cache: LRUCache
```

Use immutable snapshots and atomic reference replacement. Requests should not hold the mutation lock while scoring, and watcher updates should not mutate a list being read by another request.

## Implementation phases

## Phase 0 — Add evidence and protect the event loop

This is the smallest safe first PR and should land before deeper tuning.

1. Add opt-in timings around:
   - directory resolution;
   - index hit/miss;
   - scan duration and entry count;
   - candidate selection/scoring;
   - total endpoint duration;
   - index generation and dirty state.
2. Add a repeatable benchmark script or pytest benchmark helper for 10k/100k/250k generated paths. Do not make microbenchmark thresholds part of ordinary CI on shared runners; record results in a dedicated performance job or manual command.
3. Move blocking index construction to `asyncio.to_thread` immediately.
4. Add per-root single-flight construction so simultaneous misses await one task.
5. Fix cache expiry to be based on build completion, not build start.
6. Serve a still-valid previous snapshot while a refresh happens in the background (“stale while revalidate”) rather than stopping a keystroke on a rescan.
7. Keep existing session/directory conflict behavior unchanged.

**Why first:** This removes event-loop starvation and scan stampedes even before the final index exists. It is a low-risk production safety improvement.

**Do not call Phase 0 complete merely by increasing the TTL.** A larger TTL hides rescans but leaves cold requests, process restarts, query CPU, and stale-data behavior unresolved.

## Phase 1 — Extract a backend `FileSearchService`

1. Move indexing, cache ownership, ranking, and invalidation out of `routes.py` into `penguin/web/services/file_search.py`.
2. Instantiate/start/stop it from `penguin/web/app.py` lifespan, following the existing service lifecycle pattern.
3. Preserve a bounded workspace LRU (initially 16 roots), but evict watcher registrations and query caches together with the index.
4. Normalize roots once with the existing directory/session authority helpers. The service must never independently choose a workspace root.
5. Add `prewarm(root)` and call it when a session/workspace directory is established or first observed. Prewarm must be asynchronous and deduplicated.
6. Keep `/find/file` and `/api/v1/find/file` response shapes unchanged.

### Initial enumeration strategy

Use the fastest available enumerator without making correctness depend on a developer-installed tool:

1. Prefer bundled/available `rg --files` when the runtime can reliably locate it.
2. Otherwise use Git enumeration for Git workspaces where its semantics match the route contract.
3. Fall back to a native Python `os.scandir` traversal in a worker thread.

Before choosing flags, lock down intended semantics in tests:

- hidden files are currently indexed and ranked last unless the query targets a hidden segment;
- explicit skip directories such as `.git`, `node_modules`, build output, virtualenvs, and caches are excluded;
- symlinked directories should not escape or recursively explode the workspace;
- ignored files are currently not uniformly excluded, unlike default ripgrep behavior;
- empty directories currently appear in directory search.

A likely ripgrep command is `rg --files --hidden --no-ignore` plus explicit exclusion globs matching `_FIND_FILE_SKIP_DIR_NAMES`. Benchmark it and verify Windows quoting/path normalization. If using file output to derive directories, preserve empty-directory behavior with a lightweight directory pass or explicitly decide and document a narrower contract. Do not silently change route semantics just to win a benchmark.

## Phase 2 — Make warm queries cheap

The first optimization is to stop recreating data on each keypress.

1. Precompute lowercase path, lowercase basename, hidden flag, type, depth, and stable lexical tie-break data when the snapshot is built.
2. Store file and directory entry IDs separately so `type=file` and `type=directory` do not allocate filtered lists.
3. Avoid `[*files, *directories]` and avoid returning copied cache lists.
4. Replace “collect every match then sort all matches” with bounded top-K selection (`heapq.nsmallest` or an equivalent fixed-size heap). The result limit is normally ten.
5. Use staged ranking consistent with current behavior:
   - exact basename/path;
   - basename prefix;
   - path prefix;
   - basename substring;
   - path substring;
   - basename subsequence;
   - path subsequence.
6. If enough results exist in a higher-priority tier, do not execute lower-priority fuzzy tiers. This preserves ordering while avoiding expensive subsequence work for common queries.
7. Add a small per-snapshot query LRU keyed by `(generation, kind, normalized_query, limit, hidden_policy)`. Backspacing and repeated `@` opens should be effectively free.
8. Cache candidate sets for recent query prefixes only if profiling shows value. If query `abc` extends `ab`, it can refine the complete `ab` candidate set, but never refine only the prior top ten because that can lose valid results.
9. Add compact character or n-gram postings only if the staged/precomputed implementation misses the target. Avoid a large custom indexing structure without benchmark evidence.
10. Benchmark an already-installed/native fuzzy implementation before adding a dependency. A new library is justified only if it materially improves p95 and supports the required deterministic ranking across Python 3.10–3.12 and supported platforms.

For one-character queries, consider a product rule that prioritizes prefix/substring matches and recent files rather than doing an exhaustive fuzzy fallback. That rule must be explicit and tested because it changes ranking semantics.

## Phase 3 — Keep the index fresh without TTL rescans

The project already depends on `watchdog`, so reuse it rather than adding another filesystem watcher dependency.

1. Run one shared observer from the file-search service and schedule active workspace roots.
2. Handle path-changing events:
   - create: add file/directory and required parent directories;
   - delete: remove entry and now-empty derived directories as appropriate;
   - move: remove source and add destination;
   - modify: ignore for filename search because the searchable path did not change.
3. Apply explicit skip/hidden/symlink policies to events exactly as initial enumeration does.
4. Debounce event bursts for roughly 50–100 ms and publish one new immutable generation per batch.
5. Invalidate the query-result LRU by generation instead of individually deleting keys.
6. On observer overflow, watcher failure, bulk checkout uncertainty, or inconsistent state:
   - mark the root dirty;
   - continue serving the previous snapshot;
   - trigger one background rebuild;
   - atomically replace the snapshot when complete.
7. Add a slow reconciliation interval as a safety net (for example 30–60 seconds), but rebuild only when a cheap fingerprint indicates possible drift. Do not restore a five-second unconditional full scan.
8. Stop and unschedule watchers on application shutdown and workspace-LRU eviction.

Watcher correctness matters more than theoretical freshness. If incremental directory bookkeeping becomes brittle, use watcher events as invalidation signals and perform a debounced background rebuild first; then add true incremental mutation in a later measured PR. A 20–100 ms native rebuild is already far better than a synchronous Python walk on a keystroke.

## Phase 4 — TUI request hygiene and perceived latency

Apply the same helper to both prompt autocomplete and `DialogTag` so they do not drift.

1. Extract a small `file-search-resource`/query helper shared by:
   - `component/prompt/autocomplete.tsx`;
   - `component/dialog-tag.tsx`.
2. Send `limit=10` explicitly (or five for `DialogTag`) so the contract is visible.
3. Cancel or logically supersede older requests when the query/directory/session changes. If the generated SDK cannot pass an `AbortSignal`, use a monotonically increasing request token and discard stale responses; add SDK cancellation separately if warranted.
4. Add a short adaptive debounce for rapid typing (start around 25–40 ms and measure). Do not delay the initial `@` open unnecessarily.
5. Keep the previous valid result set visible while the next query is in flight, with a subtle loading state if the request crosses a threshold. Avoid flashing an empty list.
6. Cache a small number of exact `(directory, query)` responses client-side for backspace/reopen behavior. Directory/session must be part of the key.
7. Ensure stale responses can never overwrite newer query results.
8. Preserve frecency behavior, but clarify ranking ownership:
   - the server ranks textual relevance and returns a bounded candidate set;
   - the TUI may use frecency as a tie-break/boost;
   - if frecency should override relevance globally, send enough candidates or move the frecency signal into a server-visible contract. Sorting only the server’s top ten cannot recover a frequently used file that the server omitted.

The TUI work is load shedding and polish. It is not a substitute for the backend index because web and remote clients also use the endpoint.

## Phase 5 — Validation and rollout

### Backend tests

Extend `tests/api/test_find_file_routes.py` and add focused service tests for:

- existing file/directory/type/hidden ordering behavior;
- session-bound directory winning over raw caller directory;
- conflicting session/directory requests still returning 409;
- one build for N concurrent cold requests;
- stale snapshot served during background refresh;
- cache expiry measured from build completion (if Phase 0 TTL remains temporarily);
- create/delete/move watcher updates;
- ignored/skip directory behavior;
- hidden entries and hidden-targeting queries;
- empty directories;
- symlink loops and paths escaping the root;
- watcher overflow/failure causing one rebuild;
- LRU eviction stopping the corresponding watch;
- application shutdown stopping observer threads/tasks;
- route work not blocking an unrelated async health/request probe during a deliberately slow scan.

### Query correctness tests

Build table-driven ranking tests covering every tier and tie-break. Compare the optimized implementation against the current scorer on a generated corpus before switching it on. Any intended ranking difference should be reviewed as a product change rather than buried in a performance PR.

### TUI tests

Add tests for the extracted resource/controller:

- rapid `a -> ar -> arch` input does not display `a` results last;
- superseded requests are cancelled or discarded;
- changing sessions/directories invalidates the client cache;
- backspacing can reuse cached results;
- loading does not blank valid existing suggestions;
- prompt autocomplete and `DialogTag` use the same query contract.

Run at minimum:

```bash
pytest -q tests/api/test_find_file_routes.py tests/web/services/test_file_search.py
cd penguin-tui/packages/opencode
bun test test/cli/tui/file-search-resource.test.ts
bun run typecheck
```

### Performance validation

Add a manual/repeatable command that reports:

- build implementation used (`rg`, Git, or Python fallback);
- file/directory counts;
- cold build time;
- warm p50/p95/p99 for representative queries;
- worst-case no-match/subsequence query;
- cache-hit time;
- watcher update-to-visible time;
- concurrent request behavior;
- event-loop responsiveness during build.

Capture before/after results in the PR description. Do not enforce tight wall-clock assertions in ordinary unit tests.

### Rollout

1. Land Phase 0 safeguards and measurements.
2. Land the service extraction with behavior parity.
3. Enable the new snapshot/query implementation by default after correctness tests pass.
4. Enable watcher invalidation with a temporary diagnostic flag only if platform confidence is low; otherwise keep a safe background-rebuild fallback always available.
5. Land TUI cancellation/debounce independently once the server contract is stable.
6. Remove the old global cache/scanner and temporary compatibility flag after one release with no regressions.

## Recommended PR sequence

### PR 1 — Stop pathological behavior

- Async `to_thread` build.
- Per-root single-flight.
- Correct completion-based expiry.
- Stale-while-revalidate.
- Timing logs and concurrency tests.

Expected result: the webserver remains responsive and repeated searches stop paying synchronous rescans, but warm ranking may still take 50–80 ms.

### PR 2 — Backend service and fast initial enumeration

- Introduce `FileSearchService`.
- Lifecycle ownership and workspace prewarming.
- Ripgrep/Git/native enumerator strategy with parity tests.
- Immutable snapshot and bounded LRU.

Expected result: cold Git workspace indexing drops from seconds toward tens/hundreds of milliseconds and no longer lives in route globals.

### PR 3 — Warm query engine

- Precomputed entry fields.
- No per-request corpus copying.
- Staged ranking and bounded top-K.
- Query-result cache.
- Before/after ranking equivalence tests and benchmarks.

Expected result: common warm searches meet the <=25 ms server p95 target.

### PR 4 — Watcher freshness

- Shared `watchdog` lifecycle.
- Debounced update/rebuild path.
- Overflow recovery and reconciliation.
- Shutdown/eviction tests.

Expected result: no periodic full rescans in the request path and changes appear within roughly 250 ms.

### PR 5 — TUI request controller

- Shared autocomplete requester.
- Supersession/cancellation.
- Adaptive debounce and exact-query cache.
- Stable loading/results behavior.

Expected result: rapid typing produces fewer requests, no stale-result flashes, and local keypress-to-result p95 is below 80 ms.

## Approaches to avoid

- **Only increase the five-second TTL.** This does not solve cold start, stampedes, blocking I/O, or warm scoring cost.
- **Run `os.walk` or a subprocess on every query.** Even a fast command has process startup and filesystem costs that do not belong in a keystroke path.
- **Move the canonical index into the TUI.** That breaks backend/API ownership and remote filesystem semantics.
- **Persist this in SQLite/FTS immediately.** Filename corpora of this size fit comfortably in memory; persistence adds invalidation and schema complexity before it provides a demonstrated benefit.
- **Add Elasticsearch, Tantivy, or a standalone daemon.** This is far beyond the requirement and creates packaging/operations costs.
- **Debounce by hundreds of milliseconds.** That masks server work while making the UI deliberately sluggish.
- **Refine from only the previous top ten.** It is fast but incorrect because later characters may promote candidates that were previously outside the returned set.
- **Hold a global lock while scanning or ranking.** Reads should use immutable snapshots; mutation locks should cover short state transitions only.

## Definition of done

- Warm `/find/file` common-query p95 is <=25 ms on a 100k-entry corpus.
- Local TUI keypress-to-suggestions p95 is <=80 ms after index warmup.
- Cold indexing cannot block unrelated FastAPI requests.
- Concurrent cold searches for one root trigger one build.
- No five-second request-path full rescan remains.
- Create/delete/move changes become searchable within 250 ms under normal watcher operation.
- Session-scoped directory authority and conflict responses are unchanged.
- Hidden, skipped, type-filter, path normalization, empty-directory, and symlink behavior are explicitly tested.
- TUI stale requests cannot overwrite current results.
- The old route-level `_FIND_FILE_INDEX_CACHE` and scanner are removed after migration.
