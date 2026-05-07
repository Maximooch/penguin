# Browser Tool Refresh: Browser-Harness Adoption Plan

## Objective

Evaluate and integrate `reference/browser-harness` as Penguin's next-generation browser automation backend.

Canonical Penguin repository: https://github.com/Maximooch/penguin

The goal is not "add another browser tool." The goal is to make Penguin's browser capability reliable enough for real web workflows: authenticated browser sessions, UI testing, scraping, documentation research, subagent/browser isolation, screenshots, CDP escape hatches, and reusable browser/domain skills.

## Current Recommendation

Adopt browser-harness as Penguin's preferred canonical `browser_*` backend when it is installed locally/from source, while keeping PyDoll as the PyPI-available compatibility fallback.

Do **not** hard-depend on browser-harness in Penguin's base install or extras while it is not published on PyPI.

Rationale:

- Penguin supports Python `>=3.9,<3.13`; browser-harness requires newer Python.
- Browser-harness is not published on PyPI, so `penguin-ai[browser]` cannot honestly install it yet.
- The `[browser]` extra should install the PyPI-available fallback (`pydoll-python`) and document local/source browser-harness installation.
- Browser-harness is MIT-licensed, so copying/vendoring is legally feasible, but blindly forking it creates maintenance ownership immediately.
- The best current path is optional local/source library integration behind a stable Penguin-owned adapter contract; vendoring remains an escape hatch if upstream/package instability proves costly.

## Background

Penguin already advertises browser and research support for documentation, web workflows, and UI testing. The current implementation does not match that ambition.

Current state:

- Legacy `browser_use` support is disabled in `penguin/tools/browser_tools.py` due compatibility/telemetry concerns.
- PyDoll is the current preferred browser automation path, exposed through `pydoll_browser_*` tools.
- `ToolManager` still exposes both legacy `browser_*` names and PyDoll-specific tool names.
- Browser tooling is currently mixed into the `ToolManager` monolith, which increases regression risk and makes backend replacement harder.

Browser-harness offers a better shape for Penguin's direction:

- direct Chrome DevTools Protocol control
- attaches to a user's real Chrome instead of always launching a managed browser
- daemonized browser connection with stale-session recovery
- screenshot-first workflow
- raw CDP escape hatch
- simple helper layer that agents can extend
- interaction skills and domain skills that encode reusable browser knowledge

## Architecture Fit

Penguin's architecture is modular, event-driven, and tool-oriented. Browser-harness should be treated as a browser backend/subsystem, not as a one-off wrapper.

Fit points:

- `ToolManager` / future `tool_domains.browser` owns tool schemas and dispatch.
- Optional dependency resolution mirrors existing `pydoll` and `browser` extras.
- Session and subagent identity can map to browser-harness `BU_NAME` values.
- Penguin workspace state can map to `BH_AGENT_WORKSPACE`.
- Skill/domain knowledge can feed Penguin's existing Skills system or a browser-specific retrieval layer.
- Browser screenshots and page state can be emitted to TUI/web surfaces as tool artifacts.

## Browser-Harness Capabilities To Preserve

Core helper primitives:

- `cdp(method, session_id=None, **params)` for raw CDP calls.
- `new_tab(url)` for safe first navigation without clobbering the user's active tab.
- `goto_url(url)` for intentional current-tab navigation.
- `page_info()` for URL/title/viewport/scroll/page-size or pending-dialog state.
- `capture_screenshot(path=None, full=False, max_dim=None)` for visual inspection.
- `click_at_xy(x, y, button="left", clicks=1)` for compositor-level clicking.
- `type_text(text)`, `press_key(key)`, and `fill_input(selector, text)` for input.
- `scroll(x, y, dy=-300, dx=0)` for wheel scrolling.
- `list_tabs()`, `current_tab()`, `switch_tab(target)`, and `ensure_real_tab()` for tab control.
- `wait_for_load()`, `wait_for_element()`, and `wait_for_network_idle()` for readiness.
- `js(expression, target_id=None)` for inspection and extraction.
- `upload_file(selector, path)` for file uploads.
- `http_get(url, headers=None, timeout=20.0)` for non-browser static/API reads.

Daemon/admin behavior to preserve:

- idempotent `ensure_daemon()` startup.
- stale daemon/session self-healing.
- POSIX Unix socket with restrictive permissions.
- Windows loopback token protection.
- remote Browser Use cloud browser support as optional, not default.
- explicit remote shutdown to avoid cloud browser billing leaks.

## Skills Consideration

Browser-harness includes a large markdown skill corpus:

- general interaction skills for mechanics such as tabs, iframes, dialogs, uploads, screenshots, scrolling, cookies, downloads, shadow DOM, network requests, and profile sync
- domain skills for site-specific playbooks under `agent-workspace/domain-skills/`

Important constraint: do **not** dump all browser/domain skills into the base prompt.

Decisions:

1. Reference the browser-harness `SKILL.md` pattern as a bundled Penguin skill named `browser`.
2. Keep interaction skills as progressively-loadable references under that `browser` skill.
3. Store browser domain skills under Penguin Skills in the browser-specific directory: `penguin/bundled_skills/browser/domain-skills/` for packaged defaults and user/project browser skill directories for learned/local site playbooks.
4. Treat hostname lookup as optional. Browser-harness already has a domain-skill section and `BH_DOMAIN_SKILLS` gate; Penguin should preserve the concept without forcing every navigation to retrieve site files.
5. For docs/static scraping, prefer scripting/HTTP/JS extraction. Use actual browser interaction primarily for testing software Penguin made, authenticated workflows, dynamic UI verification, or pages where static scraping is insufficient.
6. Redact secrets and avoid storing pixel coordinates, task transcripts, credentials, or personal data in reusable domain skills.

Potential integration with Penguin Skills:

- Keep activated browser instructions as `MessageCategory.CONTEXT`, not `SYSTEM`.
- Use `activate_skill("browser")` when a browser workflow begins or when browser interaction starts failing.
- Load only the relevant interaction reference file after a concrete mechanic appears.

## Proposed Tool Surface

Add a new module, likely:

- `penguin/tools/browser_harness_tools.py`

Initial user-facing tools:

- `browser_open_tab`
  - args: `url`
  - behavior: calls `new_tab(url)` and `wait_for_load()` by default

- `browser_page_info`
  - args: none
  - behavior: returns `page_info()`

- `browser_screenshot`
  - args: `full: bool = false`, `max_dim: int | null = 1800`
  - behavior: captures screenshot and returns artifact path/metadata

- `browser_click`
  - args: `x`, `y`, optional `button`, optional `clicks`
  - behavior: coordinate click, then optionally return updated `page_info()`

- `browser_type`
  - args: `text`
  - behavior: raw text input into focused element

- `browser_press_key`
  - args: `key`, optional `modifiers`
  - behavior: dispatches real CDP key events

- `browser_fill`
  - args: `selector`, `text`, optional `clear_first`, optional `timeout`
  - behavior: framework-aware form filling

- `browser_scroll`
  - args: x/y/dx/dy or named mode
  - behavior: wheel scroll

- `browser_js`
  - args: `expression`
  - behavior: evaluate JS in active tab and return serializable result

- `browser_cdp`
  - args: `method`, `params`, optional `session_id`
  - behavior: raw CDP escape hatch; high-power tool

- `browser_tabs`
  - args: optional `include_chrome`
  - behavior: list current page targets

- `browser_switch_tab`
  - args: `target_id`
  - behavior: activate and attach to a tab

- `browser_wait`
  - args: mode: `load | element | network_idle | seconds`, plus options
  - behavior: readiness helper

Advanced/escape-hatch tool:

- `browser_harness_run`
  - args: Python code string
  - behavior: execute a browser-harness snippet with helpers pre-imported
  - risk: high; should be permission-gated and not be the primary model path

Compatibility strategy:

- Reclaim canonical `browser_*` names for harness-backed tools after compatibility audit.
- Keep `pydoll_browser_*` names until users have a migration path.
- Consider aliases from old `browser_navigate`/`browser_interact` to harness tools if behavior is close enough.

## Backend Configuration

Add config similar to:

```yaml
browser:
  backend: harness  # harness | pydoll | disabled
  harness:
    enabled: true
    use_real_chrome: true
    domain_skills: false
    skills_dir: context/browser_harness
    remote_enabled: false
    screenshot_max_dim: 1800
```

Environment mapping:

- `BU_NAME`: derive from Penguin session/agent ID.
- `BH_AGENT_WORKSPACE`: derive from workspace path, likely `context/browser_harness/<session-or-project>/`.
- `BH_DOMAIN_SKILLS`: set only when domain-skill retrieval is explicitly enabled.
- `BROWSER_USE_API_KEY`: remote cloud support only; never required for local browser automation.

## Safety And Permission Model

Browser-harness attaches to a real logged-in browser. That is high leverage and high risk.

Required guardrails:

- Ask for explicit setup/attach consent before first use.
- Prefer `new_tab(url)` over `goto_url(url)` to avoid clobbering active user work.
- Require confirmation before purchases, payments, account changes, posting, deletion, form submission with sensitive impact, or sending messages/emails.
- Stop and ask the user at auth walls; do not infer or type credentials from screenshots.
- Treat `browser_cdp`, `browser_js`, and `browser_harness_run` as high-power tools.
- Redact screenshots/artifacts from logs if they may contain secrets or personal data.
- Ensure cloud/remote browsers are explicit opt-in and visibly report billing/timeout behavior.
- Ensure remote daemons are stopped on task/session completion when Penguin started them.

Tool metadata should mark browser tools with:

- network access
- external side effects
- possible sensitive-data exposure
- mutates external state for click/type/form/CDP tools
- approval required for high-risk actions
- not parallel-safe unless scoped to separate `BU_NAME`

## Implementation Plan

### Phase 0 - Spike / Prove The Backend

- [x] Add optional dependency path for browser-harness without changing defaults.
- [x] Add a small internal adapter that can call browser-harness helpers.
- [x] Implement `browser_open_tab`, `browser_page_info`, and `browser_harness_screenshot` only.
- [x] Verify local real-Chrome attach setup on macOS.
- [ ] Verify failure modes when Chrome remote debugging permission is missing.
- [x] Verify screenshot artifact return through current tool-result pipeline.
- [x] Verify the model can actually see a real browser-harness screenshot via `image_path` using modern vision-capable models.

Exit criteria:

- Penguin can open a new tab, wait for load, capture a screenshot, and report page info through native tools.
- Failure messages are actionable enough for a user to complete Chrome remote-debugging setup.
- Screenshot visibility is validated as model-visible content, not merely a saved file path.

### Phase 0.5 - General Image Ingestion

- [x] Add `read_image` as a general tool for local screenshots, diagrams, UI captures, and other image files.
- [x] Return normalized image artifact metadata: `filepath`, `artifact.image_path`, MIME type, dimensions, format, and byte size.
- [x] Add ActionXML support that injects image messages into the conversation using the same multimodal shape as screenshot tools.
- [x] Add permission mapping as a filesystem read operation.

Exit criteria:

- Any allowed local image can be promoted into model-visible conversation context without coupling to browser tools.

### Phase 1 - Minimal Useful Browser Tool Set

- [x] Add coordinate click and text/key input tools.
- [x] Add wait helpers for load, element, network idle, and sleep.
- [x] Add JS evaluation tool.
- [x] Add tab listing/switching tools.
- [x] Add permission metadata and approval gates for risky tools.
- [x] Keep PyDoll fallback intact.

Notes after Phase 1 implementation:

- Phase 1 is covered with mocked browser-harness modules; real Chrome attach remains a manual validation item because browser-harness is not yet an installed dependency in base dev/test.
- Risky tools carry permission metadata and map to `NETWORK_POST`; enforcement depends on Penguin permission mode/config.

Exit criteria:

- Penguin can complete a simple browser workflow using screenshot → click → verify.
- Penguin can inspect DOM state with JS when coordinates are insufficient.
- Tests cover schema registration and dispatch for the new tools.

### Phase 2 - Skill/Reference Integration

- [x] Reference browser-harness `SKILL.md` as a bundled Penguin browser skill.
- [x] Add interaction skills as progressively-loadable references.
- [x] Decide domain skills live under Penguin Skills in a browser-specific directory.
- [x] Implement hostname-based domain-skill lookup when enabled.
- [x] Add guidance to prompt/tool docs: browser interaction is screenshot/coordinate-first; docs/static scraping should prefer scripting/HTTP/JS extraction; DOM/CDP are escape hatches.
- [x] Add redaction/no-secret guidance for learned domain skills.

Notes after Phase 2 implementation:

- Domain-skill lookup is metadata-only and gated by `browser.harness.domain_skills: true`.
- When enabled, `browser_open_tab` and `browser_page_info` return matching browser domain skill directories/files for the current hostname; they do not auto-inject domain skill contents into the prompt.
- Domain skills are searched under `skills_dir/domain-skills/`, configured `domain_skill_roots`, and bundled browser domain-skill resources.

Exit criteria:

- General interaction guidance is available without prompt bloat.
- Domain skills are discoverable by hostname only when explicitly enabled.

### Phase 3 - Session/Subagent Isolation And Observability

Completed baseline:

- [x] Map each Penguin session/agent to deterministic `BU_NAME`.
- [x] Support separate browser daemons for parallel subagents via per-agent/per-session browser identity.
- [x] Track runtime ownership metadata: `started_by_penguin`, `session_id`, `agent_id`, `bu_name`, and `skills_dir`.
- [x] Add `browser_status` / doctor tool for active browser connection identity, environment, dependency, and page state.

Notes after Phase 3 baseline implementation:

- `browser_status` reports active browser-harness identity, ownership, environment, dependency/connectivity, and optional page state.
- Runtime browser tools derive identity per execution context, so separate session/agent contexts produce separate `BU_NAME` values.
- Cleanup remains intentionally deferred until owned-daemon shutdown semantics are verified against browser-harness admin APIs.

#### Phase 3.1 - Real Parallel Isolation Test

Priority: high.

Goal: prove real browser-harness sessions do not collide when Penguin runs multiple sessions/subagents.

Acceptance criteria:

- [x] Start two execution contexts with different `session_id`/`agent_id` pairs in deterministic tests.
- [x] Verify each context gets a distinct deterministic `BU_NAME`.
- [x] Open/page-info/screenshot through both contexts against real local Chrome.
- [x] Confirm no tab/session bleed in mocked helper state and real local Chrome smoke.
- [x] Document any browser-harness daemon limitation if true parallelism fails; no limitation observed in local smoke after serialized helper reload.

#### Phase 3.2 - Ownership Persistence

Priority: high before cleanup.

Goal: persist which browser-harness daemon identities Penguin started or owns.

Acceptance criteria:

- [x] Persist ownership records under a workspace-controlled path, defaulting to `context/browser_harness/ownership.json`.
- [x] Record `bu_name`, `session_id`, `agent_id`, `started_by_penguin`, `skills_dir`, timestamps, and backend where available.
- [x] Make `browser_status` distinguish persisted owned identities from external/user-managed identities.
- [x] Survive Penguin restart via file-backed records without falsely claiming unrelated names.

#### Phase 3.3 - Safe Cleanup Tool

Priority: medium-high; blocked on Phase 3.2.

Goal: clean only Penguin-owned browser-harness daemon state by default.

Acceptance criteria:

- [x] Add `browser_cleanup` with default `owned_only=true`.
- [x] Refuse non-owned cleanup unless `force=true` is explicitly provided; permission metadata marks cleanup high-risk/approval-required.
- [x] Never kill user Chrome blindly; cleanup delegates only to browser-harness daemon shutdown for the target `BU_NAME`.
- [x] Use browser-harness `admin.restart_daemon(name)` after reviewing its identity-checked shutdown semantics.
- [x] Test fake admin cleanup paths and real local owned-daemon cleanup smoke.

#### Phase 3.4 - TUI/Web Browser Status Surface

Priority: medium.

Goal: expose browser identity and connection state to humans while debugging browser/subagent workflows.

Acceptance criteria:

- [ ] Add or reuse a web/API route/event surface for `browser_status`.
- [ ] Surface active backend, connection state, `BU_NAME`, `session_id`, and `agent_id` in TUI/web where appropriate.
- [ ] Make failure states actionable: missing package, Chrome not debuggable, daemon unavailable, wrong identity.
- [ ] Avoid polling aggressively; status should be explicit or low-frequency.

Implementation notes after Phases 3.1-3.3:

- Ownership persistence is file-backed through `BrowserHarnessOwnershipStore`.
- `browser_cleanup` refuses unowned daemon names by default and removes ownership records after successful shutdown.
- Deterministic parallel-context tests cover identity isolation and ownership records. Real Chrome smoke on local port `9444` confirmed distinct `BU_NAME`s, page titles, screenshots, and ownership records for two sessions. Cleanup smoke on local port `9445` confirmed owned cleanup removes records and non-owned cleanup is refused.

Phase 3 exit criteria:

- Two real subagents/sessions can run isolated browser sessions without tab/session collision.
- Penguin can report browser identity/status and safely clean up only Penguin-owned daemon state.

### Phase 4 - Optional Library With Stable Penguin Backend Contract

Decision: use browser-harness as an optional library now, while designing Penguin's browser surface as a stable backend contract that can later support vendoring or alternate backends.

This is the hybrid architecture in practice:

- Penguin owns public tool contracts, artifact conventions, permission policy, session/agent identity, skill integration, error normalization, and fallback behavior.
- browser-harness owns Chrome attach, CDP plumbing, daemon mechanics, and low-level browser helpers.
- Vendoring remains an escape hatch if dependency churn, release instability, or API drift becomes costly.

Phase 4 tasks:
- [x] Verify browser-harness package source, release cadence, versioning, and install path: local/source only for now; no PyPI package.
- [x] Confirm license compatibility: MIT browser-harness under Penguin's AGPL distribution path.
- [x] Confirm Python/dependency constraints and document impact on Penguin's `>=3.9,<3.13` support window.
- [x] Decide optional extra name: keep `browser` as the user-facing extra and install the PyPI-available PyDoll fallback there.
- [x] Do not add a fake browser-harness dependency while package source/version story is not PyPI-resolvable.
- [x] Define the Penguin-owned browser backend adapter contract in docs: `context/decisions/browser-backend-contract.md`.
- [x] Add backend import/version diagnostics to `browser_status`.
- [x] Document fallback matrix: harness available, harness unavailable, Chrome attach unavailable, PyDoll fallback.
- [x] Ensure browser-harness-specific assumptions do not leak outside adapter/tools/skill layers.

Phase 4 exit criteria:

- Penguin can install/use browser-harness as an optional dependency without affecting base installs.
- Public browser tools remain Penguin-native and backend-agnostic enough to support future vendoring or alternate backend replacement.
- A decision note records why optional library is current path and what evidence would trigger vendoring.

## Testing Strategy

Unit tests:

- tool schema registration
- backend selection config
- missing optional dependency behavior
- environment mapping for `BU_NAME` and `BH_AGENT_WORKSPACE`
- permission metadata for risky tools
- artifact metadata for screenshots

Integration tests:

- adapter with mocked browser-harness helper module
- `browser_open_tab` happy path with fake helper responses
- `browser_screenshot` returns valid path metadata
- `browser_js` serializes primitives, lists, dicts, and errors
- daemon-not-running path produces setup guidance

Manual smoke tests:

- attach to local Chrome
- open docs page in new tab
- screenshot and click by coordinates
- fill a simple form
- navigate SPA and wait for network idle
- switch tabs
- stop/restart daemon

Optional remote tests:

- start remote browser only when `BROWSER_USE_API_KEY` is explicitly set
- verify remote daemon shutdown
- verify profile sync behavior if supported

## Open Questions

- Should `browser_harness_run` exist at all, or is raw Python execution too broad for default Penguin tools?
- Should Penguin maintain learned browser/domain skills in `.penguin/skills`, `context/browser_harness/domain-skills`, or a separate browser knowledge index?
- Should browser screenshots be persisted as conversation artifacts, task artifacts, or temporary files only?
- How should browser tools appear in OpenCode-compatible TUI events?
- Should browser attach be session-scoped, project-scoped, or agent-scoped by default?
- What is the minimum safe confirmation model for real-browser actions?
- Should Penguin expose Browser Use Cloud remote sessions, or keep local Chrome as the only supported MVP?

## Risks

- Real-browser automation can mutate user accounts and expose sensitive data.
- Browser-harness exact dependency pins may conflict with Penguin's broader runtime.
- Python `>=3.11` requirement excludes Penguin users on 3.9/3.10.
- Domain skills can become stale, site-specific, or privacy-sensitive.
- Screenshot-heavy workflows can generate large artifacts and sensitive logs.
- Raw CDP/JS tools are powerful enough to bypass normal page affordances.
- Remote cloud browser usage can leak cost if cleanup is not reliable.

## Acceptance Criteria For Initial PR

- [ ] New optional browser-harness backend is added without changing base install requirements.
- [ ] `browser_open_tab`, `browser_page_info`, and `browser_screenshot` work through ToolManager.
- [ ] Missing dependency / missing Chrome permission produces actionable diagnostics.
- [ ] PyDoll tools continue to register and work as before.
- [ ] Browser backend selection is configurable.
- [ ] Screenshot output is returned as a structured artifact/path, not just text.
- [ ] Basic tests cover registration, config selection, missing dependency, and successful mocked execution.
- [ ] Docs/task notes clearly state that domain skills are opt-in and not prompt-injected wholesale.

## Related Files

Penguin:

- `README.md`
- `architecture.md`
- `pyproject.toml`
- `penguin/tools/tool_manager.py`
- `penguin/tools/browser_tools.py`
- `penguin/tools/pydoll_tools.py`
- `context/tasks/tool-manager-modularization.md`
- `context/tasks/skills.md`

Browser-harness reference:

- `reference/browser-harness/README.md`
- `reference/browser-harness/SKILL.md`
- `reference/browser-harness/install.md`
- `reference/browser-harness/pyproject.toml`
- `reference/browser-harness/LICENSE`
- `reference/browser-harness/src/browser_harness/helpers.py`
- `reference/browser-harness/src/browser_harness/admin.py`
- `reference/browser-harness/src/browser_harness/_ipc.py`
- `reference/browser-harness/interaction-skills/`
- `reference/browser-harness/agent-workspace/domain-skills/`

## Strategic Take

The uncomfortable truth: Penguin's current browser layer is not yet a serious long-running browser agent surface. It is a collection of partially disabled or backend-specific tools.

Browser-harness is closer to the browser operating layer Penguin needs. The right play is to integrate it incrementally, keep the dependency optional, aggressively avoid prompt bloat from the skills corpus, and force everything through Penguin's tool metadata, permission, session, artifact, and UI/event systems.
