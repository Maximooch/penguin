# Reference Architecture Comparison: OpenCode, Cline, Kimi-CLI

**Purpose:** Synthesize learnings from three production AI coding assistants to guide Penguin CLI development
**Date:** 2025-11-05
**Related Docs:**
- [OpenCode Analysis](./reference-analysis-opencode.md)
- [Cline Analysis](./reference-analysis-cline.md)
- [Kimi-CLI Analysis](./reference-analysis-kimi-cli.md)
- [Penguin CLI Architecture](./cli-architecture.md)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture Comparison](#2-architecture-comparison)
3. [Technology Stack Comparison](#3-technology-stack-comparison)
4. [Pattern Analysis](#4-pattern-analysis)
5. [Best Practices Synthesis](#5-best-practices-synthesis)
6. [Recommendations for Penguin](#6-recommendations-for-penguin)
7. [Implementation Roadmap](#7-implementation-roadmap)
8. [Decision Matrix](#8-decision-matrix)

---

## 1. Executive Summary

### 1.1 Key Findings

| Finding | Impact | Recommendation |
|---------|---------|----------------|
| **Pure Python is viable** | High | Stick with Python for Penguin CLI |
| **gRPC provides type safety** | High | Adopt for Python ↔ CLI communication |
| **Event-driven architecture wins** | High | Implement wire protocol pattern |
| **JSONL for history** | Medium | Adopt for conversation persistence |
| **Checkpoint systems are valuable** | Medium | Add time-travel debugging |
| **Tool coordinators enable extensibility** | High | Refactor tool system |

### 1.2 Project Comparison at a Glance

| Aspect | OpenCode | Cline | Kimi-CLI | Penguin Current |
|--------|----------|-------|----------|-----------------|
| **Language** | TypeScript (Bun) | TypeScript (Node.js) | Python | Python + TypeScript |
| **Runtime** | Bun | Node.js | Python 3.13+ | Python + Node.js |
| **Scale** | ~28K LOC | ~144K LOC | ~8.5K LOC | ~10K LOC |
| **Platform** | CLI + Desktop | VSCode Extension | CLI + TUI | CLI + TUI |
| **Architecture** | Client/Server | Extension + Webview | Event-driven | Context + Hooks |
| **State** | File-based KV | Multi-tier cache | JSONL | React Context |
| **Communication** | HTTP + SSE | gRPC (Protobuf) | Event wire | Direct calls |
| **UI** | SolidJS TUI | React Webview | prompt-toolkit | Ink (React) |
| **LLM Integration** | Vercel AI SDK | 40+ providers | kosong framework | OpenRouter |
| **Maturity** | Production | Production | Production | Beta |

### 1.3 The Python Question: Answered

**Can Penguin use pure Python for CLI?**

✅ **YES!** Kimi-CLI proves it with 8,546 lines of production-ready Python.

**Should Penguin use TypeScript/Node.js?**

❌ **NO.** No compelling advantage over Python, and Penguin already has Python backend.

**Best Architecture for Penguin?**

✅ **Python CLI + Python Backend** with:
- gRPC for communication (type-safe boundary)
- Event-driven UI updates (wire protocol)
- prompt-toolkit + rich for TUI
- JSONL for conversation history
- PyInstaller for distribution

---

## 2. Architecture Comparison

### 2.1 High-Level Architectures

**OpenCode (Client/Server Split):**
```
┌─────────────┐  HTTP/SSE   ┌─────────────┐  Streaming  ┌──────────┐
│ SolidJS TUI │ ◄─────────► │ Hono Server │ ◄─────────► │   LLM    │
│   (Bun)     │             │   (Bun)     │             │ Provider │
└─────────────┘             └─────────────┘             └──────────┘
                                   │
                            ┌──────┴──────┐
                            │ File-based  │
                            │   Storage   │
                            └─────────────┘
```

**Cline (VSCode Extension):**
```
┌─────────────┐             ┌─────────────┐  Streaming  ┌──────────┐
│ React       │  gRPC/      │ Extension   │ ◄─────────► │   LLM    │
│ Webview     │  Protobuf   │ (Node.js)   │             │ Provider │
│             │ ◄─────────► │             │             │          │
└─────────────┘             └─────────────┘             └──────────┘
                                   │
                            ┌──────┴──────┐
                            │ VSCode APIs │
                            │ + Cache     │
                            └─────────────┘
```

**Kimi-CLI (Event-Driven):**
```
┌─────────────┐             ┌─────────────┐  Streaming  ┌──────────┐
│ prompt-     │  Wire       │ Agent Loop  │ ◄─────────► │   LLM    │
│ toolkit UI  │  Protocol   │  (Python)   │             │ Provider │
│             │ ◄─────────► │             │             │          │
└─────────────┘             └─────────────┘             └──────────┘
                                   │
                            ┌──────┴──────┐
                            │    JSONL    │
                            │   History   │
                            └─────────────┘
```

**Penguin Current:**
```
┌─────────────┐             ┌─────────────┐  Streaming  ┌──────────┐
│ Ink/React   │  Direct     │ Python      │ ◄─────────► │OpenRouter│
│   (Node)    │  Function   │ Backend     │             │          │
│             │  Calls      │             │             │          │
└─────────────┘             └─────────────┘             └──────────┘
                                   │
                            ┌──────┴──────┐
                            │ React State │
                            └─────────────┘
```

### 2.2 Architecture Philosophy

| Project | Philosophy | Strengths | Weaknesses |
|---------|-----------|-----------|------------|
| **OpenCode** | Client/Server separation enables multiple clients | - Scalable<br>- Multi-client ready<br>- Type-safe | - More complex<br>- More moving parts |
| **Cline** | VSCode-native with deep IDE integration | - Rich IDE features<br>- Native diff views<br>- Large ecosystem | - VSCode-only<br>- Extension complexity |
| **Kimi-CLI** | Event-driven simplicity with powerful patterns | - Simple<br>- Lightweight<br>- Easy to understand | - Single-client focused |
| **Penguin** | React-based with Python backend | - Flexible<br>- Modern stack | - Duplicate WebSocket<br>- Monolithic component |

### 2.3 Recommended Architecture for Penguin

```
┌─────────────────────────────────────────────────────────┐
│                    Penguin v2 Architecture               │
│                                                          │
│  ┌────────────────┐  gRPC/Protobuf  ┌────────────────┐ │
│  │  prompt-toolkit│  ◄────────────► │  Python Core   │ │
│  │  + rich TUI    │   Wire Protocol │  (Engine)      │ │
│  │  (Python)      │                 │                │ │
│  └────────────────┘                 └────────────────┘ │
│         │                                   │           │
│         │ Event Stream                      │ Tools     │
│         ↓                                   ↓           │
│  ┌────────────────┐                 ┌────────────────┐ │
│  │  Event Handler │                 │  Tool System   │ │
│  │  (renders UI)  │                 │  (coordinator) │ │
│  └────────────────┘                 └────────────────┘ │
│                                             │           │
│                                             ↓           │
│                                      ┌────────────────┐ │
│                                      │  JSONL History │ │
│                                      │  + Checkpoints │ │
│                                      └────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

**Key Decisions:**
1. **Pure Python** - CLI and backend in same language
2. **gRPC optional** - Can use if type safety across boundaries needed
3. **Event-driven** - Wire protocol for UI updates
4. **prompt-toolkit** - Better TUI than Ink
5. **JSONL** - Append-only conversation history

---

## 3. Technology Stack Comparison

### 3.1 Language & Runtime

| Component | OpenCode | Cline | Kimi-CLI | Recommended for Penguin |
|-----------|----------|-------|----------|-------------------------|
| **Backend** | TypeScript (Bun) | TypeScript (Node.js) | Python | ✅ Python |
| **CLI/UI** | TypeScript (Bun) | TypeScript (Node.js) | Python | ✅ Python |
| **Runtime** | Bun | Node.js | CPython 3.13+ | ✅ CPython 3.13+ |
| **Why?** | Performance | Ecosystem | Simplicity | Code reuse + ecosystem |

### 3.2 UI Framework

| Project | Framework | Pros | Cons | For Penguin? |
|---------|-----------|------|------|--------------|
| **OpenCode** | SolidJS (@opentui) | Fast, fine-grained reactivity | Custom TUI library | ❌ Too specialized |
| **Cline** | React (webview) | Rich ecosystem, familiar | Webview overhead | ❌ Not terminal |
| **Kimi-CLI** | prompt-toolkit + rich | Mature, powerful, Python-native | Python-only | ✅ **Adopt** |
| **Penguin** | Ink (React for terminal) | React patterns, good | Limited features vs prompt-toolkit | ⚠️ Consider migrating |

**Recommendation:** Migrate Penguin from Ink to prompt-toolkit + rich
- More features (file completion, better input)
- Better performance
- Pure Python (no Node.js needed)
- Battle-tested (used by many CLIs)

### 3.3 LLM Integration

| Project | Framework | Providers | Streaming | Tool Calling |
|---------|-----------|-----------|-----------|--------------|
| **OpenCode** | Vercel AI SDK | 10+ | ✅ | ✅ |
| **Cline** | Custom abstraction | 40+ | ✅ | ✅ |
| **Kimi-CLI** | kosong (custom) | 4+ | ✅ | ✅ |
| **Penguin** | OpenRouter | 100+ | ✅ | ✅ |

**Recommendation:** Keep OpenRouter
- Already supports 100+ models
- Unified API
- Cost effective
- Penguin's differentiator

### 3.4 State Management

| Project | Approach | Persistence | Benefits |
|---------|----------|-------------|----------|
| **OpenCode** | File-based KV | JSON files | Simple, inspectable |
| **Cline** | Multi-tier cache | VSCode State API + debounced disk | Fast reads, efficient writes |
| **Kimi-CLI** | JSONL | Append-only JSONL | Crash-safe, human-readable |
| **Penguin** | React Context | In-memory (none) | None (lost on crash) |

**Recommendation:** Adopt JSONL pattern from Kimi
- Crash-safe (append-only)
- Human-readable (debugging)
- Supports checkpoints
- Simple implementation

### 3.5 Communication Protocol

| Project | Protocol | Benefits | Drawbacks |
|---------|----------|----------|-----------|
| **OpenCode** | HTTP + SSE | Standard, debuggable | More setup |
| **Cline** | gRPC + Protobuf | Type-safe, streaming, structured | Complex setup |
| **Kimi-CLI** | Wire protocol (events) | Simple, effective | Not standardized |
| **Penguin** | Direct function calls | None | No separation |

**Recommendation:** Adopt Kimi's wire protocol pattern
- Simple event-based communication
- Decouples agent from UI
- Easy to add subscribers (logging, telemetry)
- No gRPC complexity needed

---

## 4. Pattern Analysis

### 4.1 Communication Patterns

**OpenCode: HTTP + SSE**
```typescript
// Server-Sent Events for streaming
app.get("/event", async (c) => {
  return streamSSE(c, async (stream) => {
    Bus.subscribeAll((event) => {
      stream.writeSSE({ data: JSON.stringify(event) })
    })
  })
})
```

**Pros:**
- ✅ Standard protocol (HTTP)
- ✅ Easy to debug (curl, browser DevTools)
- ✅ Firewall-friendly
- ✅ Multiple clients can connect

**Cons:**
- ⚠️ More complex setup (need HTTP server)
- ⚠️ Network overhead (even for local)

---

**Cline: gRPC + Protobuf**
```protobuf
service TaskService {
  rpc SubmitTask(TaskRequest) returns (TaskResponse);
  rpc SubscribeToState(Empty) returns (stream ExtensionState);
}
```

**Pros:**
- ✅ Type-safe across boundary
- ✅ Efficient streaming
- ✅ Auto-generated code
- ✅ Schema evolution support

**Cons:**
- ⚠️ Complex setup (proto files, compilation)
- ⚠️ More dependencies
- ⚠️ Harder to debug

---

**Kimi-CLI: Wire Protocol**
```python
@dataclass
class MessagePart:
    text: str

@dataclass
class ToolCallBegin:
    tool_name: str

def wire_send(event: WireEvent):
    # Send to stdout (wire mode)
    print(json.dumps(asdict(event)))

    # Update live view (shell mode)
    live_view.handle_event(event)
```

**Pros:**
- ✅ Simple to implement
- ✅ No dependencies
- ✅ Flexible (multiple subscribers)
- ✅ Easy to debug (JSON events)

**Cons:**
- ⚠️ No type safety across boundary (but not needed in pure Python)

---

**Recommendation for Penguin:**

**If pure Python CLI:** Use Kimi's wire protocol
```python
# Simple, effective, no dependencies
async def agent_loop(wire_send: Callable):
    wire_send(StepBegin(step_no=1))
    for token in stream:
        wire_send(MessagePart(text=token))
    wire_send(StepEnd())
```

**If Python backend + TypeScript CLI:** Consider gRPC
```python
# Type-safe boundary, but more complex
service PenguinService {
  rpc SubmitTask(TaskRequest) returns (TaskResponse);
  rpc SubscribeToTokens(Empty) returns (stream Token);
}
```

**Decision:** Start with wire protocol, add gRPC if needed later.

### 4.2 State Management Patterns

**OpenCode: Instance-Scoped State**
```typescript
const state = Instance.state(
  async () => ({ data: await load() }),  // Init
  async (s) => await save(s.data)        // Cleanup
)

Instance.provide({ directory: "/project" }, async () => {
  const s = state()  // Isolated per directory
})
```

**Benefits:**
- ✅ Automatic state isolation per project
- ✅ Lazy initialization
- ✅ Automatic cleanup
- ✅ No global state

**Drawbacks:**
- ⚠️ More complex to understand
- ⚠️ Magic behavior (implicit context)

---

**Cline: Multi-Tier Cache**
```typescript
class StateManager {
  private cache: State = {}           // Fast reads
  private pending = new Set<string>() // Pending writes

  get(key): T { return this.cache[key] }

  set(key, value): void {
    this.cache[key] = value            // Update cache
    this.pending.add(key)              // Mark dirty
    this.schedule()                    // Schedule flush (500ms)
  }

  private async flush(): Promise<void> {
    // Write all pending to disk
    await fs.writeFile("state.json", ...)
  }
}
```

**Benefits:**
- ✅ Fast reads (in-memory)
- ✅ Efficient writes (batched)
- ✅ Reduced disk I/O

**Drawbacks:**
- ⚠️ More complex
- ⚠️ Risk of data loss if process killed before flush

---

**Kimi-CLI: JSONL Append-Only**
```python
# Append message to history
async with aiofiles.open("history.jsonl", "a") as f:
    await f.write(json.dumps(message.dict()) + "\n")

# Checkpoint marker
await f.write(json.dumps({"role": "_checkpoint", "id": 0}) + "\n")
```

**Benefits:**
- ✅ Crash-safe (append-only)
- ✅ Human-readable (JSON)
- ✅ Easy to debug
- ✅ Supports checkpoints
- ✅ Simple implementation

**Drawbacks:**
- ⚠️ Linear read time (but rarely a problem)
- ⚠️ File size grows (but compression helps)

---

**Recommendation for Penguin:** Adopt Kimi's JSONL pattern
```python
# Simple, crash-safe, human-readable
class Context:
    async def append_message(self, message: Message):
        async with aiofiles.open(self.history_file, "a") as f:
            await f.write(json.dumps(message.dict()) + "\n")

    async def checkpoint(self, checkpoint_id: int):
        async with aiofiles.open(self.history_file, "a") as f:
            await f.write(json.dumps({
                "role": "_checkpoint",
                "id": checkpoint_id,
                "timestamp": time.time()
            }) + "\n")
```

### 4.3 Tool System Patterns

**OpenCode: Tool.define Pattern**
```typescript
export const BashTool = Tool.define("bash", {
  description: DESCRIPTION,
  parameters: z.object({ command: z.string() }),
  async execute(params, ctx) {
    return { title: "Success", output: result }
  }
})
```

**Benefits:**
- ✅ Declarative
- ✅ Type-safe parameters (Zod)
- ✅ Context injection
- ✅ Clean API

---

**Cline: Tool Coordinator Pattern**
```typescript
class ToolExecutorCoordinator {
  private handlers = new Map<string, ToolHandler>()

  register(handler: ToolHandler) {
    for (const tool of handler.getSupportedTools()) {
      this.handlers.set(tool, handler)
    }
  }

  async execute(tool: string, params: any) {
    const handler = this.handlers.get(tool)
    return await handler.execute(tool, params)
  }
}
```

**Benefits:**
- ✅ Centralized registration
- ✅ Extensible (easy to add tools)
- ✅ Validation in one place
- ✅ Clear separation of concerns

---

**Kimi-CLI: CallableTool2 Pattern**
```python
class MyTool(CallableTool2[Params]):
    name = "MyTool"
    description = load_desc(Path(__file__).parent / "tool.md")

    class Params(BaseModel):
        arg1: str

    def __init__(self, approval: Approval, **kwargs):
        self._approval = approval

    async def __call__(self, params: Params) -> ToolReturnType:
        if not await self._approval.request(...):
            return ToolRejectedError()

        result = await self.do_work(params)
        return ToolOk(output=result)
```

**Benefits:**
- ✅ Dependency injection
- ✅ Pydantic validation
- ✅ Markdown descriptions
- ✅ Structured returns

---

**Recommendation for Penguin:** Adopt Coordinator + Kimi's pattern
```python
# Tool coordinator for registration
class ToolCoordinator:
    def __init__(self):
        self.tools: dict[str, Tool] = {}

    def register(self, tool: Tool):
        self.tools[tool.name] = tool

    async def execute(self, name: str, params: dict):
        tool = self.tools.get(name)
        if not tool:
            raise ValueError(f"Unknown tool: {name}")
        return await tool(params)

# Tool with dependency injection
class BashTool(CallableTool):
    name = "bash"

    class Params(BaseModel):
        command: str

    def __init__(self, approval: Approval, runtime: Runtime):
        self._approval = approval
        self._runtime = runtime

    async def __call__(self, params: Params):
        if not await self._approval.request("bash", params.command):
            return ToolRejected()

        result = await run_bash(params.command)
        return ToolOk(output=result)
```

### 4.4 UI/UX Patterns

**OpenCode: SolidJS Fine-Grained Reactivity**
```tsx
const [messages, setMessages] = createSignal<Message[]>([])

// Only updates when messages change
createEffect(() => {
  console.log("Messages updated:", messages().length)
})
```

**Benefits:**
- ✅ Efficient updates (fine-grained)
- ✅ No virtual DOM
- ✅ Fast rendering

**Drawbacks:**
- ⚠️ Custom TUI library (not reusable)
- ⚠️ Smaller ecosystem than React

---

**Cline: React Webview**
```tsx
<ChatView>
  <MessageList messages={messages} />
  <InputArea onSubmit={handleSubmit} />
</ChatView>
```

**Benefits:**
- ✅ Rich ecosystem
- ✅ Familiar to developers
- ✅ Radix UI for accessibility

**Drawbacks:**
- ⚠️ VSCode-specific (webview)
- ⚠️ Not usable in terminal

---

**Kimi-CLI: prompt-toolkit + rich**
```python
from prompt_toolkit import PromptSession
from rich.console import Console
from rich.live import Live

# Advanced input
session = PromptSession(
    multiline=True,
    completer=FileMentionCompleter(),
    key_bindings=custom_bindings
)
text = await session.prompt_async(">>> ")

# Rich output
console = Console()
with Live(console=console) as live:
    for update in stream:
        live.update(render(update))
```

**Benefits:**
- ✅ Mature, battle-tested
- ✅ Rich features (completion, keybindings)
- ✅ Excellent formatting (rich)
- ✅ Pure Python

**Drawbacks:**
- ⚠️ Python-only

---

**Recommendation for Penguin:** Migrate to prompt-toolkit + rich
```python
# Better than Ink for terminal UI
from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console
from rich.markdown import Markdown

# Custom keybindings
kb = KeyBindings()

@kb.add("c-x")
def switch_mode(event):
    toggle_agent_mode()

# Multi-line input with completion
session = PromptSession(
    multiline=True,
    key_bindings=kb,
    completer=merge_completers([
        CommandCompleter(),
        FileMentionCompleter()
    ])
)

# Rich output
console = Console()
console.print(Markdown(response))
```

---

## 5. Best Practices Synthesis

### 5.1 Type Safety

**Best Practice from All Three:**

```python
# Use Pydantic for validation
class ToolParams(BaseModel):
    command: str
    timeout: int = 120

# Use type hints everywhere
async def execute_tool(
    tool: Tool,
    params: ToolParams,
    context: Context
) -> ToolResult:
    ...

# Use pyright in strict mode
# pyproject.toml
[tool.pyright]
typeCheckingMode = "strict"
```

**Benefits:**
- Catch bugs at development time
- Better IDE support
- Self-documenting code
- Runtime validation (Pydantic)

### 5.2 Async/Await

**Best Practice from All Three:**

```python
# Use async throughout
async def agent_loop():
    async for token in stream:
        await process_token(token)

    results = await asyncio.gather(
        execute_tool_1(),
        execute_tool_2(),
        execute_tool_3()
    )

# Use aiofiles for file I/O
async with aiofiles.open("file.txt") as f:
    content = await f.read()

# Use tenacity for retries
@retry(
    retry=retry_if_exception(lambda e: isinstance(e, RetryableError)),
    wait=wait_exponential(max=5),
    stop=stop_after_attempt(10)
)
async def llm_call():
    return await api.call(...)
```

### 5.3 Error Handling

**Best Practice from All Three:**

```python
# Structured error types
class ToolResult:
    pass

class ToolOk(ToolResult):
    output: str
    message: str
    metadata: dict = {}

class ToolError(ToolResult):
    message: str
    brief: str

class ToolRejected(ToolResult):
    reason: str

# Use in tools
async def bash_tool(params):
    try:
        result = await run_command(params.command)
        return ToolOk(
            output=result.stdout,
            message=f"Exit code: {result.returncode}"
        )
    except TimeoutError:
        return ToolError(
            message="Command timed out",
            brief="Timeout"
        )

# Handle in agent
result = await tool.execute(params)
if isinstance(result, ToolOk):
    # Success
    await context.append_message(...)
elif isinstance(result, ToolError):
    # Error - retry or ask user
    ...
elif isinstance(result, ToolRejected):
    # User denied - tell LLM
    ...
```

### 5.4 Testing

**Best Practice from All Three:**

```python
# Mock LLM for deterministic tests
@pytest.fixture
async def mock_llm():
    llm = AsyncMock()
    llm.stream.return_value = AsyncIterator([
        {"type": "text", "text": "Hello"},
        {"type": "tool_call", "name": "bash", "args": {...}}
    ])
    return llm

# Fixture-based dependency injection
@pytest.fixture
def runtime(tmp_path):
    return Runtime(work_dir=tmp_path)

@pytest.fixture
def approval():
    approval = Mock()
    approval.request = AsyncMock(return_value=True)
    return approval

# Test with fixtures
@pytest.mark.asyncio
async def test_bash_tool(runtime, approval):
    tool = BashTool(approval=approval, runtime=runtime)
    result = await tool(BashParams(command="echo hello"))

    assert isinstance(result, ToolOk)
    assert "hello" in result.output
```

### 5.5 Configuration

**Best Practice from All Three:**

```python
# Hierarchical configuration
class Config(BaseModel):
    # Global settings
    default_model: str

    # Nested configurations
    models: dict[str, ModelConfig]
    providers: dict[str, ProviderConfig]

    # Feature flags
    features: FeatureFlags

    # Auto-approval rules
    auto_approval: list[AutoApprovalRule]

# Load with hierarchy
def load_config() -> Config:
    configs = [
        load_from("~/.penguin/config.json"),      # Global
        load_from(".penguin/config.json"),        # Project
        load_from_env("PENGUIN_CONFIG"),          # Env override
    ]

    return merge_configs(configs)

# Validate with Pydantic
config = Config.parse_file("config.json")
```

---

## 6. Recommendations for Penguin

### 6.1 Immediate Changes (Week 1-2)

**1. Fix Critical Bugs** ✅
- Session switching bug (useRef → useState)
- Duplicate WebSocket client (use single source)
- Add error boundaries

**2. Adopt Pure Python for CLI** ✅
- Remove TypeScript/Node.js dependency
- Use prompt-toolkit + rich instead of Ink
- Simplify architecture

**3. Implement Wire Protocol** ✅
```python
# Event-driven UI updates
@dataclass
class MessagePart:
    text: str

@dataclass
class ToolCallBegin:
    tool_name: str
    tool_input: dict

async def agent_loop(wire_send: Callable):
    wire_send(StepBegin(step_no=1))
    for token in stream:
        wire_send(MessagePart(text=token))
    wire_send(StepEnd())

# Multiple subscribers
subscribers = [
    ui_subscriber,
    log_subscriber,
    telemetry_subscriber
]

def wire_send(event):
    for subscriber in subscribers:
        subscriber(event)
```

**4. Adopt JSONL History** ✅
```python
# Append-only, crash-safe
class Context:
    async def append_message(self, message: Message):
        async with aiofiles.open(self.history_file, "a") as f:
            await f.write(json.dumps(message.dict()) + "\n")

    async def checkpoint(self, checkpoint_id: int):
        async with aiofiles.open(self.history_file, "a") as f:
            await f.write(json.dumps({
                "role": "_checkpoint",
                "id": checkpoint_id
            }) + "\n")
```

### 6.2 Short-Term Improvements (Week 3-4)

**1. Tool Coordinator Pattern** ✅
```python
class ToolCoordinator:
    def __init__(self):
        self.tools: dict[str, Tool] = {}

    def register(self, tool: Tool):
        self.tools[tool.name] = tool

    async def execute(self, name: str, params: dict):
        tool = self.tools.get(name)
        if not tool:
            raise ValueError(f"Unknown tool: {name}")

        # Validate params
        validated = tool.params.parse_obj(params)

        # Execute
        return await tool(validated)
```

**2. Approval Flow** ✅
```python
class Approval:
    async def request(
        self,
        tool_name: str,
        brief: str,
        full: str
    ) -> bool:
        # Check auto-approval
        if self.is_auto_approved(tool_name, brief):
            return True

        # Ask user
        response = await prompt_toolkit.prompt(
            f"Approve {tool_name}? [y/n/always/never]: "
        )

        if response == "always":
            self.add_auto_approval_rule(tool_name, brief)

        return response.lower() == "y"
```

**3. Dependency Injection** ✅
```python
# Tools declare dependencies
class BashTool:
    def __init__(self, approval: Approval, runtime: Runtime):
        self._approval = approval
        self._runtime = runtime

# Agent loader injects them
tool_deps = {
    Approval: approval_instance,
    Runtime: runtime_instance,
}

def instantiate_tool(tool_class: type):
    sig = inspect.signature(tool_class.__init__)
    kwargs = {}
    for param_name, param in sig.parameters.items():
        if param.annotation in tool_deps:
            kwargs[param_name] = tool_deps[param.annotation]
    return tool_class(**kwargs)
```

**4. Checkpoint System** ✅
```python
class Context:
    async def checkpoint(self):
        """Create checkpoint for rollback"""
        checkpoint_id = self._next_checkpoint_id
        self._next_checkpoint_id += 1

        async with aiofiles.open(self.history_file, "a") as f:
            await f.write(json.dumps({
                "role": "_checkpoint",
                "id": checkpoint_id,
                "timestamp": time.time()
            }) + "\n")

    async def revert_to(self, checkpoint_id: int):
        """Time-travel to checkpoint"""
        # Read history up to checkpoint
        lines = []
        async with aiofiles.open(self.history_file) as f:
            async for line in f:
                obj = json.loads(line)
                if obj.get("role") == "_checkpoint" and obj.get("id") == checkpoint_id:
                    lines.append(line)
                    break
                lines.append(line)

        # Backup old history
        backup = self.history_file.with_suffix(".jsonl.bak")
        shutil.copy(self.history_file, backup)

        # Write truncated history
        async with aiofiles.open(self.history_file, "w") as f:
            for line in lines:
                await f.write(line)
```

### 6.3 Medium-Term Enhancements (Month 2)

**1. MCP Integration** ✅
```python
# Model Context Protocol support
from fastmcp import FastMCP, Client

async def load_mcp_tools(config: Config) -> list[Tool]:
    tools = []

    for server_name, server_config in config.mcp_servers.items():
        client = Client(
            command=server_config.command,
            args=server_config.args
        )

        async with client:
            for mcp_tool in await client.list_tools():
                tools.append(MCPTool(mcp_tool, client))

    return tools
```

**2. Context Compaction** ✅
```python
async def compact_context(context: Context):
    """Summarize when context too long"""

    # Generate summary
    summary = await llm.call(
        system="Summarize the conversation so far",
        messages=context.history
    )

    # Revert to checkpoint 0
    await context.revert_to(0)

    # Add summary as new message
    await context.append_message(Message(
        role="user",
        content=[TextPart(text=summary)]
    ))
```

**3. YAML Agent Specs** ✅
```yaml
# agent.yaml
version: 1
agent:
  name: "Penguin Agent"
  system_prompt_path: "./system.md"
  tools:
    - penguin.tools.bash:BashTool
    - penguin.tools.file:ReadFileTool
    - penguin.tools.file:WriteFileTool
  subagents:
    research:
      path: "./agents/research/agent.yaml"
```

**4. Binary Distribution** ✅
```python
# pyproject.toml
[project.scripts]
penguin = "penguin_cli.__main__:main"

# PyInstaller spec
a = Analysis(
    ['penguin_cli/__main__.py'],
    datas=[('penguin_cli/agents', 'agents')],
)
exe = EXE(a, name='penguin', console=True)
```

### 6.4 Long-Term Vision (Month 3+)

**1. Multi-Agent Orchestration**
- Subagent delegation (like Kimi's Task tool)
- Agent roster management
- Message bus for inter-agent communication

**2. Plugin System**
- Custom tools from `.penguin/tools/`
- Custom agents from `.penguin/agents/`
- Plugin marketplace

**3. Web Interface** (Optional)
- React web UI alongside CLI
- Share architecture (same backend)
- Real-time collaboration

**4. VSCode Extension** (Optional)
- Like Cline, but powered by Penguin backend
- Deep IDE integration
- Diff views, code actions

---

## 7. Implementation Roadmap

### Phase 1: Foundation (Weeks 1-2)

**Goal:** Fix critical bugs, adopt core patterns

**Tasks:**
- [ ] Fix session switching bug
- [ ] Remove duplicate WebSocket client
- [ ] Add error boundaries
- [ ] Implement wire protocol
- [ ] Adopt JSONL history
- [ ] Write migration guide from Ink to prompt-toolkit

**Success Criteria:**
- No critical bugs
- Event-driven architecture working
- Conversation history persisted
- Pure Python CLI (optional: keep Ink for now)

---

### Phase 2: Refactoring (Weeks 3-4)

**Goal:** Improve architecture, add features

**Tasks:**
- [ ] Decompose ChatSession into smaller components
- [ ] Implement Tool Coordinator
- [ ] Add approval flow
- [ ] Implement dependency injection
- [ ] Add checkpoint system
- [ ] Increase test coverage to 60%

**Success Criteria:**
- No component >300 lines
- Extensible tool system
- Approval flow working
- Checkpoint/rollback functional
- 60% test coverage

---

### Phase 3: Enhancement (Weeks 5-8)

**Goal:** Add advanced features, polish UX

**Tasks:**
- [ ] MCP integration
- [ ] Context compaction
- [ ] YAML agent specs
- [ ] Time-travel debugging (D-Mail)
- [ ] File mention completion (@-mentions)
- [ ] Image paste support
- [ ] Binary distribution (PyInstaller)

**Success Criteria:**
- MCP tools working
- Context compaction automatic
- Agent specs configurable
- Time-travel functional
- Binary distribution working

---

### Phase 4: Polish (Weeks 9-12)

**Goal:** Production-ready, documentation, testing

**Tasks:**
- [ ] Comprehensive documentation
- [ ] Architecture diagrams
- [ ] User guide
- [ ] Contributing guide
- [ ] Increase test coverage to 80%
- [ ] Performance benchmarks
- [ ] Release v1.0

**Success Criteria:**
- 80% test coverage
- Complete documentation
- Performance benchmarked
- v1.0 release

---

## 8. Decision Matrix

### 8.1 Language & Runtime

| Option | Pros | Cons | Decision |
|--------|------|------|----------|
| **Pure Python** | - Code reuse<br>- Simple architecture<br>- Rich ecosystem | - Slightly slower startup | ✅ **ADOPT** |
| **TypeScript CLI** | - Fast startup<br>- Good async | - Separate from backend<br>- No compelling advantage | ❌ REJECT |
| **Go CLI** | - Fast<br>- Static binary | - No code reuse<br>- Overkill | ❌ REJECT |

**Verdict:** Pure Python (proven by Kimi-CLI)

---

### 8.2 UI Framework

| Option | Pros | Cons | Decision |
|--------|------|------|----------|
| **prompt-toolkit + rich** | - Mature<br>- Feature-rich<br>- Pure Python | - Python-only | ✅ **ADOPT** |
| **Ink (current)** | - React patterns<br>- Good | - Limited features<br>- Requires Node.js | ⚠️ MIGRATE FROM |
| **SolidJS TUI** | - Fast<br>- Fine-grained | - Custom library<br>- TypeScript-only | ❌ REJECT |

**Verdict:** Migrate from Ink to prompt-toolkit + rich

---

### 8.3 Communication Protocol

| Option | Pros | Cons | Decision |
|--------|------|------|----------|
| **Wire Protocol** | - Simple<br>- Flexible<br>- No dependencies | - No standardization | ✅ **ADOPT** |
| **gRPC + Protobuf** | - Type-safe<br>- Streaming | - Complex setup<br>- Overkill for pure Python | ⚠️ OPTIONAL (if needed later) |
| **HTTP + SSE** | - Standard<br>- Debuggable | - More complex<br>- Network overhead | ❌ REJECT (overkill) |

**Verdict:** Wire protocol (like Kimi-CLI)

---

### 8.4 State Management

| Option | Pros | Cons | Decision |
|--------|------|------|----------|
| **JSONL** | - Crash-safe<br>- Human-readable<br>- Checkpoints | - Linear reads | ✅ **ADOPT** |
| **Multi-tier cache** | - Fast reads<br>- Efficient writes | - Complex<br>- Risk of loss | ⚠️ OPTIONAL (if performance needed) |
| **File-based KV** | - Simple<br>- Inspectable | - Less structured | ❌ REJECT |

**Verdict:** JSONL (like Kimi-CLI)

---

### 8.5 Tool System

| Option | Pros | Cons | Decision |
|--------|------|------|----------|
| **Coordinator + DI** | - Extensible<br>- Clean | - More setup | ✅ **ADOPT** |
| **Direct registration** | - Simple | - Less extensible | ❌ CURRENT (replace) |

**Verdict:** Tool Coordinator with Dependency Injection

---

## Conclusion

### Key Takeaways

1. **Pure Python is Proven:** Kimi-CLI demonstrates Python is excellent for sophisticated CLIs
2. **Event-Driven Architecture Wins:** Wire protocol pattern is simple and effective
3. **JSONL is Best for History:** Crash-safe, human-readable, supports checkpoints
4. **Tool Coordinator Enables Extensibility:** Clean separation, easy to add tools
5. **prompt-toolkit > Ink:** More features, better performance, pure Python

### Immediate Action Items

1. ✅ **Adopt pure Python** for Penguin CLI
2. ✅ **Implement wire protocol** for event-driven UI
3. ✅ **Adopt JSONL** for conversation history
4. ✅ **Refactor tool system** with coordinator pattern
5. ✅ **Migrate from Ink** to prompt-toolkit + rich

### Final Recommendation

**Penguin should follow Kimi-CLI's architecture with selective adoption of patterns from OpenCode and Cline:**

```
Penguin v2 = Kimi-CLI base + OpenCode patterns + Cline polish
```

**Specifically:**
- **Base:** Kimi's pure Python architecture
- **Patterns:** OpenCode's tool system, Cline's type safety
- **UX:** Kimi's TUI + OpenCode's performance + Cline's polish

**Estimated Effort:** 8-12 weeks for full implementation

**Risk:** Low (proven patterns, incremental adoption)

**Benefit:** High (better architecture, easier maintenance, more features)

---

**Next Steps:**
1. Review this comparison with team
2. Prioritize adoption of patterns
3. Create detailed implementation plan for Phase 1
4. Begin incremental migration
5. Document decisions and progress