# MCP Integration Rewrite Plan

## Status

- Created: 2026-05-01
- Updated: 2026-05-01
- Owner: Penguin runtime/tooling
- State: proposed
- Bias: rewrite existing MCP integration instead of patching current stubs

## Executive Summary

Current MCP integration should be treated as disposable. It exposes and consumes a custom HTTP/JSON-lines shape that resembles MCP vocabulary but does not implement the real MCP protocol. The rewrite should make Penguin a real MCP host first: connect to external MCP servers and expose their tools as Penguin tools. Exposing Penguin itself as an MCP server is useful, but it is phase 2.

The leverage point is `ToolManager`: Penguin already has tool schemas, permission enforcement, path/context normalization, and execution dispatch. MCP should plug into that system rather than invent a parallel tool layer.

Post-skills-merge adjustment: the new skills runtime pattern is the right precedent. MCP should be a runtime-owned manager with small ToolManager facade methods, explicit status/diagnostics, and web/TUI visibility. Do not hardcode MCP tools only into the static registry and call it done.

## Goals

1. Consume local STDIO MCP servers as Penguin tools.
2. Consume remote Streamable HTTP MCP servers as Penguin tools.
3. Preserve Penguin permission semantics and workspace boundaries.
4. Use the official Python MCP SDK, not ad hoc protocol shims.
5. Make failures visible. No silent optional-pass behavior for configured MCP.
6. Eventually expose selected Penguin tools through a real MCP server.

## Non-Goals For First Pass

- MCP resources as first-class context sources.
- MCP prompts as Penguin prompt templates.
- Client-side sampling/elicitation support.
- Marketplace UI.
- Complex OAuth flows beyond token/header config.
- Backward compatibility with current `penguin.integrations.mcp` behavior.

## Evidence From Current Repo

- `penguin/tools/tool_manager.py` owns the canonical tool registry and maps public tool names to call targets.
- `ToolManager.execute_tool()` already handles context normalization, permission checks, and dispatch.
- `penguin/web/app.py` conditionally imports MCP components and silently swallows exceptions, which can hide broken MCP setup.
- `penguin/integrations/mcp/http_server.py` exposes `/api/v1/mcp/tools` and `/tools/{name}:call`; this is not MCP JSON-RPC/Streamable HTTP.
- `penguin/integrations/mcp/client.py` only proxies Penguin's custom HTTP route; it is not a real MCP client.
- `penguin/integrations/mcp/stdio_server.py` uses custom JSON-line methods `list_tools` and `call_tool`; this is not MCP `tools/list` / `tools/call` JSON-RPC.
- `penguin/integrations/mcp/adapter.py` imports `ModelContextProtocol`, which is not the Python SDK usage shown in current MCP docs.
- `pyproject.toml` has an `[mcp]` extra with auth dependencies but does not include the `mcp` SDK itself.
- Recent skills-system work added a useful integration pattern: a runtime-owned manager, ToolManager facade tools, core wiring, and web/TUI diagnostics. MCP should follow that pattern instead of becoming another isolated subsystem.
- MCP dynamic tool registration must coexist cleanly with static native tools and skills tools in ToolManager listing/execution paths.

## Evidence From Cached MCP Docs

Cached docs live in `context/docs_cache/modelcontextprotocol/`.

Key points:

- MCP follows host/client/server architecture: a host creates one MCP client per MCP server.
- Local MCP servers typically use STDIO; remote servers use Streamable HTTP.
- MCP is a JSON-RPC 2.0 protocol with lifecycle initialization and capability negotiation.
- Servers expose tools, resources, and prompts.
- Tools are discovered via `tools/list` and executed via `tools/call`.
- Python client docs use `ClientSession`, `StdioServerParameters`, and `stdio_client`.
- Python server docs use `mcp.server.fastmcp.FastMCP`.
- STDIO servers must not write logs to stdout because stdout carries protocol frames.

## Reference-Agent Lessons

Reviewed these reference implementations:

- `reference/opencode/packages/opencode/src/mcp/index.ts`
- `reference/opencode/packages/opencode/src/server/routes/mcp.ts`
- `reference/codex/codex-rs/codex-mcp/src/mcp_connection_manager.rs`
- `reference/codex/codex-rs/codex-mcp/src/mcp_tool_names.rs`
- `reference/codex/codex-rs/rmcp-client/src/stdio_server_launcher.rs`

Useful takeaways to steal shamelessly, minus language/runtime mismatch:

- Maintain explicit server status states: `connected`, `disabled`, `failed`, `needs_auth`, and later `needs_client_registration`. This is cleaner than boolean connected/not connected.
- Treat `tools/list_changed` notifications as a real cache invalidation event. OpenCode publishes a tools-changed bus event when a server says its tool list changed.
- Normalize MCP schemas defensively. OpenCode forces tool input schemas to object-shaped schemas with `properties` and `additionalProperties: false`; Penguin should do equivalent validation where safe.
- Timeouts need two separate knobs: startup/listing timeout and per-tool-call timeout. Codex defaults are roughly 30 seconds startup and 120 seconds tool calls; Penguin config should distinguish them.
- Tool naming must be collision-safe and model-safe. Codex uses `mcp__<server>__<tool>`, sanitizes names, hashes collisions, and caps model-visible names at 64 chars. Penguin should use this form, not `mcp::<server>::<tool>`, unless existing provider constraints prove colons are accepted everywhere.
- Preserve raw MCP identities separately from model-visible names. The callable name can be sanitized/hashed; the protocol call must still send the raw MCP `tool.name` to the owning server.
- Process lifecycle is not optional. Local STDIO server launch should set cwd/env deliberately, pipe stdout for protocol, capture stderr for logs, kill on drop, and on Unix prefer process-group cleanup for child subprocesses.
- Add status/connect/disconnect APIs early. OpenCode has `/mcp`, add, auth, connect, disconnect routes; Penguin does not need the full OAuth flow in phase 1, but status and reconnect controls are worth having.
- Cache only as an optimization. Codex has startup snapshots/caches for hosted connector tools; Penguin should avoid cache complexity in the MVP but design the manager so cache can be added without changing ToolManager contracts.
- Resources/prompts are second-pass. Both reference agents support or plan resources/prompts, but tools are the leverage point. Do not let resource/prompt support block tool calls.

Codex config precedents worth copying in spirit:

- Uses a top-level `mcp_servers` map keyed by server name. Penguin can use nested `mcp.servers` if that fits existing config style, but should support import/export from `mcp_servers`-style configs later.
- STDIO server fields: `command`, `args`, `env`, optional `env_vars`, and `cwd`.
- Streamable HTTP fields: `url`, `bearer_token_env_var`, `http_headers`, and `env_http_headers`.
- Reject inline plaintext bearer tokens; prefer env-var indirection for secrets.
- Per-server fields include `enabled`, `startup_timeout_sec`, `tool_timeout_sec`, tool allow/deny lists, and a default tool approval mode.
- Codex supports both global config and project/plugin-derived MCP servers; Penguin should plan for user-global plus project-local config, with project-local gated by trust/permissions.

## Proposed Architecture

```text
PenguinCore
  └── ToolManager
        ├── Native Penguin tools
        ├── Skills tools / skill facade
        └── MCPToolProvider
              ├── MCPConnectionManager
              │     ├── stdio server sessions
              │     └── streamable HTTP server sessions
              ├── tool discovery/cache
              ├── model-safe name allocation
              ├── schema conversion
              └── call dispatch to MCP sessions
```

### New Modules

```text
penguin/integrations/mcp/
  __init__.py
  config.py              # typed config models and validation
  manager.py             # MCPConnectionManager lifecycle
  names.py               # model-safe tool-name allocation and reverse lookup
  schema.py              # MCP inputSchema -> Penguin tool schema conversion
  transports.py          # stdio/http transport helpers
  diagnostics.py         # status snapshots and error formatting
  errors.py              # explicit integration exceptions
  server.py              # phase 2: expose Penguin via FastMCP
```

Companion Penguin-facing provider code should live with tools, not inside the protocol adapter:

```text
penguin/tools/providers/
  mcp.py                 # dynamic MCP tools as Penguin tools
```

The exact file split can change, but the boundary should not: `integrations/mcp/` owns MCP protocol/client/server concerns; `tools/providers/mcp.py` owns ToolManager-facing registration, schema exposure, and dispatch facade.

## Configuration Shape

Initial user-facing config should mirror common MCP host configs while fitting Penguin's config style. Prefer a nested shape for Penguin-native config, but design import/export so Codex/Claude-style `mcp_servers` maps are easy to ingest later.

```yaml
mcp:
  enabled: true
  initialize: lazy        # lazy | startup
  fail_on_startup_error: true
  tool_prefix: mcp
  servers:
    filesystem:
      transport: stdio
      command: npx
      args:
        - -y
        - '@modelcontextprotocol/server-filesystem'
        - /safe/root
      env: {}
      env_vars: []        # optional allowlist/inheritance descriptors, if supported
      cwd: null
      startup_timeout_sec: 30
      tool_timeout_sec: 120
      enabled: true
      default_tools_approval_mode: prompt
      enabled_tools: null
      disabled_tools: null

    sentry:
      transport: streamable_http
      url: https://mcp.sentry.dev/mcp
      bearer_token_env_var: SENTRY_MCP_TOKEN
      http_headers: {}
      env_http_headers: {}
      startup_timeout_sec: 30
      tool_timeout_sec: 120
      enabled: true
```

Security rule: do not support inline plaintext bearer tokens. Use `bearer_token_env_var` / env-backed headers. Secrets in config files are foot-guns with a nice YAML hat.

Config scope target:

- User-global MCP config for durable personal/server setup.
- Project-local MCP config for repo-specific servers, gated by project trust and permission policy.
- Later: config import from Claude Desktop/Codex-style configs.

Do not bury errors. If a configured MCP server cannot start/connect, report it clearly in CLI/TUI/web diagnostics.

### Status Shape

Use explicit states, not boolean soup:

```json
{
  "filesystem": {
    "status": "connected",
    "transport": "stdio",
    "tool_count": 4,
    "last_error": null
  },
  "sentry": {
    "status": "failed",
    "transport": "streamable_http",
    "tool_count": 0,
    "last_error": "401 Unauthorized"
  }
}
```

Allowed initial states:

- `connected`
- `disabled`
- `failed`
- `connecting`
- `disconnected`

Reserve these for remote auth work:

- `needs_auth`
- `needs_client_registration`

## Initialization Strategy

Default to lazy initialization on first tool-schema build or first MCP status request, with an explicit `mcp.initialize: startup` option for users who prefer fail-fast behavior.

Lazy initialization pros:

- Preserves Penguin startup time when MCP is installed but unused.
- Avoids launching long-lived STDIO subprocesses for sessions that never need external tools.
- Makes optional-extra behavior cleaner: no MCP SDK import or process startup unless MCP is configured/enabled.
- Better for large server sets and remote servers with auth/network latency.

Lazy initialization cons:

- First model turn that needs tool schemas may pay startup/listing latency.
- Failures appear later, which can feel spooky if diagnostics are weak.
- Tool schema generation becomes async/failure-prone; caching and status states must be tight.

Eager startup pros:

- Fail-fast diagnostics before a user asks the model to do work.
- Tool list is ready for the first completion request.
- Simpler mental model for status: configured servers connect at boot.

Eager startup cons:

- Slower startup and more background processes.
- Remote/auth failures can make Penguin feel broken even when MCP is irrelevant to the current session.
- More painful in web/server mode where many sessions may not need MCP.

Recommendation: default `lazy`, support `startup`, and expose `penguin mcp status/connect/reconnect` plus web/TUI status so failures are visible without forcing everyone to pay startup cost.

## Phase 1: MCP Host / Client Support

### Scope

Penguin can connect to configured MCP servers and use their tools as normal Penguin tools.

### Implementation Steps

1. Add dependency:
   - Add the official Python SDK to `[project.optional-dependencies].mcp` first, not the base install.
   - Use docs language like: `pip install "penguin-ai[mcp]"` or `uv sync --extra mcp` if you want MCP support.
   - Pin a compatible SDK range once tested; do not leave this floating forever.

2. Delete or quarantine current fake implementation:
   - Replace `client.py`, `stdio_server.py`, and `adapter.py` behavior.
   - Keep import compatibility only if cheap; do not preserve broken semantics.

3. Implement typed config:
   - Validate `transport`.
   - Validate command/args for STDIO.
   - Validate URL/headers for Streamable HTTP.
   - Expand env vars safely.
   - Support per-server `enabled`, `startup_timeout_sec`, and `tool_timeout_sec`.

4. Implement connection lifecycle:
   - One session per configured server.
   - Initialize sessions on demand or at app startup based on config.
   - Support cleanup on shutdown.
   - Support reconnect after failure.
   - Separate startup/listing timeout from per-tool timeout.
   - Capture STDIO stderr into logs/diagnostics; never let server logs contaminate stdout protocol frames.
   - Use explicit cwd/env resolution and avoid inheriting the whole host environment unless configured.

5. Tool discovery:
   - Call `session.list_tools()`.
   - Register each as `mcp__<server>__<tool>` unless tool-name constraints prove another separator is required.
   - Store original MCP server/tool metadata.
   - Convert `inputSchema` to Penguin's `input_schema` field without lossy hacks.
   - Sanitize model-visible names, hash collisions, and preserve a reverse lookup from model-visible tool name to `(server_name, raw_tool_name)`.
   - Handle `tools/list_changed` notifications by invalidating the provider's tool cache and emitting a Penguin UI/event-bus diagnostic.

6. Tool call dispatch:
   - Route `mcp__<server>__<tool>` to the owning session and raw MCP tool name.
   - Normalize result content into Penguin tool result text/dict.
   - Preserve structured content where possible.
   - Apply per-tool timeout.
   - Include server name and raw tool name in error/debug metadata.

7. Permission integration:
   - MCP tools should go through `ToolManager.execute_tool()` permission flow.
   - Add MCP-specific policy defaults:
     - Ask/deny for unknown external write-like tools if detectable.
     - Allowlist/denylist by server and tool glob.
   - Surface server identity in permission prompts.

8. Diagnostics:
   - Add status endpoint/API method listing configured servers, connection state, tools discovered, last error.
   - CLI/TUI should show MCP server failures rather than silently continuing.
   - Add connect/disconnect/reconnect controls for configured servers.

9. Skills-era ToolManager integration:
   - Follow the skills-manager shape: runtime-owned MCP manager, `ToolManager.set_core()` access where needed, `penguin/tools/providers/mcp.py` facade methods, and web/TUI route visibility.
   - Ensure static tools, skills tools, and dynamic MCP tools are merged deterministically in listing and schema generation.
   - Do not let MCP bypass `ToolManager.execute_tool()` permission and context paths.

### Acceptance Criteria

- A configured local STDIO MCP test server appears as Penguin tools.
- Penguin can call one MCP tool and return its output in a normal assistant turn.
- Failed server startup produces a visible diagnostic with server name and error.
- MCP tool names are stable, model-safe, length-bounded where required, and collision-safe.
- Permission-denied MCP tool calls fail through the same shape as native tools.
- Unit tests cover config validation, discovery, dispatch, timeout, and failure state.
- Integration test uses a tiny Python FastMCP/stdio server.
- Tool list changes from an MCP server invalidate cached schemas or are explicitly documented as unsupported in MVP.

## Phase 1.5: MCP Host Hardening And E2E Validation

### Scope

Make Penguin comfortable to test as an MCP host/client before exposing Penguin itself as an MCP server. This phase is about diagnostics, real config shapes, and one-command smoke validation against real STDIO servers such as `@modelcontextprotocol/server-everything` and `chrome-devtools-mcp`.

### Implementation Steps

1. Accept common host config shapes:
   - Penguin-native `mcp.servers`.
   - Claude-style top-level `mcpServers`.
   - Codex-style top-level `mcp_servers` where practical.
   - Keep Streamable HTTP/SSE rejected with a clear unsupported-transport error until that phase lands.

2. Add diagnostics and lifecycle controls:
   - ToolManager facade methods for MCP status, refresh, reconnect, and close.
   - Web/API endpoints for `/api/v1/mcp`, reconnect, and close, following the skills-route precedent.
   - Status payload should include availability, initialized/discovered state, server status, transport, command, tool count, and last error.

3. Add smoke validation tooling:
   - Scriptable STDIO smoke runner using Penguin's `MCPClientManager`, not Inspector only.
   - Example target: `npx -y @modelcontextprotocol/server-everything`.
   - Example high-value target: `npx -y chrome-devtools-mcp@latest --no-usage-statistics --no-update-checks`.

4. Preserve permission and provider boundaries:
   - MCP tool execution still routes through `ToolManager.execute_tool()`.
   - Browser/Chrome MCP tools should remain high-risk and prompt/deny according to permission policy.

### Acceptance Criteria

- Penguin can parse `mcp.servers`, `mcpServers`, and `mcp_servers` config shapes.
- `/api/v1/mcp?refresh=true` reports configured server status without hiding errors.
- ToolManager can refresh/reconnect/close MCP sessions without restarting Penguin.
- A local smoke script can list tools from a real STDIO MCP server when `penguin-ai[mcp]` is installed on Python 3.10+.
- Focused tests cover config aliases, diagnostics, refresh/reconnect/close facades, and disabled/no-SDK behavior.

## Phase 2: Penguin As An MCP Server

Expose Penguin through a real SDK-backed MCP server. Split this into two tracks: a narrow tool-level server for protocol correctness, then an agent-level server that exposes Penguin as a software-engineering runtime.

### Phase 2A: Tool-Level MCP Server

#### Scope

Expose selected low-risk Penguin tools through an SDK-backed MCP server. This is a protocol foundation, not the final product shape.

#### Implementation Steps

1. Build `FastMCP` server wrapper.
2. Register allowlisted Penguin tools as MCP tools.
3. Convert Penguin tool schemas to MCP-friendly function signatures/input schemas where practical.
4. Route calls into `ToolManager.execute_tool()`.
5. Preserve permission checks and workspace restrictions.
6. Support STDIO first; Streamable HTTP second.
7. Ensure all server logging goes to stderr for STDIO.

#### Default Exposure Policy

Deny by default for dangerous tools:

- browser automation
- shell execution
- file writes/patches unless explicitly allowed
- workspace reindexing
- sub-agent spawning/delegation unless explicitly allowed
- external MCP-hosted tools (`mcp__*`) unless explicitly allowed

Expose read-only tools first:

- `read_file`
- `list_files`
- `find_file`
- `grep_search`
- `analyze_project`

#### Acceptance Criteria

- MCP Inspector can discover Penguin tools via real `tools/list`.
- A read-only Penguin tool can be called via real `tools/call`.
- STDIO mode emits no protocol-breaking stdout logs.
- Denied tools are absent or fail with clear permission errors.
- Tool calls route through `ToolManager.execute_tool()`, not direct private registry calls.

### Phase 2B: Penguin Runtime MCP Server

#### Scope

Expose Penguin's differentiated runtime surfaces, not a generic chat wrapper. The target audience is Link, IDEs, Claude Desktop, and other agent hosts that want to delegate durable software work into Penguin's project/task/runtime system.

Primary docs to keep aligned:

- `docs/docs/system/run-mode.md` — autonomous execution and continuous task processing.
- `docs/docs/usage/project_management.md` — SQLite-backed projects/tasks, dependency metadata, task truth.
- `docs/docs/usage/task_management.md` — lifecycle status plus ITUV phase semantics.
- `docs/docs/system/blueprints.md` — spec-driven task DAGs, recipes, acceptance criteria, agent hints.
- `docs/docs/system/orchestration.md` — ITUV workflow phases, native/Temporal backend shape.
- `features.md` — competitive feature bar and Penguin differentiators.

#### Default Exposure Policy

If a user intentionally connects a Penguin MCP server, it should expose Penguin's differentiated control-plane by default. Hiding everything creates a bad first-run experience. However, autonomous execution and high-risk mutation still need explicit opt-in.

Default-on Phase 2B surfaces:

- Project/task management tools.
- Blueprint lint/status/graph tools, and sync once its internals are verified.
- Read-only session/context/evidence/checkpoint listing tools.

Explicit opt-in surfaces:

- RunMode execution tools.
- ITUV workflow start/signal tools.
- Cancellation/resume operations that mutate active execution state.
- Raw dangerous low-level tools: shell, writes, patches, browser, subagents, external MCP-hosted tools.

Runtime opt-in should support at least one explicit flag/config/env path, for example:

- `scripts/penguin_mcp_server.py --allow-runtime-tools`
- `mcp.server.expose_runtime_tools: true`
- `PENGUIN_MCP_ALLOW_RUNTIME_TOOLS=1`

#### Implementation Layout

Use focused tool modules rather than growing `server.py` into a god file:

```text
penguin/integrations/mcp/server_tools/
  __init__.py
  pm.py
  blueprints.py
  runmode.py
  sessions.py
  artifacts.py
```

Shared helpers should prefer web/API service-layer payload construction when available. If route logic contains the current truth, extract small shared service functions instead of duplicating stale Python API behavior in MCP.

#### Slice 1: PM Tools Default-On

Status: implemented in `penguin/integrations/mcp/server_tools/pm.py` with shared web/MCP payload serializers in `penguin/web/services/project_payloads.py`.

Expose Penguin's project/task truth as the first Phase 2B control-plane surface.

Tools:

- `penguin_pm_list_projects` — list project containers and lifecycle summaries.
- `penguin_pm_create_project` — create a project with name, description, workspace/root metadata.
- `penguin_pm_get_project` — return one project by ID with tasks included by default.
- `penguin_pm_list_tasks` — list tasks by project/status/parent task. Phase/dependency-readiness filters remain future work.
- `penguin_pm_create_task` — create tasks with description, priority, dependencies, acceptance criteria, resource constraints, and metadata.
- `penguin_pm_get_task` — return rich task truth: status, phase, dependency specs, artifact evidence, recipe, metadata, clarification requests.

Defer or gate until lifecycle validation is confirmed:

- `penguin_pm_update_task` — update status, phase, metadata, dependency specs, recipe, or artifact evidence through validated lifecycle paths.

Task creation should support rich fields immediately. Fields that are first-class in `ProjectManager` should be stored first-class; unsupported-but-useful fields should be preserved under metadata and reported as metadata-preserved, not silently dropped or faked.

#### Slice 2: Blueprint Tools Default-On

Status: implemented in `penguin/integrations/mcp/server_tools/blueprints.py` with shared Blueprint payload serializers in `penguin/web/services/blueprint_payloads.py`.

Expose Penguin's spec-to-task DAG capability.

Tools:

- `penguin_blueprint_lint` — parse/lint Markdown/YAML/JSON blueprints and return structured diagnostics for duplicate IDs, missing deps, cycles, and missing acceptance criteria.
- `penguin_blueprint_graph` — return the dependency DAG in a machine-readable form, optionally DOT/JSON.
- `penguin_blueprint_status` — map blueprint-derived project tasks to current DAG/status data.

Defer until internals are verified and idempotency is clear:

- `penguin_blueprint_sync` — import/sync a blueprint into a project as tasks/dependency graph without executing it.
- Phase/dependency-readiness filters and richer blueprint/task status correlation.

#### Slice 3: Runtime / RunMode Explicit Opt-In

Expose long-running execution as durable jobs, not blocking tool calls. These tools are not registered unless runtime tools are explicitly enabled.

Tools:

- `penguin_runmode_start_task` — start a bounded RunMode task with name, description, context, max iterations, time limit, and optional project/task binding.
- `penguin_runmode_start_continuous` — start continuous task processing for a project or named task queue, with explicit time/resource limits.
- `penguin_runmode_status` — return status, phase, current iteration, active task, stop reason, waiting-input state, and latest artifact evidence.
- `penguin_runmode_cancel` — cancel or interrupt a running RunMode job.
- `penguin_runmode_resume_clarification` — answer a clarification request and resume through the same lifecycle path.

Implementation note: this slice needs a durable-ish job registry/status handle before exposing start operations. Do not implement it as a blocking `process_message("do task")` wrapper.

#### Slice 4: Orchestration / ITUV Explicit Opt-In

Expose the ITUV lifecycle explicitly instead of hiding it behind prose. Starting/signaling workflows mutates execution state, so keep this behind runtime opt-in until policy is nailed down.

Tools:

- `penguin_ituv_start_workflow` — start an ITUV workflow for a task or blueprint item.
- `penguin_ituv_status` — return implement/test/use/verify phase, retry state, blockers, and artifact evidence.
- `penguin_ituv_signal` — pause, resume, cancel, or nudge a workflow.

#### Slice 5: Sessions / Context / Evidence Default-On Read Paths

Expose enough runtime context for another host to coordinate safely. Keep listing/summarization default-on; restoration/mutation should be opt-in or separately gated.

Tools:

- `penguin_session_list` — list active/recent sessions and associated projects/tasks.
- `penguin_session_summary` — return a compact session/context summary suitable for handoff.
- `penguin_artifacts_list` — list files, diffs, command outputs, screenshots, or evidence attached to a task/run.
- `penguin_checkpoints_list` — list checkpoints for audit/handoff.

Gated:

- `penguin_checkpoint_restore` — controlled rollback.

#### Design Requirements

- Long-running tools must return durable IDs and status handles. Do not block an MCP call for an entire autonomous run.
- Every task/run payload should expose lifecycle truth: `status`, `phase`, dependencies, artifact evidence, recipe, metadata, and clarification state.
- Project/task scope must be explicit; defaulting to a hidden global project is a foot-gun.
- Clarification-needed states must survive as first-class MCP results, not become fake failures.
- Cancellation must be explicit and reliable.
- Permission boundaries must be stricter than direct local Penguin usage because another host/agent may be driving it.
- Outputs should include artifact paths/evidence and machine-readable state, not just prose.
- Phase 2B should prefer existing web/API and `PenguinAPI` lifecycle semantics where those are truthful, rather than inventing another parallel task API.

#### Acceptance Criteria

- External MCP clients can create/list projects and tasks with rich lifecycle fields.
- External MCP clients can start a bounded RunMode job and receive a durable run/task ID.
- Polling returns truthful non-terminal states including `running`, `pending_review`, `waiting_input`, `failed`, `cancelled`, and `completed`.
- Clarification-needed states can be resumed via MCP.
- Blueprint lint/sync can create dependency-aware task graphs without execution.
- Artifact evidence is visible through MCP for completed or pending-review work.
- Dangerous low-level tools remain unavailable unless explicitly exposed.
- Link can use this as a deep Penguin orchestration bridge rather than a generic chat endpoint.

## Phase 3: Resources, Prompts, Notifications

### Resources

Potential mappings:

- Workspace files as MCP resources.
- Conversation/session summaries as resources.
- Project/task records as resources.
- Docs cache pages as resources.

### Prompts

Potential mappings:

- Penguin prompt modes as MCP prompts.
- Task recipes as MCP prompts.
- Project bootstrap prompts.

### Notifications

- Support `tools/list_changed` when Penguin tool registry changes.
- Emit diagnostics when MCP server capabilities change.

## Test Plan

### Unit Tests

- Config parsing and env expansion.
- Server name/tool name normalization.
- Name collision hashing and raw-name reverse lookup.
- Schema conversion.
- Result normalization.
- Permission policy decisions.
- Error classification.
- Status-state transitions.
- Tool-list-changed invalidation.

### Integration Tests

- Start a local SDK-backed STDIO MCP server.
- Discover tools through Penguin.
- Execute a tool through `ToolManager.execute_tool()`.
- Simulate startup failure.
- Simulate tool timeout.
- Simulate malformed tool result.
- Simulate duplicate/sanitized tool names from two servers.
- Confirm STDIO stderr is captured and stdout remains protocol-only.
- Confirm disconnect/reconnect updates status and rediscovery.
- Confirm static tools, skills tools, and MCP tools all appear without clobbering each other.

### Manual Validation

- Use MCP Inspector against Penguin server in phase 2.
- Use a known public/local MCP server as a Penguin client target.
- Confirm CLI/TUI diagnostics make failures obvious.

## Risks And Sharp Edges

- MCP SDK API may shift; pin/test against a known version.
- Long-running STDIO subprocesses need reliable cleanup.
- Tool result content blocks can be richer than Penguin currently expects.
- OAuth/remote auth can balloon scope fast. Keep first pass token/header based.
- Permission semantics are easy to bypass if MCP tools are registered outside `ToolManager.execute_tool()`.
- Silent optional imports will create ghost bugs. Kill silent failure for configured MCP.
- Tool-name constraints differ across model/provider surfaces. Use conservative names and tests; do not assume colons/slashes survive every schema path.
- STDIO process cleanup is easy to get 90% right and still leak grandchildren. Test it.

## Suggested Milestones

### Milestone 1: Local STDIO Client MVP

- Dependency added.
- Config model added.
- One local STDIO server can be discovered.
- One MCP tool can be called as `mcp__<server>__<tool>`.
- Basic tests pass.

### Milestone 1.5: Host Hardening And Real-Server Smoke

- Common config aliases parse correctly.
- MCP status/refresh/reconnect/close surfaces exist in ToolManager and web/API.
- Smoke script validates STDIO discovery against `server-everything` and Chrome DevTools MCP.
- Diagnostics clearly show missing SDK, failed command startup, unsupported transport, and tool counts.

### Milestone 2: Robust Client

- Reconnect/cleanup.
- Diagnostics.
- Allow/deny policy.
- Result normalization.
- Streamable HTTP support if SDK support is stable.
- Connect/disconnect/reconnect controls.
- Tool-list-changed cache invalidation.

### Milestone 3: Penguin As MCP Server

- SDK-backed STDIO server.
- Read-only allowlisted tools exposed.
- MCP Inspector validation.

### Milestone 4: Product Polish

- CLI/TUI settings/status.
- Web API status surface.
- Docs.
- Example configs.

## Decisions And Remaining Open Questions

1. Dependency packaging: MCP starts as an optional extra. Docs should say `install Penguin with MCP support` and show the appropriate extra install command.
2. Initialization: default lazy on first tool-schema build/status request; support eager startup via config for fail-fast users.
3. Config scope: support both user-global and project-local MCP config. Use Codex/Claude patterns as import/export references where practical.
4. Permissions: external MCP default approval depends on Penguin's permission system, but MVP should route every MCP call through `ToolManager.execute_tool()` and support per-server/per-tool approval policy.
5. Streamable HTTP/OAuth: token/env-header support can land in robust client phase; full OAuth/client registration belongs in the final/security-focused phase.
6. Tool-name constraints: still open. Assume conservative `mcp__server__tool`, length cap, sanitization, hash collisions, and reverse lookup until provider paths are empirically tested.

## Recommendation

Start with Milestone 1, immediately follow with Milestone 1.5 for real-server validation, and include the reference-agent basics that prevent pain later: explicit status states, conservative `mcp__server__tool` naming, raw-name reverse lookup, separate startup/tool timeouts, and STDIO process cleanup. Do not touch resources, prompts, OAuth, or server exposure until a local STDIO MCP tool can be discovered and called through Penguin's existing ToolManager with tests. Anything else is scope creep wearing a fake mustache.
