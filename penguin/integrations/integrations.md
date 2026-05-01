# Penguin Integrations

## Purpose

`penguin/integrations/` is for boundary adapters between Penguin and external protocols, products, platforms, and ecosystems.

An integration belongs here when this sentence is true:

> If the external system or protocol disappeared, this module would mostly disappear too.

This directory should not become a junk drawer for core runtime logic. Integrations adapt external systems into Penguin; they should not own Penguin's internal semantics.

## Design Principles

1. Keep core abstractions in core packages.
   - Tool execution belongs in `penguin/tools/`.
   - Conversation/session state belongs in `penguin/system/` or runtime services.
   - Model-provider behavior belongs in `penguin/llm/`.
   - Project/task state belongs in `penguin/project/`.

2. Keep protocol/product glue in `penguin/integrations/`.
   - Transport setup.
   - Auth handshakes.
   - External API request/response mapping.
   - Protocol-specific schema conversion.
   - External event/webhook parsing.
   - Diagnostics for that external surface.

3. Dependency direction should point inward only through stable facades.
   - Good: `ToolManager -> tools provider -> integrations.mcp -> MCP SDK`.
   - Bad: `integrations.mcp -> random PenguinCore internals -> ToolManager private state`.

4. Prefer manager/provider boundaries.
   - Integration manager: owns external lifecycle, clients, sessions, retries, auth state.
   - Penguin provider/facade: adapts the integration into tools, resources, events, or UI commands.

5. Make failure visible.
   - Configured integrations should expose status, last error, and diagnostics.
   - Silent optional imports are acceptable only when a feature is completely unconfigured.

6. Treat permissions as a Penguin concern.
   - Integrations may contribute metadata such as external identity, risk hints, scopes, and resource names.
   - Final permission decisions should flow through Penguin's permission/tool/runtime systems.

## Recommended Shape

```text
penguin/integrations/<name>/
  __init__.py
  config.py          # typed integration config
  manager.py         # external lifecycle/client/session owner
  client.py          # low-level API/protocol client if useful
  schema.py          # schema conversion, if applicable
  auth.py            # auth/OAuth/token handling, if applicable
  diagnostics.py     # status snapshots and human-readable errors
  errors.py          # explicit integration exceptions
  webhooks.py        # inbound event parsing, if applicable
```

Optional companion code should live near the Penguin subsystem it adapts into:

```text
penguin/tools/providers/<name>.py     # external tools as Penguin tools
penguin/web/routes/<name>.py          # web/API control/status surface
penguin/cli/<name>.py                 # CLI commands, if substantial
penguin/tui/...                       # TUI surface, if needed
```

## What Belongs Here

### Protocol Integrations

- **MCP**: Model Context Protocol host/client/server support.
  - `integrations/mcp/` owns SDK sessions, transports, protocol schemas, server status, and MCP-specific diagnostics.
  - Tool exposure should still route through `penguin/tools/` provider/facade code.

- **LSP**: Language Server Protocol integration.
  - Use for diagnostics, symbol search, definition/reference lookup, semantic workspace context, code actions, rename support.
  - Keep editor-specific UI outside the protocol adapter.

- **DAP**: Debug Adapter Protocol integration.
  - Use for breakpoints, stack frames, variables, stepping, test/debug sessions.
  - Treat execution/debug permissions as first-class; debugger attach is not a harmless read-only action.

- **A2A / Agent Protocols**: Inter-agent communication with external agents or agent runtimes.
  - Use for task delegation, capability discovery, status sync, result exchange.
  - Must preserve Penguin's task lifecycle truth instead of flattening everything into generic chat messages.

- **Webhooks**: Generic inbound event integration.
  - Use for GitHub/GitLab events, CI events, deployment events, issue tracker updates, incident alerts.
  - Should normalize payloads into typed Penguin events before touching project/task state.

### Developer Platform Integrations

- **GitHub**: issues, PRs, code review comments, checks, Actions status, repository metadata.
- **GitLab**: merge requests, issues, pipelines, repository metadata.
- **Sentry**: errors, traces, releases, issue triage, suspect commits, regression context.
- **Linear/Jira**: issues, planning metadata, workflow state, requirements sync.
- **Notion**: docs, specs, lightweight PM databases, knowledge base sync.

### Communication And Collaboration

- **Slack/Discord**: notifications, command entrypoints, human approval flows, incident rooms.
- **Email/Calendar**: summaries, scheduling, release coordination, approval reminders.

### Editor And IDE Integrations

- **VS Code**: editor bridge, selected text/context, terminal/session attachment, diagnostics, inline actions.
- **JetBrains / editor of choice**: same conceptual bridge with different transport/plugin implementation.
- **Generic editor bridge**: a protocol-neutral layer for active file, selection, cursor, open buffers, diagnostics, and commands.

Editor integration should distinguish:

```text
integrations/lsp/          # protocol-level language intelligence
integrations/dap/          # protocol-level debugger intelligence
integrations/editor_bridge/ # active-editor context and commands
```

Do not collapse those into one blob. LSP, DAP, and editor UI context are related but not the same beast.

### Link Integration

**Link** is expected to be deeper than a normal external integration.

Working description:

- OSS chat + project management + agent orchestration platform.
- Intended to have deep Penguin integration.
- Already has some support in `penguin/llm`, so the eventual boundary may cross `llm`, runtime events, project/task orchestration, and web surfaces.

Likely responsibilities:

- Chat/session sync.
- Project/task sync.
- Agent orchestration and delegation.
- Human approval/clarification workflows.
- Shared artifacts and references.
- Runtime event streaming.
- Possibly model/provider routing if Link acts as a gateway.

Because Link may become a first-class Penguin surface, avoid forcing it into the same box as small API integrations. Start with `penguin/integrations/link/` for external protocol/client/auth glue, but expect companion code in:

```text
penguin/llm/               # existing/deeper model or gateway support
penguin/project/           # task/project synchronization
penguin/web/routes/        # Link API/event surfaces
penguin/system/            # session/event bridging if needed
penguin/multi/             # agent orchestration if needed
```

The rule still holds: `integrations/link/` should own Link boundary behavior, not all Penguin behavior related to Link.

### Import/Export Bridges

- Claude Desktop MCP config import.
- Cursor/Windsurf/OpenCode config import.
- Chat transcript import/export.
- Project/task export.
- Docs or knowledge-base import.

### Secrets And Enterprise Connectors

- 1Password.
- HashiCorp Vault.
- AWS/GCP/Azure secret managers.
- SSO/OIDC/SAML helpers.

These should provide credentials through typed interfaces. They should not scatter secret lookup code across integrations.

## What Does Not Belong Here

- Native Penguin tool implementations.
- Permission decision engines.
- Conversation persistence.
- Context window management.
- Prompt construction.
- Core project/task database logic.
- Model-provider adapters that are already first-class `penguin/llm` concerns.
- Business logic that only happens to call an external API.

If an integration starts deciding what Penguin means internally, it is in the wrong layer.

## Integration Maturity Levels

### Level 0: Config Stub

- Typed config only.
- No runtime behavior.
- Useful for documenting intended shape.

### Level 1: Client/Manager

- Can authenticate/connect.
- Can fetch status.
- Has explicit diagnostics and errors.

### Level 2: Penguin Surface

- Exposes tools, resources, project events, or UI commands through stable Penguin facades.
- Permission path is enforced.
- Tests cover success and failure.

### Level 3: Productized Integration

- CLI/web/TUI status and controls.
- Docs and example configs.
- Retry/backoff/reconnect where appropriate.
- Observability.
- Compatibility tests or recorded fixtures.

## Candidate Integration Backlog

High leverage, near-term:

1. MCP host/client support.
2. GitHub/GitLab issue + PR context.
3. Sentry issue/error context.
4. VS Code/editor bridge for active file, selection, diagnostics, and commands.
5. LSP symbol/diagnostics integration.

Medium-term:

1. DAP debugging workflows.
2. Webhook event ingestion.
3. Notion/docs synchronization.
4. Linear/Jira planning synchronization.
5. Slack/Discord notifications and approval flows.

Strategic/deeper:

1. Link platform integration.
2. A2A / external agent runtime interoperability.
3. Enterprise secrets/SSO connectors.
4. Cross-agent/project orchestration bridges.

## Architectural Smell Tests

Ask these before adding code under `penguin/integrations/`:

1. Is this mostly about an external system/protocol?
2. Can it expose a small manager/client boundary?
3. Does it avoid importing private core internals?
4. Are permissions enforced outside the integration?
5. Does it expose status and last-error diagnostics?
6. Would the code mostly disappear if the external system disappeared?

If the answer is no, do not put it here.
