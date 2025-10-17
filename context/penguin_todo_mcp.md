### MCP Integration – Penguin TODO

This document tracks the minimal, high‑leverage integration of the Model Context Protocol (MCP) into Penguin as both a server (export selected Penguin tools) and a client (import remote MCP tools).

### Goals
- Expose a safe, allow‑listed subset of Penguin tools via MCP.
- Consume remote MCP servers and present their tools as Penguin tools.
- Keep startup fast (lazy init), default to read‑only and local‑only.
 - No dependency on Agent Browser; prefer in‑house client and optional web panel.

### Deliverables (MVP)
- Optional install: `penguin-ai[mcp]` with client/server deps.
- MCP Server: stdio transport, allow‑listed tools only.
- MCP Client Bridge: register remote MCP tools into `ToolManager` under `mcp::<server>::<tool>`.
- Config: `config.yml` entries for server (allowlist) and client servers.
- CLI: `penguin mcp {serve, add-server, list-tools, call}`.
- Tests: echo/round‑trip + one real tool (`grep_search`).
 - Optional: simple Penguin MCP Panel web UI for discovery and calls.

### Scope & Constraints
- Default deny: read‑only tools only; no write/edit tools exposed by default.
- Local‑only by default (stdio). SSE/remote requires explicit config + token.
- Lazy connect to remote servers on first invocation.

### Implementation Tasks
1) Add optional extra in `pyproject.toml`
   - [ ] Define `[project.optional-dependencies].mcp` with MCP client/server libs.
   - [ ] Document install: `pip install penguin-ai[mcp]`.

2) Server: expose allow‑listed tools (stdio)
   - [ ] New module: `penguin/integrations/mcp/server.py`.
   - [ ] Adapter over `ToolManager.tools` to list tools and call by name.
   - [ ] Allowlist from config: expose only safe, read‑only tools (e.g., `grep_search`, `list_files`, `read_file` with guards, `memory_search`).
   - [ ] Per‑tool timeouts + minimal rate‑limit; structured errors.

3) Client: bridge remote MCP tools into ToolManager
   - [ ] New module: `penguin/integrations/mcp/client.py`.
   - [ ] Mirror remote tools as virtual Penguin tools with names `mcp::<server>::<tool>`.
   - [ ] Lazy connect on first invocation; cache schemas; map errors.

4) Config wiring (`config.yml`)
   - [ ] `mcp.enabled: bool`.
   - [ ] `mcp.server: { transport: stdio|sse, port?: int, allow_tools: [..], auth?: { token: "..." } }`.
   - [ ] `mcp.servers: [{ name, transport, url|command, auth?, allow_tools? }]`.

5) CLI commands
   - [ ] `penguin mcp serve [--stdio|--sse :port] [--allow TOOL1,TOOL2]`.
   - [ ] `penguin mcp add-server <name> --url/--command ...`.
   - [ ] `penguin mcp list-servers` / `list-tools [--server <name>]`.
   - [ ] `penguin mcp call <server>.<tool> --json '{...}'`.

6) Tests
   - [ ] Unit: server tool listing, allowlist enforcement, input schema validation.
   - [ ] Unit: client tool registration, lazy connect, call path, error mapping.
   - [ ] Integration: start local server, call `grep_search` via client bridge.
   - [ ] Negative cases: forbidden tool, malformed params, timeouts.

7) Penguin MCP Panel (optional, no Agent Browser)
   - [ ] Web endpoints under `penguin/web` to list MCP servers and tools.
   - [ ] Call tools with JSON params; stream outputs to browser (SSE/WebSocket).
   - [ ] Minimal UI: server picker, tool list, schema viewer, parameter form, results pane.
   - [ ] Auth for panel routes (reuse existing web auth middleware if present).

8) Link‑based MCP client transport (optional)
   - [ ] Implement a Link transport adapter if Link is available in Penguin.
   - [ ] Fallback to stdio when Link is not configured.

### Security Defaults
- Deny by default; explicit allowlist only.
- Read‑only tools by default; writes require explicit opt‑in and warnings.
- Token for non‑stdio transports; optional OAuth2 when going remote.

### Compatibility
- No reliance on Agent Browser; interact directly with configured MCP servers.
- Support stdio first; optionally SSE for web contexts; Panel is a thin client.

### Acceptance Criteria (MVP)
- Installing `[mcp]` enables `penguin mcp serve` and client bridge without impacting base startup times.
- `grep_search` callable from a remote MCP client against Penguin server.
- A remote MCP server’s tool shows up in `ToolManager` as `mcp::<server>::<tool>` and can be invoked with parameters, returning structured output.
- Unit + integration tests pass in CI.

### Post‑MVP
- OAuth2 flows for remote servers; tool attestation/verification.
- Telemetry and tracing of MCP calls; rate limiting per tool.
- Prompt/Resource surfaces (MCP prompts/resources) as needed.

### Cleanup
- Consolidate/remove prior stubs: `penguin/integrations/mcp/adapter.py`, `misc/MCP/*`, and the echo demo after real server is in place.


