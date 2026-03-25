** 0.6.2.1  
**Status:** Active  
**Last Updated:** 2026-02-14

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [System Overview](#system-overview)
3. [Architecture Principles](#architecture-principles)
4. [High-Level Architecture](#high-level-architecture)
5. [Core Components](#core-components)
6. [Data Flow](#data-flow)
7. [Subsystem Design](#subsystem-design)
8. [Multi-Agent System](#multi-agent-system)
9. [Memory & Persistence](#memory--persistence)
10. [Tool System](#tool-system)
11. [Communication Layers](#communication-layers)
12. [Execution Model](#execution-model)
13. [Security & Governance](#security--governance)
14. [Performance Considerations](#performance-considerations)
15. [Deployment Architecture](#deployment-architecture)

---

## Executive Summary

Penguin is a modular, event-driven AI software engineering agent that combines autonomous code generation with project management, task coordination, and multi-agent orchestration. The system operates as a distributed nervous system with PenguinCore as the central coordinator, managing interactions between specialized components while maintaining loose coupling and high cohesion.

**Key Capabilities:**
- Multi-agent runtime with planner/implementer/QA personas
- Persistent conversation and memory systems
- Workspace-aware toolchain for code manipulation
- SQLite-backed project and task management
- Multiple interfaces: CLI, TUI, Web API, Python client
- Multi-provider LLM support (OpenAI, Anthropic, OpenRouter, Ollama, etc.)

---

## System Overview

### Design Philosophy

1. **Separation of Concerns**: Each subsystem handles a specific domain (conversations, tools, projects, etc.)
2. **Event-Driven Communication**: Components communicate through event buses and message passing
3. **Layered Architecture**: Clear separation between interfaces, core logic, and persistence layers
4. **Plugin-Based Extensibility**: Tools and capabilities can be dynamically loaded and extended
5. **Multi-Agent Orchestration**: Support for multiple specialized agents working in coordination

### Technology Stack

**Core:**
- Python 3.9+ (Docker base: 3.11-slim)
- Poetry 1.8.2 (package management)
- Pydantic (data validation)
- SQLite (persistence)

**Interfaces:**
- CLI: Typer + Rich + Questionary
- TUI: Textual
- Web API: FastAPI + Uvicorn + WebSockets + Jinja2
- Python Client: Direct library import

**LLM Integration:**
- LiteLLM (multi-provider abstraction)
- Providers: OpenRouter, Anthropic, OpenAI, Ollama, Gemini
- Streaming support via httpx/requests

**Execution:**
- IPython (interactive code execution)
- IPython kernel + widgets
- Watchdog (file system monitoring)

**Utilities:**
- GitPython (git operations)
- PyGithub (GitHub API)
- Pillow (image processing)
- NumPy/Pandas (data processing)
- NetworkX (graph operations)

---

## Architecture Principles

### 1. Modularity

Each component is designed as an independent module with well-defined interfaces:

```
penguin/
├── core/              # Core orchestration
├── engine/            # Reasoning loop
├── system/            # Conversation, memory, projects
├── tools/             # Tool registry and execution
├── llm/               # LLM adapters and streaming
├── multi/             # Multi-agent coordination
├── cli/               # Command-line interface
├── web/               # Web API server
└── tui/               # Terminal UI
```

### 2. Event-Driven Communication

Components communicate via:
- **MessageBus**: Inter-agent messaging
- **Event Bus**: System-wide event propagation
- **Telemetry Streams**: Progress and metrics

### 3. Progressive Initialization

Fast startup path with deferred heavy operations:
- Lazy tool loading
- Deferred memory indexing
- Background workers
- Startup profiling

### 4. Plugin Architecture

Tools and capabilities can be dynamically registered:
- Declarative tool definitions
- Plugin loader for discovery
- Runtime tool registration

---

## High-Level Architecture

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

---

## Core Components

### 1. PenguinCore (`core.py`)

**Purpose:** Central nervous system coordinating all subsystems.

**Key Responsibilities:**
- Initialize and wire subsystems
- Route messages between components
- Manage agent lifecycle
- Handle UI event emission
- Coordinate multi-step processing
- Manage runtime configuration

**Key Features:**
- Factory pattern creation with `PenguinCore.create()`
- Progressive initialization with startup profiling
- Fast startup mode for deferred heavy operations
- Agent registration and management
- MessageBus integration for inter-agent communication
- Telemetry and diagnostics collection

**Interface:**
```python
class PenguinCore:
    @classmethod
    def create(cls, config: PenguinConfig, workspace: Path) -> "PenguinCore"
    
    def register_agent(self, agent_id: str, **kwargs) -> None
    def get_agent(self, agent_id: str) -> Optional[EngineAgent]
    def emit_event(self, event: Event) -> None
    def get_telemetry(self) -> TelemetryData
```

### 2. Engine (`engine.py`)

**Purpose:** Reasoning and execution orchestrator.

**Core Loop:**
1. Prepare conversation state
2. Select appropriate agent (planner/implementer/QA/lite)
3. Request LLM completion
4. Parse and execute actions
5. Check stop conditions
6. Iterate or complete

**Key Components:**
- **EngineAgent**: Wrapper for agent-specific configurations
- **EngineSettings**: Runtime configuration for the engine
- **Stop Conditions**: TokenBudget, WallClock, External callbacks
- **Multi-Agent Coordinator**: Routes work to specialized agents

**Interface:**
```python
class Engine:
    def run(self, user_input: str, agent_id: str = "default") -> EngineResponse
    def run_stream(self, user_input: str, agent_id: str = "default") -> Iterator[EngineChunk]
    def stop(self) -> None
```

### 3. ModelConfig (`llm/model_config.py`)

**Purpose:** Configuration for LLM model parameters.

**Key Fields:**
```python
@dataclass
class ModelConfig:
    model: str                          # Model identifier
    provider: str                       # Provider (openai, anthropic, etc.)
    max_output_tokens: Optional[int]    # Response generation limit
    max_context_window_tokens: Optional[int]  # Input context capacity
    temperature: float                  # Sampling temperature
    reasoning_enabled: bool             # Extended thinking support
```

**Key Features:**
- Explicit token limit naming (no ambiguous `max_tokens`)
- Reasoning configuration for models like Claude, DeepSeek R1
- Provider-specific adapter selection
- Deprecation warnings for legacy property access

### 4. ConversationManager (`system/conversation_manager.py`)

**Purpose:** Manages conversation state, context, and persistence.

**Manages:**
- Session persistence (SQLite/filesystem)
- Context window management
- Message categorization
- Checkpoints and snapshots
- Multi-agent conversations
- Token tracking and budgets

**Architecture:**
- **SessionManager**: Handles conversation persistence
- **ContextWindowManager**: Enforces token limits with intelligent trimming
- **CheckpointManager**: Branch/restore conversation states
- **ConversationSystem**: Per-agent conversation contexts

**Context Sharing Utilities:**
| Function | Description |
|----------|-------------|
| `shares_context_window(agent1, agent2)` | Check if two agents share the same CWM |
| `get_context_sharing_info(agent_id)` | Get sharing relationships for an agent |
| `get_context_window_stats(agent_id)` | Get token usage stats for agent's context |
| `sync_context_to_child(parent, child)` | Copy context snapshot to isolated child |
| `get_shared_context_agents(agent_id)` | List all agents sharing context with given agent |

---

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

**Per-Agent Streaming (`llm/stream_handler.py`):**

The `AgentStreamingStateManager` enables parallel streaming from multiple agents:

```python
AgentStreamingStateManager:
  ├── Per-agent StreamingStateManager instances
  ├── Isolation: Each agent's stream is independent
  ├── Backward compatibility: Default agent fallback
  └── Methods:
      ├── handle_chunk(chunk, agent_id) → events tagged with agent_id
      ├── finalize(agent_id) → complete message for specific agent
      ├── is_agent_active(agent_id) → check streaming state
      └── get_active_agents() → list currently streaming agents
```

---

## Subsystem Design

### 1. Tool System (`tools/`)

**Architecture:**
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
      ├── Browser Automation (PyDoll, navigation)
      └── Sub-Agent Tools (multi-agent coordination)
```

**Sub-Agent Tools:**
| Tool | Description |
|------|-------------|
| `spawn_sub_agent` | Create child agent with optional `background=True` |
| `stop_sub_agent` | Cancel a running agent |
| `resume_sub_agent` | Resume a paused agent |
| `get_agent_status` | Query agent state, result, or error |
| `wait_for_agents` | Block until agents complete (with timeout) |
| `delegate` | Send task to specific agent |
| `delegate_explore_task` | Spawn haiku agent for codebase exploration |
| `send_message` | Inter-agent messaging via MessageBus |
| `get_context_info` | Query context sharing relationships |
| `sync_context` | Sync context from parent to child |

**Tool Execution Pipeline:**
1. Action parsed from LLM response
2. Tool identified by name/type
3. Parameters validated and prepared
4. Tool executed with workspace context
5. Result formatted and returned
6. Added to conversation as system message

### 2. Memory System (`memory/`)

**Architecture:**
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

**Architecture:**
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

---

## Multi-Agent System

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

### Parallel Execution System

The multi-agent system supports true parallel execution via `AgentExecutor` (`multi/executor.py`):

```python
AgentExecutor:
  ├── Semaphore-based concurrency control (PENGUIN_MAX_CONCURRENT_TASKS)
  ├── Background task spawning (asyncio.Task management)
  ├── State machine: PENDING → RUNNING → COMPLETED/FAILED/CANCELLED
  ├── Pause/Resume support for long-running agents
  └── Wait operations (single agent, multiple agents, all agents)
```

**Agent States:**
- `PENDING`: Queued, waiting for semaphore slot
- `RUNNING`: Actively processing
- `PAUSED`: Suspended, can be resumed
- `COMPLETED`: Finished successfully with result
- `FAILED`: Terminated with error
- `CANCELLED`: Stopped by request

**Background Execution Pattern:**
```python
# Spawn agents in background (non-blocking)
spawn_sub_agent(agent_id="worker-1", initial_prompt="...", background=True)
spawn_sub_agent(agent_id="worker-2", initial_prompt="...", background=True)

# Wait for specific agents or all
wait_for_agents(agent_ids=["worker-1", "worker-2"], timeout=30000)

# Query status
get_agent_status(agent_id="worker-1")  # Returns state, result, error
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

---

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

**Token Limit Naming Convention:**

| Name | Purpose | Location |
|------|---------|----------|
| `max_output_tokens` | Model response/generation limit | ModelConfig |
| `max_context_window_tokens` | Input context capacity | ModelConfig, ContextWindowManager |
| `max_category_tokens` | Per-category budget limit | TokenBudget |
| `shared_context_window_max_tokens` | Multi-agent shared context | Agent registration |
| `model_output_max_tokens` | Per-agent output limit | Agent registration |

**Trimming Strategy:**
1. Preserve SYSTEM messages (never truncated)
2. Keep recent DIALOG messages
3. Truncate oldest SYSTEM_OUTPUT first (lowest priority)
4. Selective CONTEXT retention based on relevance
5. Category budgets are dynamic based on live config

---

## Tool System

### Tool Registry Architecture

```python
Tool Definition:
{
    "name": "read_file",
    "category": "file_ops",
    "description": "Read file contents",
    "parameters": {
        "path": {"type": "string", "required": True},
        "line_numbers": {"type": "boolean", "default": False}
    },
    "execute": lambda params: execute_read_file(**params)
}
```

**Tool Categories:**
- **File Operations**: read, write, edit, diff, search
- **Code Analysis**: AST, dependencies, linting, formatting
- **Search**: grep, workspace search, web search (Perplexity)
- **Memory**: declarative notes, summary notes, retrieval
- **Project Management**: tasks, resources, budgets
- **Browser Automation**: PyDoll, navigation, screenshot
- **Sub-Agent Coordination**: spawn, stop, resume, delegate, messaging

### Tool Execution Flow

```
LLM Response with Action
    ↓
ActionExecutor.parse_action()
    ↓
ToolManager.get_tool(tool_name)
    ↓
Validate parameters
    ↓
Execute tool with workspace context
    ↓
Format result
    ↓
Add to conversation as system message
```

---

## Communication Layers

### 1. MessageBus

**Purpose:** Inter-agent messaging and system-wide event propagation.

**Protocol:**
```python
class ProtocolMessage:
    sender: Optional[str]      # agent_id | "human" | None
    recipient: Optional[str]   # agent_id | "human" | None
    content: Any
    message_type: str          # "message" | "action" | "status" | "event"
    metadata: Dict[str, Any]
    channel: Optional[str]
    timestamp: str
    session_id: str
    message_id: str
```

### 2. Event Bus

**Purpose:** System-wide event propagation for UI updates and telemetry.

**Event Types:**
- Progress events (tool execution, agent status)
- Telemetry events (token usage, timing)
- Error events (exceptions, failures)
- Lifecycle events (agent start/stop, session changes)

### 3. Telemetry Streams

**Purpose:** Collect metrics for dashboards and monitoring.

**Metrics:**
- Message counts per agent
- Token usage (input/output)
- Tool execution times
- Agent state transitions
- Error rates and types

---

## Execution Model

### Run Loop

```python
class Engine:
    def run(self, user_input: str, agent_id: str = "default") -> EngineResponse:
        # 1. Prepare conversation state
        conversation = self.conversation_manager.get_conversation(agent_id)
        
        # 2. Select agent
        agent = self.get_agent(agent_id)
        
        # 3. Request LLM completion
        response = self.api_client.get_completion(
            messages=conversation.get_messages(),
            model_config=agent.model_config,
            stream=False
        )
        
        # 4. Parse and execute actions
        actions = self.parse_actions(response.content)
        for action in actions:
            result = self.action_executor.execute_action(action)
            conversation.add_message("system", result)
        
        # 5. Check stop conditions
        if self.should_stop():
            return EngineResponse(status="stopped")
        
        # 6. Iterate or complete
        return EngineResponse(content=response.content, status="completed")
```

### Stop Conditions

- **TokenBudget**: Stop when token limit reached
- **WallClock**: Stop after time limit
- **ExternalCallback**: Stop when callback returns True
- **ManualStop**: User-initiated stop

---

## Security & Governance

### 1. Permission System

- Workspace boundaries enforced
- File operation restrictions
- Tool access control per agent
- API key management via environment variables

### 2. Token Budgeting

- Per-category token limits
- Context window enforcement
- Cost tracking and reporting
- Budget alerts and limits

### 3. Error Recovery

- Graceful degradation
- Circuit breaker patterns
- Retry logic with exponential backoff
- Error logging and tracing

---

## Performance Considerations

### 1. Fast Startup

- Lazy loading of tools and memory providers
- Deferred memory indexing
- Background workers for heavy operations
- Startup profiling and optimization

### 2. Memory Efficiency

- Context window trimming
- Token budget management
- Lazy loading of resources
- Garbage collection tuning

### 3. Concurrency

- Semaphore-based concurrency control
- Async I/O for network operations
- Parallel agent execution
- Background task management

### 4. Caching

- Tool execution caching
- Memory search caching
- LLM response caching (optional)
- File system monitoring (watchdog)

---

## Deployment Architecture

### 1. Docker

**Multi-stage build:**
```dockerfile
FROM python:3.11-slim as base
# Phase 1: Base image and core dependencies

FROM base as dependencies
# Phase 2: Install dependencies

FROM dependencies as builder
# Phase 3: Build and package

FROM base as final
# Phase 4: Clean final image
```

### 2. Web API

**FastAPI + Uvicorn:**
- REST endpoints for core operations
- WebSocket endpoints for streaming
- OpenAPI documentation
- Embeddable `PenguinAPI` class

### 3. CLI

**Typer + Rich:**
- Interactive commands
- Setup wizard
- Progress bars and spinners
- Colored output

### 4. TUI

**Textual:**
- Terminal-based interface
- Real-time updates
- Keyboard navigation
- Rich widgets

---

## Appendix

### A. Configuration

**Config Hierarchy:**
1. `~/.penguin/config.yml` (global)
2. `.penguin/config.yml` (project)
3. `.penguin/settings.local.yml` (local, gitignored)
4. Environment variables
5. CLI arguments

### B. Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `PENGUIN_WORKSPACE` | Workspace path | `~/.penguin` |
| `OPENROUTER_API_KEY` | OpenRouter API key | - |
| `ANTHROPIC_API_KEY` | Anthropic API key | - |
| `OPENAI_API_KEY` | OpenAI API key | - |
| `PENGUIN_MAX_CONCURRENT_TASKS` | Max concurrent agents | 4 |

### C. File Structure

```
penguin/
├── core/              # Core orchestration
├── engine/            # Reasoning loop
├── system/            # Conversation, memory, projects
├── tools/             # Tool registry and execution
├── llm/               # LLM adapters and streaming
├── multi/             # Multi-agent coordination
├── cli/               # Command-line interface
├── web/               # Web API server
├── tui/               # Terminal UI
├── utils/             # Utilities
└── context/           # Documentation and notes
```

### D. API Endpoints

**Web API (FastAPI):**
- `POST /chat` - Send message, get response
- `POST /chat/stream` - Streaming chat
- `POST /agent/spawn` - Create sub-agent
- `POST /agent/stop` - Stop agent
- `GET /agent/status` - Query agent status
- `GET /telemetry` - Get metrics
- `GET /health` - Health check

---

**Document Version:** 1.0  
**Maintained By:** Penguin Development Team  
**License:** AGPL-3.0-or-later
