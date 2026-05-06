# MCP Runtime Surface Architecture

## Status

- Created: 2026-05-04
- Scope: Penguin MCP host/client and server/runtime-control-plane architecture
- Audience: Penguin maintainers, Link/orchestration integrators, future agent implementers

## Executive Summary

Penguin now has two MCP roles:

1. **MCP host/client** — Penguin consumes external MCP servers and exposes their tools to Penguin's normal ToolManager path.
2. **MCP server** — Penguin exposes selected Penguin capabilities to external MCP hosts.

The strategic value is not only exposing low-level file/search tools. The differentiated surface is Penguin's durable software-engineering runtime:

- Project Management (PM)
- Blueprints
- RunMode
- ITUV lifecycle state
- artifacts/evidence
- sessions/checkpoints
- runtime job records

A host like Link, Claude Desktop, an IDE, or another agent should be able to use Penguin as a specialized software-engineering runtime, not merely as a bag of file tools.

## Layer Model

```text
External MCP Hosts
  ├── Claude Desktop / Inspector / Link / IDEs / other agents
  │
  ▼
Penguin MCP Server
  ├── Phase 2A: safe low-level tools
  ├── Phase 2B: PM / Blueprint / RunMode / ITUV runtime tools
  │
  ▼
Penguin Runtime
  ├── ToolManager
  ├── ProjectManager / ProjectStorage
  ├── RunMode
  ├── Workflow / ITUV state
  ├── Conversation/session/checkpoint systems
  └── file/tool/security boundaries
```

For consuming external MCP servers:

```text
Penguin ToolManager
  └── MCP tool provider
        └── MCP client manager
              ├── stdio MCP server sessions
              └── future remote transports
```

## Host vs Server Distinction

### Penguin As MCP Host / Client

This is Phase 1 / 1.5.

Penguin connects to external MCP servers such as:

- Chrome DevTools MCP
- GitHub MCP
- filesystem MCP
- Sentry MCP
- database/search/browser MCP servers

Those tools appear to Penguin as dynamically discovered tools using model-safe names like:

```text
mcp__chrome_devtools__navigate
mcp__chrome_devtools__evaluate
```

Important properties:

- dynamic tool discovery
- STDIO sessions are persistent for process lifetime
- calls route through `ToolManager.execute_tool()` permission semantics
- configured servers expose diagnostics/status

### Penguin As MCP Server

This is Phase 2A / 2B.

External MCP hosts connect to Penguin and see Penguin-native capabilities.

#### Phase 2A: Tool-Level Server

Safe low-level tools, default-on:

- `read_file`
- `list_files`
- `find_file`
- `grep_search`
- `analyze_project`

This validates protocol compliance and enables basic workspace introspection.

#### Phase 2B: Runtime / Control-Plane Server

Penguin-specific runtime tools:

- PM tools: projects and tasks
- Blueprint tools: lint, graph, sync, status
- RunMode tools: start/status/cancel/resume clarification
- ITUV tools: lifecycle status, frontier, mutation guardrails
- future Session/Artifact/Checkpoint/runtime job records

This is the strategic surface.

## Default-On vs Runtime-Gated Tools

### Default-On

Default-on means: if a user intentionally starts Penguin's MCP server, these tools appear without extra flags.

Current default-on groups:

- safe low-level read/search tools
- PM control-plane tools
- Blueprint tools

Rationale:

- PM and Blueprint tools define and inspect intended work.
- They are central to Penguin's differentiated value.
- They do not directly launch autonomous execution.

### Runtime-Gated

Runtime-gated tools require:

```bash
scripts/penguin_mcp_server.py --allow-runtime-tools
```

Current runtime-gated groups:

- RunMode tools
- ITUV tools

Rationale:

- These can start work, mutate lifecycle state, cancel jobs, or mark tasks review-ready.
- They need explicit operator intent.
- Future public/remote deployments may need stronger policy controls.

## Current Implemented Slices

### Phase 1: MCP Host / Client

- optional MCP SDK dependency
- local STDIO MCP client support
- dynamic names `mcp__server__tool`
- ToolManager provider bridge
- permission mapping

### Phase 1.5: Host Diagnostics / Smoke

- config aliases: `mcp.servers`, `mcpServers`, `mcp_servers`
- status/reconnect/refresh APIs
- product smoke script
- real E2E with `@modelcontextprotocol/server-everything` and Chrome DevTools MCP

### Phase 2A: Penguin Tool-Level Server

- FastMCP-backed stdio server
- safe read/search tools exposed
- MCP Inspector validated

### Phase 2B Slice 1: PM Tools

Default-on:

- `penguin_pm_list_projects`
- `penguin_pm_create_project`
- `penguin_pm_get_project`
- `penguin_pm_list_tasks`
- `penguin_pm_create_task`
- `penguin_pm_get_task`

### Phase 2B Slice 2 / 2.5: Blueprint Tools

Default-on:

- `penguin_blueprint_lint`
- `penguin_blueprint_graph`
- `penguin_blueprint_status`
- `penguin_blueprint_sync`

`penguin_blueprint_sync` defaults to dry-run and refuses invalid blueprints.

### Phase 2B Slice 3: RunMode Tools

Runtime-gated:

- `penguin_runmode_capabilities`
- `penguin_runmode_list_jobs`
- `penguin_runmode_get_job`
- `penguin_runmode_start_task`
- `penguin_runmode_start_project`
- `penguin_runmode_cancel_job`
- `penguin_runmode_resume_clarification`

Current job registry is in-memory only. Durable records are planned for Slice 5.

### Phase 2B Slice 4: ITUV Tools

Runtime-gated:

- `penguin_ituv_capabilities`
- `penguin_ituv_status`
- `penguin_ituv_frontier`
- `penguin_ituv_signal`
- `penguin_ituv_mark_ready_for_review`
- `penguin_ituv_record_artifact`

Mutation tools default to dry-run and enforce conservative transition semantics.

## State Preservation

| State | Current Preservation |
| --- | --- |
| Projects | durable in project DB |
| Tasks | durable in project DB |
| Blueprint sync results | durable as tasks/dependencies |
| External MCP server sessions | process-lifetime |
| RunMode MCP job records | in-memory only today |
| Job cancellation handles | in-memory only today |
| Conversation/session history | Penguin has persistence, but MCP runtime-job recovery is not wired yet |

## Local vs Cloud / Link Considerations

For local Penguin, project/task/runtime job state should live close to `ProjectStorage`.

For Link/cloud:

- runtime jobs should become first-class DB records
- project/task/session IDs should be explicit and stable
- job status should be evented/streamed
- artifacts/evidence should be addressable separately
- cancellation should coordinate with worker processes, not local threads only

Do not overbuild Link's distributed runtime inside local Penguin, but keep the local model mirrorable:

- stable job IDs
- explicit foreign keys
- structured status enum
- compact summaries
- JSON metadata
- no arbitrary Python object persistence

## Security Notes

- Default-on does not mean unrestricted.
- Runtime mutation/execution stays CLI-gated.
- Browser/Chrome MCP tools can inspect browser state; use isolated profiles for tests.
- External MCP tools route through permission checks.
- Penguin-as-server low-level writes/shell/browser/subagents remain denied by default unless explicitly allowlisted.

## Known Debt

- Runtime job records are not durable yet.
- ITUV phase transition policy is currently MCP-local; ProjectManager should eventually own it.
- Artifact evidence writes currently touch task storage directly from the MCP ITUV tool layer; ProjectManager needs a public helper.
- MCP server tool catalog should become public docs/reference before release.
