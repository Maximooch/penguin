# Penguin Permission Engine TODO

This document tracks the design, implementation, and rollout of Penguin's permission/policy engine. The goal is a minimal yet effective security layer that enforces boundaries without impeding developer velocity.

## Current State

- **Data structures exist**: `ToolDefinition.permissions`, `ActionDefinition.permissions`, `PluginMetadata.permissions` fields declared but unenforced
- **MCP adapter has basic filtering**: `MCPServer._is_allowed()` uses allow/deny glob patterns, hardcoded write-tool heuristic
- **Prompts reference non-existent behavior**: System prompts mention "permission engine" 12+ times with no backing implementation
- **Sub-agents record but don't enforce**: Per-agent persona/model/default_tools stored, never checked at runtime

---

## Technical Considerations

### Enforcement Points

Where should permission checks happen? Multiple layers possible:

| Layer | Pros | Cons |
|-------|------|------|
| **ToolManager.execute()** | Catches all tool calls | Tight coupling, harder to swap engines |
| **ActionExecutor** | Central dispatch | Some tools bypass this path |
| **Individual tool handlers** | Fine-grained | Repetitive, easy to forget |
| **Middleware/decorator** | Clean separation | Adds indirection |

**Recommendation**: Decorator-based middleware wrapping `ToolManager.execute()` and `ActionExecutor.execute_action()`. Single enforcement point with plugin-able policy engine.

### Path Normalization

File operations need consistent path handling:
- Resolve symlinks (or deny them?)
- Handle `..` traversal attempts
- Workspace-relative vs absolute paths
- Case sensitivity (macOS HFS+ is case-insensitive)

**Edge cases**:
- `/workspace/../etc/passwd` - traversal through allowed prefix
- Symlinks inside workspace pointing outside
- Hardlinks (rare but possible attack vector)

### Operation Taxonomy

What operations need permission checks?

```
filesystem.read      - Read file contents
filesystem.write     - Create/overwrite files  
filesystem.delete    - Remove files
filesystem.mkdir     - Create directories
filesystem.list      - List directory contents (usually safe)

process.execute      - Run shell commands
process.spawn        - Long-running background processes
process.kill         - Terminate processes

network.fetch        - HTTP GET (usually safe)
network.post         - HTTP POST/PUT (data exfil risk)
network.listen       - Open server ports

git.read             - Status, log, diff (safe)
git.write            - Commit, branch, stash
git.push             - Push to remote (irreversible)
git.force            - Force push, reset (destructive)

memory.read          - Query stored notes
memory.write         - Add/update notes
memory.delete        - Remove notes
```

### Approval Flow

When `PermissionResult.ASK` is returned, how does approval work?

**Supported modes**:
1. **Synchronous blocking**: Tool pauses, UI prompts user, resumes on approval (CLI/TUI)
2. **Queue-based**: Request queued, agent continues with other work, approval triggers retry (Web API/Link)
3. **Session-level allowlist**: "Allow all file writes this session"
4. **Pattern-based allowlist**: "Allow writes to `*.py` files"

**Web API Approval Flow** (critical for Link and external clients):
```
Agent requests write to /src/main.py
    ↓
PermissionEngine returns ASK
    ↓
ApprovalRequest created, stored in pending queue
    ↓
WebSocket event broadcast: {"event": "approval_required", "data": {...}}
    ↓
Link UI shows approval modal
    ↓
User clicks Approve/Deny
    ↓
POST /api/v1/approvals/{id}/approve or /deny
    ↓
Agent resumes or receives denial
```

**Required API endpoints**:
- `GET /api/v1/approvals` — List pending approval requests
- `GET /api/v1/approvals/{id}` — Get specific approval details
- `POST /api/v1/approvals/{id}/approve` — Approve with optional scope (once, session, pattern)
- `POST /api/v1/approvals/{id}/deny` — Deny with optional reason
- WebSocket event: `approval_required` via `/api/v1/events/ws`

### Container vs Local Modes

Different trust models:
- **Container/sandbox**: Full permissions assumed (isolated environment)
- **Local development**: Restricted to workspace, ask for system operations
- **Production/CI**: Read-only by default, explicit allowlists

Detection heuristic: Check for `/.dockerenv`, `KUBERNETES_SERVICE_HOST`, or explicit config override.

### Multi-Agent Implications

Sub-agents inherit parent permissions or get restricted subset?

**Options**:
1. **Inherit**: Sub-agent has same permissions as parent
2. **Restrict**: Sub-agent can only have ≤ parent permissions
3. **Explicit**: Each sub-agent spawn declares its permission scope
4. **Role-based**: "analyzer" role = read-only, "implementer" = read-write

---

## Questions and Suggestions

### Resolved Questions ✅

1. **Granularity**: ✅ **Permission nodes (per-operation)** — Tools like `apply_diff` decompose into `filesystem.read` + `filesystem.write` checks
2. **Persistence**: ✅ **Yes** — Store in config file and expose via Web API for runtime management
3. **Audit logging**: ✅ **All checks** — Log every permission check, not just denials (useful for debugging and security audits)
4. **Escape hatch**: ✅ **Yes** — `--yolo` flag disables all checks (for CI, containers, power users)
5. **Dynamic policies**: ✅ **Yes** — Via [Runtime Configuration Management](https://penguin-rho.vercel.app/docs/api_reference/api_server) (`PATCH /api/v1/runtime/config`)
6. **Delegation**: ✅ **No** — Sub-agents cannot exceed parent permissions (strict inheritance)

### Design Suggestions

**1. Start with deny-by-default, allowlist up**
- Safer to add permissions than remove them
- Explicit allowlists force conscious security decisions

**2. Use capability tokens, not role strings**
- Instead of `role="admin"`, use `capabilities=["filesystem.write", "process.execute"]`
- More composable, easier to reason about

**3. Separate policy from enforcement**
- `PolicyEngine`: Decides ALLOW/ASK/DENY based on rules
- `PermissionEnforcer`: Wraps execution points, calls engine, handles ASK flow
- Allows swapping policy engines (simple rules → complex RBAC) without touching enforcement

**4. Make denials informative**
- Bad: "Permission denied"
- Good: "Cannot write to /etc/hosts: outside workspace boundary. Run with --allow-system-paths or add to config."

**5. Consider "dry-run" mode**
- Agent plans actions, permission engine logs what it would do, no actual execution
- Useful for reviewing agent behavior before granting permissions

---

## Planning: Implementation Phases

### Phase 1: Core Engine (Foundation) ✅ COMPLETE
**Goal**: Functional permission checking with workspace boundary enforcement

- [x] Create `penguin/security/` module structure
- [x] Implement `PermissionMode` enum: `READ_ONLY`, `WORKSPACE`, `FULL`
- [x] Implement `PermissionResult` enum: `ALLOW`, `ASK`, `DENY`
- [x] Implement `PolicyEngine` base class with `check_operation(op, resource) -> PermissionResult`
- [x] Implement `WorkspaceBoundaryPolicy`: Allow operations within workspace, deny outside
- [x] Add path normalization utilities (resolve symlinks, detect traversal)
- [x] Wire into `ToolManager.execute()` as enforcement point
- [x] Unit tests for boundary checking, traversal prevention (38 tests passing)

**Deliverables**: 
- `penguin/security/__init__.py` - Module exports
- `penguin/security/permission_engine.py` - Core classes (PermissionMode, PermissionResult, Operation, PolicyEngine, PermissionEnforcer)
- `penguin/security/policies/workspace.py` - WorkspaceBoundaryPolicy
- `penguin/security/path_utils.py` - Path normalization and security utilities
- `penguin/security/tool_permissions.py` - Tool-to-operation mapping
- `tests/test_permission_engine.py` - 38 unit tests

**Time actual**: ~3 hours

### Phase 2: Configuration & Prompt Integration ✅ COMPLETE
**Goal**: User-configurable policies, prompt clarity

- [x] Add `security` section to config.yml schema with mode, allowed_paths, denied_paths, require_approval
- [x] Implement config-driven policy loading with additive merge for security lists
- [x] Add `SecurityConfig` dataclass to Config class
- [x] Add security settings to `RuntimeConfig` (security_mode, security_enabled, set methods)
- [x] Create `get_permission_section()` for prompt injection (`security/prompt_integration.py`)
- [x] Update `PromptBuilder` to include permission context in all prompt modes
- [x] Add API endpoints:
  - `GET /api/v1/security/config` - Get current security settings
  - `PATCH /api/v1/security/config` - Update mode/enabled at runtime
  - `POST /api/v1/security/yolo` - Quick YOLO mode toggle

**Deliverables**:
- `config.yml` security section
- `SecurityConfig` dataclass in `config.py`
- RuntimeConfig security methods
- `security/prompt_integration.py` - Prompt section generator
- `prompt/builder.py` - Updated with permission context
- `api/routes.py` - Security config endpoints

**Time actual**: ~2 hours

### Phase 3: Approval Flow (Web/API) ✅ COMPLETE
**Goal**: Interactive approval for ASK results via Web API and Python API

- [x] Define `ApprovalRequest` dataclass with unique IDs, status, expiration
- [x] Implement `ApprovalManager` singleton for pending/resolved requests
- [x] Implement `ApprovalScope` (ONCE, SESSION, PATTERN) and `ApprovalStatus` (PENDING, APPROVED, DENIED, EXPIRED)
- [x] Implement session-level approval caching (`SessionApproval`)
- [x] Implement pattern-based pre-approval (glob patterns)
- [x] Implement Web API approval endpoints:
  - `GET /api/v1/approvals` — List pending requests
  - `GET /api/v1/approvals/{id}` — Get request details
  - `POST /api/v1/approvals/{id}/approve` — Approve (with scope: once/session/pattern)
  - `POST /api/v1/approvals/{id}/deny` — Deny request
  - `POST /api/v1/approvals/pre-approve` — Pre-approve operations
  - `GET /api/v1/approvals/session/{id}` — Get session approvals
  - `DELETE /api/v1/approvals/session/{id}` — Clear session approvals
- [x] Add `ApprovalWebSocketManager` for real-time notifications
- [x] Add WebSocket events: `approval_required`, `approval_resolved`
- [x] Integrate with `ToolManager.execute_tool()`:
  - Check pre-approvals before creating request
  - Return `{"status": "pending_approval", "approval_id": "..."}` for ASK results
- [x] Add auto-expiration with configurable TTL (default 5 min)
- [ ] CLI approval flow (deferred - Phase 3b)
- [ ] TUI approval flow (deferred - Phase 3b)

**Deliverables**:
- `security/approval.py` - ApprovalManager, ApprovalRequest, SessionApproval
- `api/routes.py` - REST endpoints + WebSocket integration
- `tools/tool_manager.py` - Approval flow integration

**Time actual**: ~2 hours

### Phase 4: Multi-Agent & Sub-Agent Policies
**Goal**: Permission scoping for sub-agents

- [ ] Add `permissions` field to sub-agent spawn parameters
- [ ] Implement permission inheritance rules (child ≤ parent)
- [ ] Wire permission checks into `MultiAgentCoordinator`
- [ ] Add per-agent permission override in config:
  ```yaml
  agents:
    analyzer:
      permissions: [filesystem.read, memory.read]
    implementer:
      permissions: [filesystem.read, filesystem.write, process.execute]
  ```

**Deliverables**: Sub-agent permission scoping, coordinator integration
**Time estimate**: 2-3 hours

### Phase 5: Audit & Observability
**Goal**: Visibility into permission decisions

- [ ] Add permission check logging (configurable verbosity)
- [ ] Track denial reasons for debugging
- [ ] Expose permission metrics via telemetry collector
- [ ] Add `/permissions` slash command to show current policy state
- [ ] Add `penguin permissions list` CLI command

**Deliverables**: Audit logging, CLI/TUI introspection commands
**Time estimate**: 1-2 hours

### Phase 6: Advanced Policies (Future)
**Goal**: Sophisticated policy rules beyond simple allowlists

- [ ] Pattern-based rules: "Allow write to `*.py`, deny write to `*.env`"
- [ ] Time-based rules: "Allow during business hours only"
- [ ] Rate limiting: "Max 10 file writes per minute"
- [ ] RBAC integration: Map external identity to capability sets
- [ ] Policy-as-code: Load policies from `.penguin/policies/*.yml`

**Deliverables**: Advanced policy types, policy file loading
**Time estimate**: 4-6 hours (optional, lower priority)

---

## Success Criteria

1. **No silent bypasses**: Every tool execution passes through permission check
2. **Clear feedback**: Denials explain why and how to fix
3. **Minimal friction**: Default policies don't block normal workflows
4. **Configurable**: Power users can tune policies to their security posture
5. **Prompt alignment**: System prompts accurately reflect enforced policies
6. **Testable**: Permission logic has comprehensive unit tests

---

## Dependencies

- **Config system**: Needs `security` section in config schema
- **ToolManager**: Enforcement point integration
- **System prompt builder**: Permission context injection
- **CLI/TUI**: Approval flow UI
- **Web API routes** (`penguin/api/routes.py`): Approval endpoints, runtime config integration
- **WebSocket events**: `approval_required` event type
- **Telemetry**: Audit logging integration
- **Runtime Configuration Management**: Dynamic policy updates via `PATCH /api/v1/runtime/config`

---

## Decisions Made ✅

### Implementation Order
Confirmed: Chronological (1→2→3→5→4→6)
1. **Phase 1** (Core Engine) — Foundation ← **IN PROGRESS**
2. **Phase 2** (Config & Prompts) — Makes it usable immediately
3. **Phase 3** (Approval Flow) — Required for interactive use, especially Link
4. **Phase 5** (Audit) — Observability helps debug issues
5. **Phase 4** (Multi-Agent) — Can defer until sub-agents are more widely used
6. **Phase 6** (Advanced) — Future enhancement

### Default Mode
✅ **`WORKSPACE` mode** as default, UNLESS user explicitly sets `project_root` via:
- `RuntimeConfig.set_project_root()` 
- `PENGUIN_PROJECT_ROOT` env var
- Config file `execution_mode: project`

This aligns with existing `RuntimeConfig` in `config.py` which already tracks:
- `_project_root`, `_workspace_root`, `_execution_mode`
- Observer pattern for notifying components

### First Test Cases
1. `enhanced_write` / `write_to_file` — Clear write operation
2. `execute_command` — High-risk, good test of `process.execute`
3. `apply_diff` — Tests combined read+write permission nodes
4. `git_push` — Tests `require_approval` flow

### MCP Integration
✅ **Layer** approach (defense in depth), then migrate:
- Keep existing `MCPServer._is_allowed()` glob patterns
- Add PermissionEngine as additional layer
- Eventually migrate MCP patterns to unified config

---

## Related Documents

- `prompting_action_plan.md`: Code snippets for initial implementation
- `codex_comparison_summary.md`: Codex safety model comparison
- `penguin_cli_refactor_plan.md`: CLI `/permissions` command plans
- `cli-feature-list.md`: Gemini CLI policy engine reference
- `penguin_todo_multi_agents.md`: Sub-agent permission notes

