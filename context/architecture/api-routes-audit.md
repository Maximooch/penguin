# API Routes Audit: Migration from api/routes.py to web/routes.py

**Date:** 2024-12-19
**Status:** Pending Migration
**Goal:** Consolidate all API functionality into `penguin/web/routes.py` and remove the legacy `penguin/api/routes.py`

---

## Summary

`penguin/api/routes.py` contains security/approval functionality that was never migrated to `penguin/web/routes.py`. The web routes file is the actively used one, but it's missing critical permission management endpoints.

---

## Functionality to Migrate

### 1. Approval Flow Endpoints (Priority: HIGH)

These are **critical** if the permission system is enabled - without them, there's no way to approve/deny tool executions via the API.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/approvals` | GET | List pending approval requests |
| `/api/v1/approvals/pre-approve` | POST | Pre-approve operations (for automation/CI) |
| `/api/v1/approvals/session/{session_id}` | GET | Get session-specific approvals |
| `/api/v1/approvals/session/{session_id}` | DELETE | Clear session approvals |
| `/api/v1/approvals/{request_id}` | GET | Get specific approval request |
| `/api/v1/approvals/{request_id}/approve` | POST | Approve a pending request |
| `/api/v1/approvals/{request_id}/deny` | POST | Deny a pending request |

**Dependencies:**
- `ApprovalWebSocketManager` class (lines 25-130 in api/routes.py)
- `_setup_approval_websocket_callbacks()` function
- `ApprovalAction` and `PreApprovalRequest` Pydantic models
- Import: `from penguin.security.approval import get_approval_manager, ApprovalScope`

**Source location:** `penguin/api/routes.py` lines 1478-1778

### 2. Security Configuration Endpoints (Priority: HIGH)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/security/config` | GET | Get current security/permission config |
| `/api/v1/security/config` | PATCH | Update security config at runtime |
| `/api/v1/security/yolo` | POST | Quick toggle for YOLO mode |
| `/api/v1/security/audit` | GET | Get permission audit log entries |
| `/api/v1/security/audit/stats` | GET | Get audit statistics |

**Dependencies:**
- `SecurityConfigUpdate` Pydantic model
- `_get_default_capabilities()` helper function
- Import: `from penguin.security.audit import get_audit_logger`

**Source location:** `penguin/api/routes.py` lines 1194-1476

### 3. Supporting Infrastructure

| Component | Description |
|-----------|-------------|
| `ApprovalWebSocketManager` | Manages WebSocket connections for real-time approval notifications |
| `_ws_manager` | Singleton instance |
| `_approval_callbacks_registered` | Flag to track callback registration |
| `_setup_approval_websocket_callbacks()` | Registers ApprovalManager callbacks |
| `_get_approval_manager()` | Lazy-loaded approval manager getter |

---

## Functionality Already Duplicated (No Action Needed)

These endpoints exist in both files with similar implementations:

- `/api/v1/chat/message` - POST
- `/api/v1/chat/stream` - WebSocket
- `/api/v1/projects/create` - POST
- `/api/v1/tasks/execute` - POST
- `/api/v1/tasks/execute-sync` - POST
- `/api/v1/tasks/stream` - WebSocket
- `/api/v1/token-usage` - GET
- `/api/v1/conversations` - GET
- `/api/v1/conversations/{id}` - GET
- `/api/v1/conversations/create` - POST
- `/api/v1/context-files` - GET
- `/api/v1/context-files/load` - POST
- `/api/v1/upload` - POST
- `/api/v1/capabilities` - GET
- `/api/v1/checkpoints/*` - All checkpoint endpoints
- `/api/v1/models` - GET
- `/api/v1/models/load` - POST
- `/api/v1/models/current` - GET
- `/api/v1/system/info` - GET
- `/api/v1/system/status` - GET

---

## Functionality Unique to web/routes.py (Keep As-Is)

These are newer features that were correctly added only to web/routes.py:

- Agent CRUD: `/api/v1/agents/*`
- Multi-agent messaging: `/api/v1/messages/*`
- Coordination: `/api/v1/coord/*`
- Workflows: `/api/v1/workflows/*`
- Orchestration: `/api/v1/orchestration/*`
- Memory: `/api/v1/memory/*`
- System config: `/api/v1/system/config/*`
- Telemetry: `/api/v1/telemetry`, `/api/v1/ws/telemetry`
- Events WebSocket: `/api/v1/events/ws`

---

## Migration Plan

### Phase 1: Add Missing Endpoints to web/routes.py

1. **Add Pydantic models** at top of web/routes.py:
   - `SecurityConfigUpdate`
   - `ApprovalAction`
   - `PreApprovalRequest`

2. **Add ApprovalWebSocketManager class** and supporting infrastructure:
   - Class definition
   - `_ws_manager` singleton
   - `_approval_callbacks_registered` flag
   - `_setup_approval_websocket_callbacks()` function
   - `_get_approval_manager()` helper

3. **Add helper function:**
   - `_get_default_capabilities(mode, enabled)`

4. **Add security config endpoints:**
   - GET/PATCH `/api/v1/security/config`
   - POST `/api/v1/security/yolo`
   - GET `/api/v1/security/audit`
   - GET `/api/v1/security/audit/stats`

5. **Add approval flow endpoints:**
   - GET `/api/v1/approvals`
   - POST `/api/v1/approvals/pre-approve`
   - GET/DELETE `/api/v1/approvals/session/{session_id}`
   - GET `/api/v1/approvals/{request_id}`
   - POST `/api/v1/approvals/{request_id}/approve`
   - POST `/api/v1/approvals/{request_id}/deny`

6. **Update existing WebSocket handlers** to integrate with ApprovalWebSocketManager if needed

### Phase 2: Verify and Test

1. Ensure all security/approval endpoints work correctly in web/routes.py
2. Test WebSocket approval notifications
3. Verify no regressions in existing functionality

### Phase 3: Remove api/routes.py

1. Remove `penguin/api/routes.py`
2. Remove `penguin/api/__init__.py` if it only exports routes
3. Update any imports that reference `penguin.api.routes`
4. Remove api router registration from app setup (check `penguin/web/app.py` or similar)

---

## Files Affected

| File | Action |
|------|--------|
| `penguin/web/routes.py` | Add security/approval endpoints |
| `penguin/api/routes.py` | Delete after migration |
| `penguin/api/__init__.py` | Delete or update |
| `penguin/web/app.py` | Remove api router if registered |
| Any tests for api/routes | Update to use web/routes |

---

## Risks and Considerations

1. **WebSocket State:** The `ApprovalWebSocketManager` manages connection state. Ensure it integrates correctly with existing WebSocket handling in web/routes.py.

2. **Lazy Imports:** The approval manager uses lazy imports to avoid circular dependencies. Preserve this pattern.

3. **Route Order:** FastAPI route order matters - specific paths must come before path parameters. When adding approval routes, ensure `/approvals/pre-approve` and `/approvals/session/{id}` come before `/approvals/{request_id}`.

4. **Backwards Compatibility:** If any external systems depend on the api/routes.py endpoints, they should continue to work since we're just moving them, not changing them.

---

## Line Counts

- `penguin/api/routes.py`: ~1,778 lines (will be deleted)
- `penguin/web/routes.py`: ~2,900+ lines (will add ~600 lines)

After migration, web/routes.py will be ~3,500 lines. Consider future refactoring to split into sub-modules if needed.
