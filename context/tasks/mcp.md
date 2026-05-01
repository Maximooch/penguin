# MCP Integration Rewrite Plan

## Status

- Created: 2026-05-01
- Owner: Penguin runtime/tooling
- State: proposed
- Bias: rewrite existing MCP integration instead of patching current stubs

## Executive Summary

Current MCP integration should be treated as disposable. It exposes and consumes a custom HTTP/JSON-lines shape that resembles MCP vocabulary but does not implement the real MCP protocol. The rewrite should make Penguin a real MCP host first: connect to external MCP servers and expose their tools as Penguin tools. Exposing Penguin itself as an MCP server is useful, but it is phase 2.

The leverage point is `ToolManager`: Penguin already has tool schemas, permission enforcement, path/context normalization, and execution dispatch. MCP should plug into that system rather than invent a parallel tool layer.

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

## Proposed Architecture

```text
PenguinCore
  └── ToolManager
        ├── Native Penguin tools
        └── MCPToolProvider
              ├── MCPConnectionManager
              │     ├── stdio server sessions
              │     └── streamable HTTP server sessions
              ├── tool discovery/cache
              ├── schema conversion
              └── call dispatch to MCP sessions
```

### New Modules

```text
penguin/integrations/mcp/
  __init__.py
  config.py              # typed config models and validation
  manager.py             # MCPConnectionManager lifecycle
  provider.py            # registers MCP tools into ToolManager
  schema.py              # MCP inputSchema -> Penguin tool schema conversion
  transports.py          # stdio/http transport helpers
  errors.py              # explicit error types
  server.py              # phase 2: expose Penguin via FastMCP
```

The exact file split can change, but the boundaries should not.

## Configuration Shape

Initial user-facing config should mirror common MCP host configs:

```yaml
mcp:
  enabled: true
  servers:
    filesystem:
      transport: stdio
      command: npx
      args:
        - -y
        - '@modelcontextprotocol/server-filesystem'
        - /safe/root
      env: {}
      cwd: null
      timeout_seconds: 30

    sentry:
      transport: streamable_http
      url: https://mcp.sentry.dev/mcp
      headers:
        Authorization: Bearer ${SENTRY_MCP_TOKEN}
      timeout_seconds: 30
  tool_prefix: mcp
  fail_on_startup_error: true
```

Do not bury errors. If a configured MCP server cannot start/connect, report it clearly in CLI/TUI/web diagnostics.

## Phase 1: MCP Host / Client Support

### Scope

Penguin can connect to configured MCP servers and use their tools as normal Penguin tools.

### Implementation Steps

1. Add dependency:
   - `mcp>=1.2.0` or current compatible version.
   - Put it in `[project.optional-dependencies].mcp` first unless product decision says base install should include it.

2. Delete or quarantine current fake implementation:
   - Replace `client.py`, `stdio_server.py`, and `adapter.py` behavior.
   - Keep import compatibility only if cheap; do not preserve broken semantics.

3. Implement typed config:
   - Validate `transport`.
   - Validate command/args for STDIO.
   - Validate URL/headers for Streamable HTTP.
   - Expand env vars safely.

4. Implement connection lifecycle:
   - One session per configured server.
   - Initialize sessions on demand or at app startup based on config.
   - Support cleanup on shutdown.
   - Support reconnect after failure.

5. Tool discovery:
   - Call `session.list_tools()`.
   - Register each as `mcp::<server>::<tool>`.
   - Store original MCP server/tool metadata.
   - Convert `inputSchema` to Penguin's `input_schema` field without lossy hacks.

6. Tool call dispatch:
   - Route `mcp::<server>::<tool>` to `session.call_tool(tool_name, arguments)`.
   - Normalize result content into Penguin tool result text/dict.
   - Preserve structured content where possible.
   - Apply timeouts.

7. Permission integration:
   - MCP tools should go through `ToolManager.execute_tool()` permission flow.
   - Add MCP-specific policy defaults:
     - Ask/deny for unknown external write-like tools if detectable.
     - Allowlist/denylist by server and tool glob.
   - Surface server identity in permission prompts.

8. Diagnostics:
   - Add status endpoint/API method listing configured servers, connection state, tools discovered, last error.
   - CLI/TUI should show MCP server failures rather than silently continuing.

### Acceptance Criteria

- A configured local STDIO MCP test server appears as Penguin tools.
- Penguin can call one MCP tool and return its output in a normal assistant turn.
- Failed server startup produces a visible diagnostic with server name and error.
- MCP tool names are stable and collision-safe.
- Permission-denied MCP tool calls fail through the same shape as native tools.
- Unit tests cover config validation, discovery, dispatch, timeout, and failure state.
- Integration test uses a tiny Python FastMCP/stdio server.

## Phase 2: Real MCP Server For Penguin Tools

### Scope

Expose selected Penguin tools through an SDK-backed MCP server.

### Implementation Steps

1. Build `FastMCP` server wrapper.
2. Register allowlisted Penguin tools as MCP tools.
3. Convert Penguin tool schemas to MCP `inputSchema`.
4. Route calls into `ToolManager.execute_tool()`.
5. Preserve permission checks and workspace restrictions.
6. Support STDIO first; Streamable HTTP second.
7. Ensure all server logging goes to stderr for STDIO.

### Default Exposure Policy

Deny by default for dangerous tools:

- browser automation
- shell execution
- file writes/patches unless explicitly allowed
- workspace reindexing
- sub-agent spawning/delegation unless explicitly allowed

Expose read-only tools first:

- `read_file`
- `list_files`
- `find_file`
- `grep_search`
- `analyze_project`

### Acceptance Criteria

- Claude Desktop or MCP Inspector can discover Penguin tools via real `tools/list`.
- A read-only Penguin tool can be called via real `tools/call`.
- STDIO mode emits no protocol-breaking stdout logs.
- Denied tools are absent or fail with clear permission errors.

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
- Schema conversion.
- Result normalization.
- Permission policy decisions.
- Error classification.

### Integration Tests

- Start a local SDK-backed STDIO MCP server.
- Discover tools through Penguin.
- Execute a tool through `ToolManager.execute_tool()`.
- Simulate startup failure.
- Simulate tool timeout.
- Simulate malformed tool result.

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

## Suggested Milestones

### Milestone 1: Local STDIO Client MVP

- Dependency added.
- Config model added.
- One local STDIO server can be discovered.
- One MCP tool can be called as `mcp::<server>::<tool>`.
- Basic tests pass.

### Milestone 2: Robust Client

- Reconnect/cleanup.
- Diagnostics.
- Allow/deny policy.
- Result normalization.
- Streamable HTTP support if SDK support is stable.

### Milestone 3: Penguin As MCP Server

- SDK-backed STDIO server.
- Read-only allowlisted tools exposed.
- MCP Inspector validation.

### Milestone 4: Product Polish

- CLI/TUI settings/status.
- Web API status surface.
- Docs.
- Example configs.

## Open Questions

1. Should `mcp` be a base dependency or optional extra?
2. Should MCP servers initialize eagerly at Penguin startup or lazily on first tool-schema build?
3. Do we want project-local MCP config, user-global MCP config, or both?
4. Should external MCP tools default to ask-before-call, or should trust be per-server?
5. How much Streamable HTTP/OAuth should be in the first production cut?

## Recommendation

Start with Milestone 1 only. Do not touch resources, prompts, OAuth, or server exposure until a local STDIO MCP tool can be discovered and called through Penguin's existing ToolManager with tests. Anything else is scope creep wearing a fake mustache.
