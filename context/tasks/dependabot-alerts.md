# Dependabot Alerts Cleanup Plan

## Summary

Snapshot captured from `gh api` output provided by the user.

- Total alerts: 140
- Severity split: 46 high, 80 medium, 14 low
- Biggest blast radius:
  - `docs/package-lock.json`: 52 alerts
  - `docs/yarn.lock`: 52 alerts
  - `penguin-tui/packages/web/package.json`: 12 alerts
  - `penguin-tui/packages/desktop/src-tauri/Cargo.lock`: 8 alerts

## Strategy

Brutal truth: this is mostly a lockfile hygiene problem, especially under `docs/`.
Do not whack alerts one-by-one. Fix by manifest, regenerate locks, then re-scan.

### Pre-Cleanup Notes
- [x] Historical note: `penguin-tui/packages/desktop/src-tauri/` was used by the upstream desktop package itself, so deleting only `src-tauri/` would have been the wrong cut
- [x] Verified: Penguin's documented/default TUI path is `penguin-tui/packages/opencode`, not the desktop Tauri app
- [x] Verified: current repo GitHub workflows publish the Python package and the TUI sidecar from `penguin-tui/packages/opencode`; they do **not** build `penguin-tui/packages/desktop/`
- [x] Retired the unused desktop surface by deleting `penguin-tui/packages/desktop/` and regenerating `penguin-tui/bun.lock`
- [x] Cleaned related references in repo metadata/docs (`penguin-tui/flake.nix`, `script/changelog.ts`, `CONTRIBUTING.md`, and `specs/01-persist-payload-limits.md`)
- [ ] Do **not** remove `penguin-tui/packages/console/core/` blindly; usage by Penguin's TUI is currently uncertain
- [ ] Treat `penguin-tui/packages/console/core/package.json` / `drizzle-orm` as a hold item pending usage audit

Recommended order:
1. Decide whether to retire `penguin-tui/packages/desktop/` as an unused product surface
2. If retiring it, remove `penguin-tui/packages/desktop/` and its related references as a unit
3. Clean `docs/package-lock.json` and `docs/yarn.lock`
4. Clean `penguin-tui/packages/web/package.json`
5. Clean `penguin-tui/packages/opencode/package.json`
6. Leave `penguin-tui/packages/console/core/` alone until usage is confirmed
7. Clean remaining medium/low alerts after the high-risk clusters collapse

## Todo

### Phase 1: Remove dead surface first
- [x] Verify whether Penguin's active TUI/runtime depends on the desktop app
- [x] Verify whether current GitHub workflows build or publish `penguin-tui/packages/desktop/`
- [x] Audit remaining repo references to `penguin-tui/packages/desktop/` before deletion (`nix/desktop.nix`, changelog/docs/specs, workspace lockfile)
- [x] If the desktop app is retired, remove `penguin-tui/packages/desktop/` as a whole package, not `src-tauri/` alone
- [ ] Re-run Dependabot alert listing and confirm the Rust/Tauri alerts disappear with the deleted desktop surface

### Phase 2: Docs dependency cluster
- [ ] Audit why `docs/` has both `package-lock.json` and `yarn.lock`
- [ ] Pick one package manager for `docs/` and delete the stale lockfile after verification
- [ ] Update docs dependencies and regenerate the surviving lockfile
- [ ] Re-run alerts for `docs/` and verify the duplicate advisories collapse

#### `docs/package-lock.json` — 52 alerts
High-priority packages:
- [ ] `node-forge` — 7 alerts (`#26`, `#27`, `#28`, `#123`, `#124`, `#125`, `#126`)
- [ ] `minimatch` — 3 alerts (`#54`, `#60`, `#62`)
- [ ] `path-to-regexp` — 2 alerts (`#2`, `#131`)
- [ ] `lodash` — 1 high + 2 medium (`#39`, `#149`, `#150`)
- [ ] `lodash-es` — 1 high + 2 medium (`#38`, `#141`, `#142`)
- [ ] `picomatch` — 1 high + 1 medium (`#127`, `#128`)
- [ ] `serialize-javascript` — 1 high + 1 medium (`#64`, `#130`)
- [ ] `cross-spawn` — 1 high (`#1`)
- [ ] `image-size` — 1 high (`#3`)
- [ ] `svgo` — 1 high (`#67`)

Follow-up medium/low packages:
- [ ] `dompurify` — 6 medium (`#65`, `#66`, `#132`, `#143`, `#144`, `#211`)
- [ ] `ajv` — 2 medium (`#50`, `#51`)
- [ ] `brace-expansion` — 1 medium + 1 low (`#9`, `#129`)
- [ ] `http-proxy-middleware` — 2 medium (`#5`, `#6`)
- [ ] `js-yaml` — 2 medium (`#23`, `#24`)
- [ ] `mermaid` — 2 medium (`#11`, `#13`)
- [ ] `qs` — 1 medium + 1 low (`#31`, `#44`)
- [ ] `webpack-dev-server` — 2 medium (`#7`, `#8`)
- [ ] `estree-util-value-to-estree` — 1 medium (`#4`)
- [ ] `follow-redirects` — 1 medium (`#157`)
- [ ] `mdast-util-to-hast` — 1 medium (`#29`)
- [ ] `yaml` — 1 medium (`#121`)
- [ ] `webpack` — 2 low (`#41`, `#42`)
- [ ] `on-headers` — 1 low (`#10`)

#### `docs/yarn.lock` — 52 alerts
High-priority packages:
- [ ] `node-forge` — 7 alerts (`#174`, `#175`, `#176`, `#196`, `#197`, `#198`, `#199`)
- [ ] `minimatch` — 3 alerts (`#186`, `#187`, `#188`)
- [ ] `path-to-regexp` — 2 alerts (`#161`, `#202`)
- [ ] `lodash` — 1 high + 2 medium (`#179`, `#204`, `#206`)
- [ ] `lodash-es` — 1 high + 2 medium (`#180`, `#205`, `#207`)
- [ ] `picomatch` — 1 high + 1 medium (`#194`, `#195`)
- [ ] `serialize-javascript` — 1 high + 1 medium (`#189`, `#201`)
- [ ] `cross-spawn` — 1 high (`#160`)
- [ ] `image-size` — 1 high (`#162`)
- [ ] `svgo` — 1 high (`#192`)

Follow-up medium/low packages:
- [ ] `dompurify` — 6 medium (`#190`, `#191`, `#203`, `#208`, `#209`, `#212`)
- [ ] `ajv` — 2 medium (`#184`, `#185`)
- [ ] `brace-expansion` — 1 medium + 1 low (`#168`, `#200`)
- [ ] `http-proxy-middleware` — 2 medium (`#164`, `#165`)
- [ ] `js-yaml` — 2 medium (`#172`, `#173`)
- [ ] `mermaid` — 2 medium (`#170`, `#171`)
- [ ] `qs` — 1 medium + 1 low (`#178`, `#183`)
- [ ] `webpack-dev-server` — 2 medium (`#166`, `#167`)
- [ ] `estree-util-value-to-estree` — 1 medium (`#163`)
- [ ] `follow-redirects` — 1 medium (`#210`)
- [ ] `mdast-util-to-hast` — 1 medium (`#177`)
- [ ] `yaml` — 1 medium (`#193`)
- [ ] `webpack` — 2 low (`#181`, `#182`)
- [ ] `on-headers` — 1 low (`#169`)

### Phase 3: App/package manifests outside docs

#### `penguin-tui/packages/web/package.json` — 12 alerts
- [ ] Upgrade `astro` cluster — 11 alerts (`#84`, `#86`, `#87`, `#88`, `#89`, `#90`, `#91`, `#92`, `#93`, `#94`, `#122`)
- [ ] Upgrade `@astrojs/cloudflare` — 1 high (`#85`)

#### `penguin-tui/packages/opencode/package.json` — 4 alerts
- [ ] Upgrade `minimatch` — 3 high (`#80`, `#81`, `#82`)
- [ ] Upgrade `@modelcontextprotocol/sdk` — 1 high (`#79`)

#### `penguin-tui/packages/ui/package.json` — 5 alerts
- [ ] Upgrade `dompurify` — 5 medium (`#83`, `#139`, `#145`, `#146`, `#213`)

#### `penguin-tui/packages/console/app/package.json` — 1 alert
- [ ] Upgrade `wrangler` — 1 high (`#71`)

#### `penguin-tui/packages/console/core/package.json` — 1 alert
- [ ] Hold `drizzle-orm` upgrade until `console/core` usage is confirmed (`#148`)

#### `examples/agent-visualizer-web/package-lock.json` — 5 alerts
- [ ] Upgrade `rollup` — 1 high (`#57`)
- [ ] Upgrade `vite` — 1 medium (`#152`)
- [ ] Upgrade `esbuild` — 1 medium (`#32`)
- [ ] Upgrade `picomatch` — 2 medium (`#119`, `#134`)

<!-- ### Phase 4: Rust / Tauri lockfile

#### `penguin-tui/packages/desktop/src-tauri/Cargo.lock` — 8 alerts
- [ ] Only do this phase if the desktop app survives the deletion decision
- [ ] Upgrade `quinn-proto` — 1 high (`#75`)
- [ ] Upgrade `tar` — 2 medium (`#76`, `#77`)
- [ ] Upgrade `bytes` — 1 medium (`#73`)
- [ ] Upgrade `glib` — 1 medium (`#72`)
- [ ] Upgrade `rustls-webpki` — 1 medium (`#118`)
- [ ] Upgrade `time` — 1 medium (`#74`)
- [ ] Upgrade `rand` — 1 low (`#156`) -->

## Verification Checklist

- [ ] Run repo-wide dependency updates per manifest, not per alert URL
- [ ] Run install/update commands and commit lockfile changes separately by area
- [ ] Re-run:
  ```bash
  gh api -H "Accept: application/vnd.github+json" \
    "/repos/{owner}/{repo}/dependabot/alerts?state=open&per_page=100" \
    --paginate --jq '.[] | [.number, .security_advisory.severity, .dependency.package.ecosystem, .dependency.package.name, .dependency.manifest_path, .html_url] | @tsv'
  ```
- [ ] Confirm the alert count drops materially after the desktop-package decision and `docs/` cleanup
- [ ] If alerts remain, inspect whether they are transitive-only and need parent package upgrades instead of direct bumps

## Notes

- The `docs/` directory alone accounts for 104/140 alerts. That is still the biggest leverage point.
- `penguin-tui/packages/desktop/` is the real deletion candidate if the desktop app is retired; deleting dead surface beats maintaining dead surface.
- `penguin-tui/packages/console/core/` is intentionally held because its relationship to Penguin's TUI is still uncertain.
- Many alerts are duplicate advisories across `package-lock.json` and `yarn.lock` for the same docs dependency graph.
- `gh` itself is outdated on this machine (`2.76.2 -> 2.89.0`), but that is unrelated to the Dependabot alerts.
- Assumption: this file is a base triage list derived from the pasted CLI output plus the user's stated plan for retiring the unused desktop app and holding `console/core` pending usage audit.
