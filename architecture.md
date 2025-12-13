# Penguin Architecture Documentation

## Table of Contents
1. [Overview](#overview)
2. [System Architecture](#system-architecture)
3. [Core Components](#core-components)
4. [Data Flow](#data-flow)
5. [Key Subsystems](#key-subsystems)
6. [Multi-Agent Architecture](#multi-agent-architecture)
7. [Memory & Persistence](#memory--persistence)
8. [Tool System](#tool-system)
9. [Communication Layers](#communication-layers)
10. [Execution Flow](#execution-flow)

## Overview

Penguin is a sophisticated AI coding assistant built on a modular, event-driven architecture that orchestrates multiple subsystems to provide intelligent software engineering capabilities. The system operates as a distributed nervous system where PenguinCore acts as the central coordinator, managing interactions between specialized components while maintaining loose coupling and high cohesion.

### Design Philosophy

- **Separation of Concerns**: Each subsystem handles a specific domain (conversations, tools, projects, etc.)
- **Event-Driven Communication**: Components communicate through event buses and message passing
- **Layered Architecture**: Clear separation between interfaces, core logic, and persistence layers
- **Plugin-Based Extensibility**: Tools and capabilities can be dynamically loaded and extended
- **Multi-Agent Orchestration**: Support for multiple specialized agents working in coordination

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Interface Layer                              │
├────────────┬────────────┬────────────┬────────────┬────────────────┤
│    CLI     │    TUI     │  Web API   │   Python   │   Dashboard    │
│ (Typer)    │ (Textual)  │ (FastAPI)  │  Client    │   (Telemetry)  │
└────────────┴────────────┴────────────┴────────────┴────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          PenguinCore                                │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ • Event Bus & MessageBus                                     │  │
│  │ • UI Event Emission                                          │  │
│  │ • Progress Callbacks                                         │  │
│  │ • Runtime Configuration                                      │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
┌──────────────┐     ┌──────────────────┐     ┌──────────────────┐
│    Engine    │     │  Conversation    │     │   Tool Manager   │
│              │◄────┤    Manager       │────► │                  │
│ • Run Loop   │     │ • Sessions       │     │ • Registry       │
│ • Agents     │     │ • Context Window │     │ • Execution      │
│ • Stop Conds │     │ • Checkpoints    │     │ • Plugin Loader  │
└──────────────┘     └──────────────────┘     └──────────────────┘
        │                       │                       │
        ▼                       ▼                       ▼
┌──────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  API Client  │     │ Project Manager  │     │ Action Executor  │
│              │     │                  │     │ (utils/parser)   │
│ • Adapters   │     │ • Task Tracking  │     │ • Parse & Route  │
│ • LiteLLM    │     │ • Dependencies   │     │ • Tool Dispatch  │
│ • OpenRouter │     │ • SQLite ACID    │     │ • Result Format  │
│ • Streaming  │     │                  │     │                  │
└──────────────┘     └──────────────────┘     └──────────────────┘
        │
        ▼
┌──────────────────────────────────────────────────────────────────┐
│                      LLM Adapters (llm/adapters/)                │
├──────────┬──────────┬──────────┬──────────┬────────────────────┤
│  OpenAI  │Anthropic │  Gemini  │  Ollama  │ LiteLLM/OpenRouter │
└──────────┴──────────┴──────────┴──────────┴────────────────────┘
```

## Core Components

### 1. PenguinCore (`core.py`)

The central nervous system that coordinates all subsystems:

```python
class PenguinCore:
    # Key Responsibilities:
    - Initialize and wire subsystems
    - Route messages between components
    - Manage agent lifecycle
    - Handle UI event emission
    - Coordinate multi-step processing
    - Manage runtime configuration
```

**Key Features:**
- Factory pattern creation with `PenguinCore.create()`
- Progressive initialization with startup profiling
- Fast startup mode for deferred heavy operations
- Agent registration and management
- MessageBus integration for inter-agent communication
- Telemetry and diagnostics collection

### 2. Engine (`engine.py`)

The reasoning and execution orchestrator:

```python
class Engine:
    # Core Loop:
    1. Prepare conversation state
    2. Select appropriate agent (planner/implementer/QA/lite)
    3. Request LLM completion
    4. Parse and execute actions
    5. Check stop conditions
    6. Iterate or complete
```

**Key Components:**
- **EngineAgent**: Wrapper for agent-specific configurations
- **EngineSettings**: Runtime configuration for the engine
- **Stop Conditions**: TokenBudget, WallClock, External callbacks
- **Multi-Agent Coordinator**: Routes work to specialized agents

### 3. ModelConfig (`llm/model_config.py`)

Configuration for LLM model parameters:

```python
@dataclass
class ModelConfig:
    model: str                          # Model identifier
    provider: str                       # Provider (openai, anthropic, etc.)
    max_output_tokens: Optional[int]    # Response generation limit
    max_context_window_tokens: Optional[int]  # Input context capacity
    temperature: float                  # Sampling temperature
    reasoning_enabled: bool             # Extended thinking support
    # ... additional fields
```

**Key Features:**
- Explicit token limit naming (no ambiguous `max_tokens`)
- Reasoning configuration for models like Claude, DeepSeek R1
- Provider-specific adapter selection
- Deprecation warnings for legacy property access

### 4. ConversationManager (`system/conversation_manager.py`)

Manages conversation state, context, and persistence:

```python
class ConversationManager:
    # Manages:
    - Session persistence (SQLite/filesystem)
    - Context window management
    - Message categorization
    - Checkpoints and snapshots
    - Multi-agent conversations
    - Token tracking and budgets
```

**Architecture:**
- **SessionManager**: Handles conversation persistence
- **ContextWindowManager**: Enforces token limits with intelligent trimming
- **CheckpointManager**: Branch/restore conversation states
- **ConversationSystem**: Per-agent conversation contexts

## Data Flow

### 1. Message Processing Flow

```
User Input → CLI/API → PenguinCore
    ↓
ConversationManager.process_message()
    ↓
Add to conversation history
    ↓
Engine.get_response() / APIClient.get_response()
    ↓
Parse actions from response
    ↓
ActionExecutor.execute_action()
    ↓
Tool execution & result formatting
    ↓
Update conversation with results
    ↓
Response to user
```

### 2. Streaming Response Flow

```
API Request with streaming=True
    ↓
APIClient creates stream
    ↓
Chunks flow through stream_callback
    ↓
UI receives real-time updates via:
  - WebSocket (Web API)
  - Console output (CLI)
  - Event emission (TUI)
    ↓
Complete response assembled
    ↓
Added to conversation history
```

## Key Subsystems

### 1. Tool System (`tools/`)

Modular tool architecture with lazy loading:

```python
ToolManager:
  ├── Registry (declarative tool definitions)
  ├── Plugin Loader (dynamic tool discovery)
  ├── Lazy Loading (deferred initialization)
  └── Tool Categories:
      ├── File Operations (read, write, edit)
      ├── Code Analysis (AST, dependencies, linting)
      ├── Search (grep, workspace, web)
      ├── Memory (declarative notes, retrieval)
      ├── Project Management (tasks, resources)
      └── Browser Automation (PyDoll, navigation)
```

**Tool Execution Pipeline:**
1. Action parsed from LLM response
2. Tool identified by name/type
3. Parameters validated and prepared
4. Tool executed with workspace context
5. Result formatted and returned
6. Added to conversation as system message

### 2. Memory System (`memory/`)

Multi-layered memory with pluggable providers:

```python
Memory Architecture:
  ├── Declarative Memory (explicit notes)
  ├── Summary Memory (auto-generated)
  ├── Semantic Search (vector embeddings)
  └── Providers (memory/providers/):
      ├── SQLite (default, built-in)
      ├── FAISS (vector search)
      ├── LanceDB (columnar storage)
      ├── Milvus (distributed vectors)
      └── File (simple file-based)
  └── ChromaDB (memory/chroma_provider.py - HuggingFace embeddings)
```

**Memory Flow:**
1. Content ingested (files, conversations, notes)
2. Embeddings generated (if vector provider)
3. Indexed for retrieval
4. Retrieved based on context/query
5. Injected into conversation context

### 3. Project Management (`project/`)

ACID-compliant project and task tracking:

```python
ProjectManager:
  ├── SQLite Backend (transactions)
  ├── Task Dependencies (DAG)
  ├── Resource Budgets (tokens, time)
  ├── Execution Tracking (status, metrics)
  └── Event Integration (progress events)
```

**Task Execution Flow:**
1. Task created with dependencies
2. Resources allocated
3. Execution tracked via RunMode
4. Progress events emitted
5. Completion recorded with metrics

## Multi-Agent Architecture

### Agent Hierarchy

```
Default Agent
  ├── Planner (high-level strategy)
  ├── Implementer (code generation)
  ├── QA (review and testing)
  └── Sub-Agents (specialized tasks)
      ├── Shared Session (same conversation)
      ├── Shared Context Window (limited view)
      └── Independent (isolated context)
```

### Agent Registration

```python
core.register_agent(
    agent_id="specialist",
    system_prompt="You are a Python specialist...",
    persona="python_expert",  # From config
    model_config_id="claude-3.5",  # Model override
    share_session_with="default",  # Parent agent
    shared_context_window_max_tokens=50000,  # Context limit for this agent
    model_output_max_tokens=8000,  # Output limit for this agent
    default_tools=["python_ast", "lint"]  # Tool subset
)
```

### Agent Communication

**MessageBus Protocol:**
```python
ProtocolMessage (system/message_bus.py):
  - sender: agent_id | "human" | None
  - recipient: agent_id | "human" | None (None = broadcast)
  - content: Any
  - message_type: "message" | "action" | "status" | "event"
  - metadata: Dict[str, Any]
  - channel: Optional[str]  # Logical room/channel identifier
  - timestamp: ISO format string
  - session_id: conversation_reference
  - message_id: unique identifier
```

**Communication Patterns:**
1. **Direct Messaging**: Agent → Agent via MessageBus
2. **Broadcast**: Agent → All via channels
3. **Human Interface**: Agent ↔ Human via UI events
4. **Sub-Agent Delegation**: Parent → Child with context

## Memory & Persistence

### Conversation Persistence

```
WORKSPACE_PATH/                    # Configurable via PENGUIN_WORKSPACE env var
  ├── conversations/               # Session and message storage
  │   ├── default/
  │   │   ├── {session_id}/
  │   │   │   ├── messages.json
  │   │   │   ├── metadata.json
  │   │   │   └── checkpoints/
  │   │   └── current.json
  │   └── {agent_id}/
  │       └── {session_id}/
  ├── checkpoints/                 # Checkpoint storage (managed by CheckpointManager)
  ├── memory_db/                   # Memory storage
  ├── logs/                        # Log files
  └── context/                     # Context files

Project Root/                      # Project-level configuration
  └── .penguin/
      ├── config.yml               # Project config overrides
      ├── settings.local.yml       # Local settings (gitignored)
      └── projects.db              # Task/project database
```

### Context Window Management

**Token Budget Categories:**
```python
MessageCategory (system/state.py):
  SYSTEM: 10%        # System prompts and instructions (highest priority, never truncated)
  CONTEXT: 35%       # Reference info: declarative notes, context folders, project docs
  DIALOG: 50%        # User/assistant conversation messages (medium priority)
  SYSTEM_OUTPUT: 5%  # Tool execution results and system outputs (lowest priority)
  ERROR              # Error messages from system or tools
  INTERNAL           # Core's internal thoughts/plans (if exposed)
  UNKNOWN            # Fallback for unset categories
```


### Token Limit Naming Convention

The codebase uses explicit naming for token limits to avoid ambiguity:

| Name | Purpose | Location |
|------|---------|----------|
| `max_output_tokens` | Model response/generation limit | ModelConfig |
| `max_context_window_tokens` | Input context capacity | ModelConfig, ContextWindowManager |
| `max_category_tokens` | Per-category budget limit | TokenBudget |
| `shared_context_window_max_tokens` | Multi-agent shared context | Agent registration |
| `model_output_max_tokens` | Per-agent output limit | Agent registration |

**Deprecated:** The ambiguous `max_tokens` property is deprecated with warnings. Use the explicit names above.

**Trimming Strategy:**
1. Preserve SYSTEM messages (never truncated)
2. Keep recent DIALOG messages
3. Truncate oldest SYSTEM_OUTPUT first (lowest priority)
4. Selective CONTEXT retention based on relevance
5. Category budgets are dynamic based on live config

## Tool System

### Tool Registry Architecture

```python
Tool Definition:
{
    "name": "read_file",
    "category": "file_ops",
    "description": "Read file contents",
    "parameters": {
        "path": {"type": "string", "required": true},
        "encoding": {"type": "string", "default": "utf-8"}
    },
    "handler": ReadFileTool,
    "lazy_load": true,
    "workspace_aware": true
}
```

### Tool Execution Context

```python
ExecutionContext:
  - workspace_path: current_directory
  - conversation: active_conversation
  - project: current_project
  - agent_id: executing_agent
  - permissions: allowed_operations
  - ui_callback: result_display
```

## Communication Layers

### 1. Event Bus

Asynchronous event distribution with priority levels (utils/events.py):

```python
EventTypes:
  - message (user/assistant/system)
  - token_update (usage tracking)
  - action_executed (tool results)
  - progress (task/iteration)
  - stream_chunk (real-time output)
  - agent_state (pause/resume/switch)
```

### 2. MessageBus

Asynchronous agent communication:

```python
Channels:
  - direct (point-to-point)
  - broadcast (all agents)
  - human (UI interface)
  - telemetry (metrics)
```

### 3. UI Event Emission

UI update pipeline:

```python
emit_ui_event(event_type, data)
    ↓
Event Bus dispatch
    ↓
UI Subscribers:
  - CLI: Console output
  - TUI: Textual widgets
  - Web: WebSocket broadcast
  - Dashboard: Telemetry
```

## Execution Flow

### 1. Interactive Chat Mode

```
1. User enters message
2. PenguinCore.process_message()
3. Add to conversation
4. Engine reasoning loop:
   a. Get LLM response
   b. Parse actions
   c. Execute tools
   d. Update context
5. Stream/return response
6. Save conversation
```

### 2. Run Mode (Autonomous)

```
1. Define task/objective
2. RunMode.start()
3. Engine continuous loop:
   while not complete:
     a. Assess progress
     b. Plan next steps
     c. Execute actions
     d. Check stop conditions
     e. Emit progress events
4. Complete with results
```

### 3. Multi-Agent Workflow

```
1. Register specialized agents
2. Parent agent receives task
3. Delegate to sub-agents:
   a. Route by capability
   b. Share context/session
   c. Execute in parallel/sequence
4. Collect results
5. Synthesize response
```


### Engine Loop Termination

The engine's `run_response` and `run_task` methods use explicit termination signals:

**run_response (Conversational Mode):**
- Terminates ONLY when `finish_response` tool is called
- Max iterations (default 5000) as safety limit
- NO implicit termination on empty action results

**run_task (Autonomous Mode):**
- Terminates ONLY when `finish_task` tool is called
- Task marked for human review (not auto-completed)
- Phrase-based completion detection is deprecated

**Important:** The LLM must explicitly call termination tools. This prevents premature loop exit when the LLM is processing tool results and needs to continue.

## Performance Optimizations

### 1. Fast Startup Mode

- Deferred memory indexing
- Lazy tool loading
- Background initialization
- Connection pooling
- Cached configurations

### 2. Token Optimization

- Intelligent context trimming
- Category-based budgets
- Compression of old messages
- Selective tool result inclusion
- Model-specific routing

### 3. Concurrent Processing

- Parallel tool execution
- Async API calls
- Background indexing
- Stream processing
- Event-driven updates

## Extension Points

### 1. Custom Tools

```python
@register_tool("my_tool")
class MyTool:
    async def execute(self, params, context):
        # Tool implementation
        return result
```

### 2. Memory Providers

```python
class CustomMemoryProvider:
    def index(self, content): ...
    def search(self, query): ...
    def retrieve(self, ids): ...
```

### 3. Agent Personas

```yaml
agent_personas:
  specialist:
    name: "Python Specialist"
    system_prompt: "..."
    model: 
      id: "claude-3.5-sonnet"
      temperature: 0.2
    default_tools: ["ast", "lint"]
```

## Configuration Architecture

### Hierarchical Configuration

```
1. Default values (code)
2. config.yml (user settings)
3. Environment variables
4. Runtime overrides
5. Agent-specific settings
```

### Configuration Flow

```python
Config.load_config()
  ↓
Merge sources
  ↓
RuntimeConfig (dynamic updates)
  ↓
Observer pattern (components notified)
  ↓
Applied to subsystems
```

## Security & Governance

### 1. Permission Model

- Workspace boundaries
- Tool execution limits
- File system access controls
- Network request filtering
- Resource quotas

### 2. Audit & Telemetry

- Message tracking
- Action logging
- Token usage reporting
- Performance metrics
- Error tracing

### 3. Error Recovery

- Graceful degradation
- Retry mechanisms
- Circuit breakers
- Fallback strategies
- State recovery

## Conclusion

Penguin's architecture represents a sophisticated orchestration of specialized subsystems working in concert to deliver intelligent software engineering capabilities. The modular design enables:

- **Scalability**: Components can be enhanced independently
- **Extensibility**: New tools and agents easily integrated
- **Reliability**: Robust error handling and recovery
- **Performance**: Optimized startup and execution paths
- **Flexibility**: Multiple interfaces and deployment modes

The system's strength lies not in any single component but in the seamless integration of its parts, creating an AI assistant that can handle complex, multi-step software development tasks while maintaining context, learning from interactions, and adapting to different workflows and requirements.