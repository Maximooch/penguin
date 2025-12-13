# Penguin API Updates - Core/Engine Integration

This document outlines the major API updates needed to bring the API layer up to date with the recent changes to `core.py`, `engine.py`, and system components.

## Summary of Changes

The API has been significantly enhanced with the following new capabilities:

### 1. **Checkpoint Management API** ✅ IMPLEMENTED
Full CRUD operations for conversation checkpoints with branching support.

### 2. **Model Management API** ✅ IMPLEMENTED  
Runtime model switching and model discovery endpoints.

### 3. **Enhanced Task Execution** ✅ IMPLEMENTED
Synchronous task execution using the Engine layer with comprehensive result tracking.

### 4. **System Diagnostics** ✅ IMPLEMENTED
System information and real-time status monitoring endpoints.

---

## New API Endpoints

### Checkpoint Management

#### `POST /api/v1/checkpoints/create`
Create a manual checkpoint of the current conversation state.

**Request Body:**
```json
{
    "name": "My Important Checkpoint",
    "description": "Before attempting the complex refactoring"
}
```

**Response:**
```json
{
    "checkpoint_id": "cp_20250528_161852_67269a65",
    "status": "created",
    "name": "My Important Checkpoint",
    "description": "Before attempting the complex refactoring"
}
```

#### `GET /api/v1/checkpoints`
List available checkpoints with optional filtering.

**Query Parameters:**
- `session_id` (optional): Filter by specific session
- `limit` (optional, default=50): Maximum number of results

**Response:**
```json
{
    "checkpoints": [
        {
            "id": "cp_20250528_161852_67269a65",
            "type": "manual",
            "created_at": "2025-05-28T16:18:52.123456",
            "session_id": "session_20250528_161800_abc123",
            "message_count": 5,
            "name": "My Important Checkpoint",
            "description": "Before attempting the complex refactoring",
            "auto": false
        }
    ]
}
```

#### `POST /api/v1/checkpoints/{checkpoint_id}/rollback`
Rollback conversation to a specific checkpoint.

**Response:**
```json
{
    "status": "success",
    "checkpoint_id": "cp_20250528_161852_67269a65",
    "message": "Successfully rolled back to checkpoint cp_20250528_161852_67269a65"
}
```

#### `POST /api/v1/checkpoints/{checkpoint_id}/branch`
Create a new conversation branch from a checkpoint.

**Request Body:**
```json
{
    "name": "Alternative Implementation",
    "description": "Exploring a different approach"
}
```

**Response:**
```json
{
    "branch_id": "cp_20250528_162000_89abcdef",
    "source_checkpoint_id": "cp_20250528_161852_67269a65", 
    "status": "created",
    "name": "Alternative Implementation",
    "description": "Exploring a different approach"
}
```

#### `GET /api/v1/checkpoints/stats`
Get statistics about the checkpointing system.

**Response:**
```json
{
    "enabled": true,
    "total_checkpoints": 25,
    "auto_checkpoints": 20,
    "manual_checkpoints": 3,
    "branch_checkpoints": 2,
    "config": {
        "frequency": 1,
        "retention_hours": 24,
        "max_age_days": 30
    }
}
```

#### `POST /api/v1/checkpoints/cleanup`
Clean up old checkpoints according to retention policy.

**Response:**
```json
{
    "status": "completed",
    "cleaned_count": 5,
    "message": "Cleaned up 5 old checkpoints"
}
```

---

### Model Management

#### `GET /api/v1/models`
List all available models from configuration and providers.

**Response:**
```json
{
    "models": [
        {
            "id": "anthropic/claude-3-5-sonnet-20240620",
            "name": "Claude 3.5 Sonnet",
            "provider": "anthropic",
            "client_preference": "openrouter",
            "vision_enabled": true,
            "max_context_window_tokens": 64000,
            "temperature": 0.7,
            "current": true
        },
        {
            "id": "openai/gpt-4o",
            "name": "GPT-4o",
            "provider": "openai", 
            "client_preference": "openrouter",
            "vision_enabled": true,
            "max_context_window_tokens": 16384,
            "temperature": 0.7,
            "current": false
        }
    ]
}
```

#### `POST /api/v1/models/load`
Switch to a different model at runtime.

**Request Body:**
```json
{
    "model_id": "google/gemini-2.5-pro-preview"
}
```

**Response:**
```json
{
    "status": "success",
    "model_id": "google/gemini-2.5-pro-preview",
    "current_model": "google/gemini-2.5-pro-preview",
    "message": "Successfully loaded model: google/gemini-2.5-pro-preview"
}
```

#### `GET /api/v1/models/current`
Get information about the currently loaded model.

**Response:**
```json
{
    "model": "anthropic/claude-3-5-sonnet-20240620",
    "provider": "anthropic",
    "client_preference": "openrouter",
    "max_context_window_tokens": 64000,
    "temperature": 0.7,
    "streaming_enabled": true,
    "vision_enabled": true
}
```

---

### Enhanced Task Execution

#### `POST /api/v1/tasks/execute-sync`
Execute a task synchronously using the Engine layer with comprehensive tracking.

**Request Body:**
```json
{
    "name": "Refactor Authentication System",
    "description": "Update the authentication system to use JWT tokens and add OAuth support",
    "continuous": false,
    "time_limit": 30
}
```

**Response:**
```json
{
    "status": "completed",
    "response": "I have successfully refactored the authentication system...",
    "iterations": 3,
    "execution_time": 45.2,
    "action_results": [
        {
            "action_name": "code_execution",
            "output": "Tests passed successfully",
            "status": "completed"
        }
    ],
    "task_metadata": {
        "id": "task_20250528_162030",
        "name": "Refactor Authentication System", 
        "context": {
            "continuous": false,
            "time_limit": 30
        },
        "max_iterations": 10,
        "start_time": "2025-05-28T16:20:30.000000"
    }
}
```

---

### System Information & Diagnostics

#### `GET /api/v1/system/info`
Get comprehensive system information.

**Response:**
```json
{
    "penguin_version": "0.1.0",
    "engine_available": true,
    "checkpoints_enabled": true,
    "current_model": {
        "model": "anthropic/claude-3-5-sonnet-20240620",
        "provider": "anthropic",
        "streaming_enabled": true,
        "vision_enabled": true
    },
    "conversation_manager": {
        "active": true,
        "current_session_id": "session_20250528_161800_abc123",
        "total_messages": 12
    },
    "tool_manager": {
        "active": true,
        "total_tools": 23
    }
}
```

#### `GET /api/v1/system/status`
Get current system status including RunMode state.

**Response:**
```json
{
    "status": "active",
    "runmode_status": "Task: Authentication Refactor - Running",
    "continuous_mode": false,
    "streaming_active": false,
    "token_usage": {
        "main_model": {
            "prompt": 1250,
            "completion": 750,
            "total": 2000
        }
    },
    "timestamp": "2025-05-28T16:25:00.000000"
}
```

---

## Migration Notes

### Breaking Changes
- **None** - All new endpoints are additive

### Enhanced Existing Endpoints
- **Task execution endpoints** now support Engine layer when available
- **WebSocket streaming** improved with Engine integration
- **Conversation endpoints** enhanced with checkpoint awareness

### Required Updates for Frontend/Client Code

1. **Add checkpoint management UI**
   - Checkpoint creation, listing, rollback, and branching
   - Visual timeline of conversation checkpoints

2. **Add model switching UI**
   - Model selection dropdown with real-time switching
   - Display current model information

3. **Enhanced task execution**
   - Show task progress with iteration tracking
   - Display execution time and action results

4. **System status dashboard**
   - Real-time system information display
   - RunMode status monitoring

---

## Implementation Status

| Feature Category | Status | Priority | Notes |
|------------------|--------|----------|-------|
| Checkpoint Management | ✅ Complete | High | Full CRUD + branching |
| Model Management | ✅ Complete | High | Runtime switching + discovery |
| Enhanced Task Execution | ✅ Complete | Medium | Engine integration |
| System Diagnostics | ✅ Complete | Medium | Info + status endpoints |
| Event-based WebSockets | 🔄 Partial | Medium | Existing streaming enhanced |
| Resource Tracking | ❌ Pending | Low | Engine resource monitoring |

### Next Steps

1. **Frontend Integration**: Update web UI to use new checkpoint and model management endpoints
2. **Event System Enhancement**: Further integrate Core's event system with WebSocket endpoints  
3. **Resource Monitoring**: Add Engine resource tracking endpoints
4. **Documentation**: Update OpenAPI specs and generate client SDKs
5. **Testing**: Add comprehensive API tests for all new endpoints

---

## Example Usage Workflows

### Checkpoint Workflow
```bash
# Create checkpoint before risky operation
curl -X POST /api/v1/checkpoints/create \
  -H "Content-Type: application/json" \
  -d '{"name": "Before refactoring", "description": "Safe point"}'

# Continue conversation...

# If something goes wrong, rollback
curl -X POST /api/v1/checkpoints/cp_123/rollback

# Or create a branch to try different approach
curl -X POST /api/v1/checkpoints/cp_123/branch \
  -H "Content-Type: application/json" \
  -d '{"name": "Alternative approach"}'
```

### Model Switching Workflow
```bash
# List available models
curl /api/v1/models

# Switch to different model
curl -X POST /api/v1/models/load \
  -H "Content-Type: application/json" \
  -d '{"model_id": "google/gemini-2.5-pro-preview"}'

# Verify switch
curl /api/v1/models/current
```

### Task Execution Workflow
```bash
# Execute task with Engine
curl -X POST /api/v1/tasks/execute-sync \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Code Review",
    "description": "Review the authentication module for security issues",
    "time_limit": 15
  }'

# Monitor system status during execution
curl /api/v1/system/status
``` 