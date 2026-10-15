# Penguin TUI OpenCode 2 Refresh — 2.0.18 Audit

Audit of the OpenCode 2 client pinned by PR #90 (`codex/opencode-v2-sync`,
"feat: add opt-in OpenCode V2 TUI"), performed **2026-09-27**.

`PR #90` is a draft and has not moved since 2026-08-20. It does not vendor a fork: it pins an
upstream artifact and serves a Penguin-owned `/api/*` compatibility seam. Nothing is broken —
the pin is frozen by design — but the gap has widened to a point where the refresh is a
protocol migration, not a dependency bump.

That branch's own ledger is `context/tasks/penguin-tui-opencode-v2.md`. This file is the
refresh plan that seeds the re-pin work, and it records observations only: **the pin moves
only when the gates at the end close.**

## Range and sources

- Pinned: `b35c5fc98577b77d8d67d298c6254e0cd138c9d5` (2026-08-11), artifact
  `@opencode-ai/cli@0.0.0-next-17220`.
- Candidate: tag `v2.0.18` → `cd9a14a6b688d4021bee381dfd39d2cef9c0f862` (2026-09-25),
  artifact `@opencode/cli@2.0.18`.
- `origin/v2` tip at audit time: `0caae608a28819981510989d28768cd9d4e4a663` (2026-09-27).
- Range size: **2532 commits**.

Evidence came from `packages/protocol/openapi.json` (120 operations at the pin, 136 at the
`origin/v2` tip, 113 paths at the tag), `packages/schema/src/event-manifest.ts`,
`packages/schema/src/plugin.ts`, and `packages/plugin/src/tui/context.ts`. Upstream now also
ships its own `V2_HTTP_API_AUDIT.md` (139 endpoints, regenerated 2026-09-13); its dispositions
agree with the operation set observed in the tag's OpenAPI document.

## Adoption identity changed

V2 left beta and was renamed, so the pinned artifact identity no longer exists:

- npm identity: `@opencode-ai/cli@0.0.0-next-17220` → **`@opencode/cli@2.0.18`**; `v2.0.0` was
  tagged 2026-09-11 and versions synced through 2.0.18 on 2026-09-25.
- plugin package: `@opencode-ai/plugin` → **`@opencode/plugin`** (2.0.18).
- installed binary: `opencode2` → **`opencode`**, with `opencode2` retained only as a legacy
  alias in the package `bin` map and in upstream `install`.
- the extracted artifact's version gate becomes `opencode v2.0.18`, not
  `opencode2 v0.0.0-next-RUN`.

Consequence: the artifact pin, sidecar binary and archive names, the V2 cache marker, the
publish workflow, and the release runbook move together. **This refresh is atomic** — the
launcher must not install one artifact while the seam advertises another commit's contract.

## Wire contract changes that block the port

| Pinned Penguin seam | 2.0.18 |
| --- | --- |
| `GET /api/health`, `GET /api/server` | removed → `GET /api/info` (`{version, pid, urls[], paths{tmp}}`); readiness is the HTTP status |
| `GET /api/project/current` | removed → `project` inside `GET /api/location` |
| `GET /api/location` | `Location.PublicInfo` is `{directory, project{id, directory, canonical}}`; workspace selectors removed |
| `POST /api/session/{id}/rename` | removed → `PATCH /api/session/{id}` (`{title?, metadata?, permissions?}`) |
| `POST /api/session/{id}/interrupt?continue=` | `?resume=`; returns `200 {interrupted}` instead of `204` |
| `GET /api/session/{id}/pending` | removed → `GET /api/session/{id}/inbox`; delivery mutation is `PATCH …/inbox/{id}` with `delivery: steer\|queue`; cancel is `DELETE …/inbox/{id}` |
| `GET /api/question/request`, `…/question/{id}/reply\|reject` | question namespace removed → form namespace |
| `GET /api/form/request` | → `GET /api/form` (`{location{directory}, data[]}`) |
| `GET …/form/{id}/state` | removed → state is returned by `GET /api/session/{id}/form/{id}` with the definition |
| `POST …/form/{id}/cancel` | → `DELETE /api/session/{id}/form/{id}` |
| permission reply field `reply` | → `decision` |
| `POST /api/generate`, `/api/session/import`, `/api/session/{id}/export`, `/api/session/{id}/wait`, `/api/session/{id}/skill`, MCP `PUT`/`DELETE`/`connect`/`disconnect` | moved under `/api/experimental/*` |
| `POST /api/session/{id}/revert/clear` | → `DELETE /api/session/{id}/revert` |
| `POST /api/service/stop`, `/api/project/{id}/directories`, `/api/question/*`, workspace endpoints | removed from the contract |

### Newly available operations the adopted surfaces need

`GET /api/info`, `POST /api/location/reload`, `GET /api/config/shell`,
`PATCH /api/experimental/config`, `PATCH /api/project/{id}`, `GET /api/session/{id}/diff`,
`POST /api/session/{id}/view`, `PUT /api/session/{id}/environment`, `GET /api/vcs/base`,
`GET /api/vcs/branch`, the worktree group (4 operations), the persistent-PTY group (10),
`GET /api/experimental/session/stats`, `POST /api/experimental/fs/write`,
`POST /api/plugin/check`, `POST /api/plugin/update`, and `POST /api/rpc/{rpcID}/{method}`.

## Event manifest

The `Question` event inventory is gone. New inventories: `Location`, `Credential`, `Provider`,
`Model`, `Worktree`, `PersistentPty`. `ProjectDirectories` and `Catalog` are gone.
`server.connected` is unchanged and remains the first frame on `/api/event`, so the existing
connect fixture stays valid.

## Plugin ABI

`context.ui.slot(name, render)` is gone. It is now a typed hierarchical claim:

```ts
context.ui.slot({ append: "app", render: () => <Commands context={context} /> })
```

Every claim names exactly one placement (`prepend`, `append`, `before`, `after`, `replace`)
against a published `SlotMap` path (`app`, `home.footer[.status]`,
`prompt.footer[.status|.file]`, `session.composer.top`, `session.panel`, `sidebar.content`,
`sidebar.footer`) and receives that slot's typed input. Plugin identity also changed:
`Plugin.Info` is now `{id?, source, features{server?, tui?, rpc?}, state}` and `plugin.added`
no longer exists.

## Ordered port checklist

1. **Artifact identity and version gate.** `penguin/cli/opencode_launcher.py` pins, binary and
   archive names, cache marker; `.github/workflows/publish-tui-v2.yml` env plus gate
   assertions; `context/process/release-runbook.md`; `README.md`;
   `docs/docs/getting_started.md`; `penguin-tui-v2/README.md`;
   `tests/test_opencode_launcher.py`.
2. **Readiness and location.** `/api/info`, drop `/api/project/current`, drop workspace
   selectors from location payloads; `penguin/web/middleware/auth.py` public allowlist;
   `tests/fixtures/opencode_v2/core_contracts.json`; route tests.
3. **Session lifecycle.** `PATCH /api/session/{id}`, interrupt `resume` with `{interrupted}`,
   revert-clear deletion.
4. **Interactions.** permission `decision` field; form namespace, deletion cancel, merged
   state.
5. **Inbox.** list, delivery mutation, and cancellation replacing `/pending`.
6. **Event manifest alignment** for the native lifecycle the seam already projects.
7. **Plugin ABI port.** `@opencode/plugin/tui`, slot claim, `Plugin.Info` shape.
8. **Previously deferred adoption, now unblocked.** Session diff, worktrees, persistent PTY,
   session tabs and prefetch, queue/steer inbox UX, child and background session UX,
   undo/redo.

Steps 1–7 are required for a re-pinned client to boot, prompt, interrupt, and reopen
truthfully. Step 8 is the capability work that the frozen pin made impossible.

## Gates before the pin moves

- **Registry values are resolved** (2026-09-27): `@opencode/cli@2.0.18` has integrity
  `sha512-EkIxIa2goJ2v8U3Os2gpRckOIjN9gpUBXy6fyVOFbPZl71rkGpoF3NFsm4nlDiF2BgnIqcgJU5NgdV1k6/OZuw==`,
  tarball `https://registry.npmjs.org/@opencode/cli/-/cli-2.0.18.tgz`, and publish time
  `2026-09-25T23:55:43.254Z`. `@opencode/plugin@2.0.18` is published.
- The publish workflow's `0.0.0-next-${OPENCODE_V2_PUBLISH_RUN}` assertion must be replaced
  with a stable version gate, since a released version has no publish run.
- The legacy `@opencode-ai/cli` scope still publishes `1.18.18`, so the current beta pin and
  its sidecar remain installable as a rollback while the stable pin is validated.
- Because `opencode2` remains a legacy alias, the V2 cache marker must be regenerated rather
  than reused. The V1 launcher, cache, and release workflow stay untouched.
- `tests/fixtures/opencode_v2/core_contracts.json` must be regenerated from the tag's
  `openapi.json` and generated client before step 2 is called done. The current fixture covers
  only health, location, session, and the connect frame.
- The packaged-client smoke (Home boot, session create, prompt, interrupt, backend restart,
  reopen) is still a pre-release gate.

## Slice 1 landed (2026-09-27, branch `codex/opencode-v2-refresh`)

Scope agreed with the maintainer: **pin + seam only**. Feature adoption (step 8) moves to a
separate PR so this one can actually merge.

Landed:

- Pin moved to tag `v2.0.18` (`cd9a14a6b688d4021bee381dfd39d2cef9c0f862`) and artifact
  `@opencode/cli@2.0.18`, in both `penguin/cli/opencode_launcher.py` and
  `penguin/web/services/opencode_v2.py`.
- **Readiness is now Penguin-owned.** `_health_url()` always probes `/api/v1/health` and the
  V2-only payload validation (`healthy`/`version`/`pid`) is gone, replaced by a status-plus-
  JSON-object check. This closed the real trap in the old design: `/api/health` was inside both
  the upstream namespace *and* the launcher's startup path, so the moment upstream dropped the
  route the probe would 404, `server_running` would read false, and `main()` would autostart a
  second web server against the live one.
- Seam gained `GET /api/info` returning the 2.x `ServerInfo` contract
  (`version`, `pid`, `urls`, `paths{tmp}`, all required, no extra keys) via `info_payload()`;
  `GET /api/health` and its `health_payload()` were removed rather than shimmed, along with the
  `/api/health` public-endpoint entry and the `health` route root in `penguin/web/middleware/auth.py`.
- **Distribution identity carve-out.** The payload binary inside the archive is now `opencode`
  (`bin/opencode`), matching upstream, but Penguin's release asset prefix stays `opencode2-*`
  (`TUI_V2_ASSET_PREFIX`) because the V1 payload already owns `opencode-*` inside the same
  GitHub release and duplicate asset names are rejected per release. `--use-global-opencode`
  keeps resolving `opencode2`, which 2.x still publishes as a legacy bin alias — switching to
  the bare name would have made that flag ambiguous with Penguin's V1 fork binary.
- Publish workflow: version/commit/publish-time/bun (`1.4.2`) pins refreshed, wrapper integrity
  and all twelve platform-package integrities re-resolved from the registry, `@opencode-ai/cli*`
  scopes renamed, `manifest.bin.opencode` asserted (plus `opencode2` alias), and the `--version`
  gate is now `opencode v2.0.18` — upstream's product name comes from `OPENCODE_CLI_NAME`,
  which was `opencode2` at the old pin and is `opencode` now. The prerelease-shaped
  `0.0.0-next-${OPENCODE_V2_PUBLISH_RUN}` gate is gone.
- Docs, runbook, and the plugin README updated; the fixture records the new commit and the
  `info_required`/`info_paths_properties` contract instead of `health_required`.

Verified: `pytest tests/test_opencode_launcher.py tests/api/test_opencode_v2_routes.py
-tests/test_opencode_v2_plugin.py` 89 passed; wider sweep `-k "opencode or launcher or v2"`
269 passed, 1 skipped. `ruff format --check` clean; the remaining `ruff check` findings are the
pre-existing `UP007`/annotation-rule noise that untouched files report at a higher rate.

Still open on this branch (the pin is *not* merge-ready yet): steps 2–4 of the port list —
session `PATCH`, inbox, form namespace, `decision`/`resume` fields, removal of
`/api/project/current`, `POST /api/session/{id}/rename`, and `/pending` — plus the event
manifest and the plugin `SlotClaim` port. Until those land, a `PENGUIN_TUI_V2=1` boot attaches
the new binary to a seam that still answers the old shapes.

## Verified against the real 2.0.18 binary (2026-09-27)

No release anywhere has `opencode2-*` assets — `publish-tui-v2.yml` exists only on this branch, so
no tag has ever run it. A local payload can still be fetched without publishing anything:

```bash
cd tmp_workspace/oc2 && npm pack @opencode/cli-darwin-arm64@2.0.18
tar -xzf opencode-cli-darwin-arm64-2.0.18.tgz && chmod +x package/bin/opencode
./package/bin/opencode --version   # -> "opencode v2.0.18"
```

That output is the empirical proof of the `OPENCODE_CLI_NAME` rename: the workflow's `--version`
gate had to become `opencode v${OPENCODE_V2_VERSION}`. The payload ships `bin/opencode` only.

Booting it against the seam (`PENGUIN_TUI_V2=1` plus `PENGUIN_TUI_BIN_PATH`, with web served from
this worktree on 8080) **works**: the TUI renders, the footer reads `2.0.18`, and the launcher's
new readiness probe reports `server_running: true`. Recording the server log gives the real boot
call set, which is a better source of truth than reading the contract:

- answered 200: `/api/info`, `/api/location`, `/api/project`, `/api/session/active`, `/api/agent`,
  `/api/command`, `/api/model`, `/api/provider`, `/api/skill`, `/api/shell`, `/api/reference`,
  `/api/mcp`, `/api/mcp/resource`, `/api/integration`, `/api/fs/list`, `/api/vcs`,
  `/api/experimental/migration/v1`, `/api/event`, plus the launcher's `/api/v1/health`.
- failed: `/api/form` 404, `/api/plugin` and `/api/config` 401.

Two bugs surfaced only by running it, both fixed on this branch:

1. **`/api/info.version` must be the upstream contract version.** The client logs
   `Server at http://127.0.0.1:8080 has version 0.9.1; this client is 2.0.18. Continuing anyway.`
   and compares that field against its own build, so the seam now reports
   `UPSTREAM_V2_VERSION` (`2.0.18`) instead of Penguin's package version. A test pins that constant
   to the launcher's artifact pin so they cannot drift apart.
2. **The auth route-root list decides 401 versus 404.** `_is_opencode_v2_route()` is what makes a
   request eligible for the client's fixed Basic-auth identity, so a namespace missing from
   `_OPENCODE_V2_ROUTE_ROOTS` is answered 401 by the auth layer before routing. That made
   unimplemented routes look like credential failures. The set now matches all 27 `/api/<root>`
   namespaces in the pinned contract, with the list recorded in the fixture and asserted by a test.

Confirmed live after the fix: `/api/info` reports `2.0.18`, the mismatch warning is gone, and
`/api/plugin` answers 404 instead of 401.

Still unimplemented, proven by the run: `/api/plugin` (plugin discovery — the reason the Penguin
extension does not load), `/api/form`, and the `config`, `worktree`, `pty`, `credential`, `rpc`,
`websearch`, and `debug` namespaces. Only boot was exercised; no prompt was sent.

## Session creation unblocked (2026-09-27)

The client could not start a session at all: `create_session_payload()` rejected any body
carrying `id` (`"Client-selected session ids are not supported"`), and the pinned client always
sends one, because the contract declares `id` as an optional `^ses` string. The TUI's own log
showed the cascade — `POST /api/session` 400, then `/api/session/{id}/permission` and `/form`
404 `SessionNotFoundError` for a session that was never created, which is why the interface was
inert.

Fixed through all three layers: `session_manager.create_session()` takes an optional `session_id`
(raising on collision), `create_session_info()` forwards it only when supplied, and the seam
validates the contract pattern and returns the existing projection for a repeat id so a client
retry is idempotent instead of creating a second session. The create route also skips
`session.created` on such a retry.

Verified live (local auth off, so the calls are the client's own authorized shape):

```
POST /api/session {"id":"ses_..."}  -> 200, echoes the id   (was 400)
GET  /api/session/ses_...           -> 200                  (was 404)
GET  /api/session/ses_.../permission-> 200                  (was 404)
GET  /api/session/ses_.../form      -> 200                  (was 404)
POST /api/session same id again     -> 200 (idempotent)
POST /api/session {"id":"nope"}     -> 400 (still guarded)
```

`^ses` also admits Penguin's native `session_...` ids; ids are opaque, so that is honoured rather
than tightened. Tests: three new cases in `tests/api/test_opencode_v2_routes.py` (id preserved,
idempotent retry, non-contract id rejected), and the file's fake manager stub now mirrors the real
signature.

## Branding and animation constraints in the V2 TUI (checked at the pin)

- The entry/exit wordmark is a **splash**, and the only config knob is
  `splash: "show" | "hide"` (`packages/tui/src/config/index.tsx`). There is no custom-logo or
  banner option anywhere in `packages/schema/src`, so Penguin can hide the upstream wordmark but
  cannot replace it through configuration.
- Replacing it means drawing our own content on Home, which is the plugin/slot path — the same
  deferred work. Penguin branding in this client is therefore coupled to the plugin decision.
- No terminal graphics protocol support exists at this pin: the only `sixel`/`kitty`/`iterm`
  matches in `packages/` are i18n strings. A raster image of a penguin is not reachable; truecolor
  half-block/braille art is, and the renderer already animates (a one-cell spinner feature plugin
  exists), so a frame-animated block-art penguin is feasible — again via the slot path.
- Markdown images *are* handled (`packages/session-ui/src/components/markdown-image.ts` resolves and
  reads local image paths), so inline images render as file references rather than pixels.

## How to re-derive these findings

Reference clone: `reference/opencode` (remote `sst/opencode`, which resolves to the upstream
documented as `anomalyco/opencode`). It must be fetched before comparing:

```bash
git -C reference/opencode fetch origin --prune
git -C reference/opencode fetch origin 'refs/tags/v2.0.*:refs/tags/v2.0.*'
git -C reference/opencode rev-list --count b35c5fc..v2.0.18
```

Operation sets are read directly from the contract document rather than from the generated
client, which is the authoritative source for both the TUI and the seam:

```bash
git -C reference/opencode show v2.0.18:packages/protocol/openapi.json
```

Diff the `paths` map of the pinned revision against the candidate to reproduce the table
above; the numbers quoted (120 / 136 / 113) come from that comparison. Event and plugin
surfaces come from `packages/schema/src/event-manifest.ts`, `packages/schema/src/plugin.ts`,
and `packages/plugin/src/tui/context.ts` at the same revisions.
