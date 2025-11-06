# OpenCode Architecture Analysis

**Project:** [OpenCode](https://github.com/opencodeco/opencode)
**Analysis Date:** 2025-11-05
**Purpose:** Reference architecture study for Penguin CLI improvements

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Technology Stack](#2-technology-stack)
3. [Architecture Overview](#3-architecture-overview)
4. [Core Systems](#4-core-systems)
5. [Agent Architecture](#5-agent-architecture)
6. [Tool System](#6-tool-system)
7. [UI/UX Implementation](#7-uiux-implementation)
8. [State Management](#8-state-management)
9. [Design Patterns](#9-design-patterns)
10. [Code Quality](#10-code-quality)
11. [Key Learnings for Penguin](#11-key-learnings-for-penguin)

---

## 1. Executive Summary

### What is OpenCode?

OpenCode is a **production-ready AI coding agent** with a sophisticated client/server architecture, built on modern TypeScript tooling. It's designed as a **local-first, privacy-focused** alternative to cloud-based AI coding assistants.

### Key Characteristics

- **Scale:** ~28,367 lines of TypeScript in main package
- **Architecture:** Client/Server with HTTP API and SSE streaming
- **Runtime:** Bun (not Node.js) for performance
- **UI Framework:** Custom TUI using SolidJS
- **State Management:** Instance-scoped with file-based persistence
- **LLM Integration:** Vercel AI SDK with 10+ provider support
- **Agent System:** Multi-agent with granular permissions

### Maturity Level

**Production-ready** with:
- ✅ Well-defined architecture patterns
- ✅ Comprehensive permission system
- ✅ Extensible plugin architecture
- ✅ Multiple deployment targets (CLI, desktop, web)
- ⚠️ Limited test coverage (early stage)
- ✅ Strong type safety (Zod + TypeScript)

---

## 2. Technology Stack

### Core Technologies

| Component | Technology | Why? |
|-----------|-----------|------|
| **Runtime** | Bun | Faster startup (3x), better DX, built-in SQLite |
| **UI Framework** | SolidJS | Fine-grained reactivity, better performance than React |
| **Terminal UI** | @opentui/solid | Custom library built on SolidJS for TUI |
| **HTTP Server** | Hono | Fast, edge-compatible, lightweight |
| **LLM Integration** | Vercel AI SDK | Provider abstraction, streaming, tool support |
| **Validation** | Zod v4 | Runtime type safety, JSON schema generation |
| **Monorepo** | Turbo | Fast builds, task caching |
| **Parser** | Tree-sitter | Bash AST parsing for permission checks |
| **Search** | ripgrep + fzf | Fast file/content search |

### Project Structure

```
opencode/
├── packages/
│   ├── opencode/          # Main CLI package (~28K LOC)
│   ├── ui/                # Reusable TUI components
│   ├── plugin/            # Plugin system API
│   ├── sdk/               # Client SDKs (JS, Python, Go)
│   ├── console/           # Web-based console
│   ├── desktop/           # Electron desktop app
│   ├── function/          # Serverless functions
│   └── script/            # Build/dev scripts
├── tools/                 # Monorepo tooling
├── .opencode/             # Example configurations
└── docs/                  # Documentation
```

### Dependencies

**Key Libraries:**
```json
{
  "ai": "^4.x",              // Vercel AI SDK
  "hono": "^4.x",            // HTTP server
  "solid-js": "^1.x",        // UI reactivity
  "zod": "^4.x",             // Validation
  "tree-sitter": "^0.21.x",  // Parsing
  "web-tree-sitter": "^0.24.x",
  "fast-glob": "^3.x",       // File globbing
  "fast-fuzzy": "^1.x"       // Fuzzy matching
}
```

---

## 3. Architecture Overview

### 3.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      OpenCode System                         │
│                                                              │
│  ┌──────────────┐                                           │
│  │  TUI Client  │ ← WebSocket/SSE                           │
│  │  (SolidJS)   │ ← HTTP API                                │
│  └──────────────┘                                           │
│         ↕                                                    │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Local HTTP Server (Hono)                 │   │
│  │  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐    │   │
│  │  │ Routes │→│ Session│→│Provider│→│ Tools  │    │   │
│  │  │  /api  │  │ Prompt │  │  LLM   │  │Registry│    │   │
│  │  └────────┘  └────────┘  └────────┘  └────────┘    │   │
│  │         ↕           ↕            ↕          ↕         │   │
│  │  ┌─────────────────────────────────────────────┐    │   │
│  │  │           Event Bus (Pub/Sub)               │    │   │
│  │  └─────────────────────────────────────────────┘    │   │
│  │         ↕           ↕            ↕          ↕         │   │
│  │  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐    │   │
│  │  │Storage │  │ Config │  │  LSP   │  │  MCP   │    │   │
│  │  │ Layer  │  │Hierarchy│  │ Client │  │ Client │    │   │
│  │  └────────┘  └────────┘  └────────┘  └────────┘    │   │
│  └──────────────────────────────────────────────────────┘   │
│         ↕                                                    │
│  ┌──────────────────────────────────────────────────────┐   │
│  │         File System Storage (~/.opencode/data/)       │   │
│  │  - Sessions, Messages, Parts                          │   │
│  │  - Configuration files                                │   │
│  │  - Logs, caches                                       │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                          ↕
              ┌───────────────────────┐
              │   LLM Providers       │
              │  (Anthropic, OpenAI,  │
              │   Bedrock, etc.)      │
              └───────────────────────┘
```

### 3.2 Client/Server Split

**Why Split?**
1. **Multiple clients:** TUI, desktop app, web console can all connect
2. **State isolation:** Server manages all stateful operations
3. **Real-time updates:** SSE streams updates to all connected clients
4. **Future-proof:** Mobile app, remote access, etc.

**Communication:**
- **HTTP REST:** CRUD operations on sessions, config, etc.
- **Server-Sent Events (SSE):** Real-time streaming updates
- **WebSocket:** Bidirectional for future features

### 3.3 Directory Structure Detail

```
packages/opencode/src/
├── agent/                    # Agent system (251 lines)
│   ├── agent.ts             # Agent definitions, permissions
│   └── types.ts             # Agent types
│
├── auth/                     # Authentication (169 lines)
│   └── auth.ts              # Provider auth management
│
├── bus/                      # Event bus (159 lines)
│   ├── bus.ts               # Type-safe pub/sub
│   └── index.ts
│
├── cli/                      # CLI implementation
│   ├── cmd/
│   │   ├── tui/             # Terminal UI app
│   │   │   ├── app.tsx      # Main app component
│   │   │   ├── route/       # Route components
│   │   │   │   ├── home.tsx # Session list
│   │   │   │   └── session.tsx # Chat view
│   │   │   ├── component/   # Reusable components
│   │   │   └── context/     # React-style providers
│   │   └── *.ts             # Other CLI commands
│   └── tui.ts               # TUI entry point
│
├── config/                   # Configuration (478 lines)
│   ├── config.ts            # Config loading/merging
│   └── types.ts             # Config schema (Zod)
│
├── file/                     # File operations
│   ├── ripgrep.ts           # Content search
│   ├── fzf.ts               # Fuzzy file search
│   └── watcher.ts           # File watching
│
├── lsp/                      # LSP integration (722 lines)
│   ├── lsp.ts               # LSP client
│   └── util.ts              # LSP utilities
│
├── mcp/                      # Model Context Protocol
│   ├── client.ts            # MCP client
│   └── server.ts            # MCP server
│
├── provider/                 # LLM providers (600+ lines)
│   ├── provider.ts          # Provider abstraction
│   ├── transform.ts         # Model transformations
│   └── types.ts             # Provider types
│
├── project/                  # Project management (341 lines)
│   ├── instance.ts          # Instance-scoped state
│   └── project.ts           # Project/worktree detection
│
├── session/                  # Session management
│   ├── index.ts             # Session CRUD (448 lines)
│   ├── prompt.ts            # Agentic loop (1,763 lines) ⭐
│   ├── message-v2.ts        # Message/Part types (600+ lines)
│   └── migration.ts         # Schema migrations
│
├── storage/                  # Persistence layer (237 lines)
│   └── storage.ts           # File-based KV store
│
├── tool/                     # Tool implementations
│   ├── registry.ts          # Tool registration
│   ├── bash.ts              # Shell execution (379 lines)
│   ├── edit.ts              # Smart file editing (641 lines) ⭐
│   ├── read.ts              # File reading
│   ├── write.ts             # File writing
│   ├── glob.ts              # Pattern matching
│   ├── grep.ts              # Content search
│   ├── ls.ts                # Directory listing
│   ├── webfetch.ts          # URL fetching
│   ├── task.ts              # Subagent delegation
│   ├── todo.ts              # Task management
│   ├── multiedit.ts         # Batch editing
│   └── patch.ts             # Git-style patching
│
├── util/                     # Utilities
│   ├── log.ts               # Structured logging
│   ├── signal.ts            # Process signals
│   ├── lock.ts              # File locking
│   ├── lazy.ts              # Lazy initialization
│   ├── context.ts           # Request context
│   └── error.ts             # Error handling
│
└── server/
    └── server.ts            # HTTP API (1,763 lines) ⭐
```

---

## 4. Core Systems

### 4.1 Session & Message Model

**Data Architecture:**

```typescript
// Session represents a conversation thread
interface Session {
  id: string;              // ULID (descending sort = newest first)
  projectID: string;       // Git root commit hash
  directory: string;       // Absolute path
  parentID?: string;       // For forked sessions
  title: string;
  version: string;         // Schema version
  time: {
    created: number;
    updated: number;
    compacting?: number;   // In-progress compaction
  };
  summary?: {
    additions: number;     // Total lines added
    deletions: number;     // Total lines deleted
    files: string[];       // Modified files
  };
  share?: {
    url: string;           // Shareable URL
  };
  revert?: {
    messageID: string;
    partID: string;
    snapshot: string[];    // File snapshots
    diff: string;          // Unified diff
  };
}

// Message = user or assistant turn
interface Message {
  id: string;
  sessionID: string;
  role: "user" | "assistant";
  parts: Part[];           // Array of content parts
  time: {
    created: number;
    updated: number;
  };
}

// Part = atomic content unit (discriminated union)
type Part =
  | TextPart           // Plain text
  | FilePart           // File attachment
  | ToolPart           // Tool call/result
  | ReasoningPart      // <thinking> content
  | StepStartPart      // Multi-step start
  | StepFinishPart     // Multi-step finish
  | RetryPart          // Retry metadata
  | SnapshotPart       // File snapshot
  | PatchPart          // File diff
  | AgentPart;         // Agent switch

interface TextPart {
  id: string;
  type: "text";
  text: string;
  stream?: boolean;      // Is streaming?
}

interface ToolPart {
  id: string;
  type: "tool";
  name: string;
  input: Record<string, any>;
  output?: {
    title: string;
    output: string;
    metadata?: Record<string, any>;
  };
  error?: {
    name: string;
    message: string;
  };
}
```

**Storage Layout:**

```
~/.opencode/data/storage/
├── session/
│   └── {projectID}/
│       └── {sessionID}.json         # Session metadata
├── message/
│   └── {sessionID}/
│       └── {messageID}.json         # Message with parts
├── part/
│   └── {messageID}/
│       └── {partID}.json            # Individual part
├── session_diff/
│   └── {sessionID}.json             # File diffs
└── share/
    └── {sessionID}.json             # Share metadata
```

**Why This Structure?**
- **Granular updates:** Parts can be updated independently
- **Streaming-friendly:** New parts/deltas appended incrementally
- **Inspectable:** Plain JSON files, easy to debug
- **Efficient:** Only load what's needed (pagination support)

### 4.2 Agentic Prompt Loop

**File:** `packages/opencode/src/session/prompt.ts` (1,763 lines)

**Core Loop Algorithm:**

```typescript
export async function prompt(input: string) {
  const msgs = await getMessages(sessionID);

  // Add user message
  msgs.push({ role: "user", content: input });

  // Multi-step agentic loop
  while (true) {
    // Call LLM with tools
    const result = await streamText({
      model,
      messages: msgs,
      tools: getTools(agent),
      maxSteps: Infinity,    // Unlimited steps
      temperature: agent.temperature ?? 0.0,
      topP: agent.topP ?? 0.95,

      // Streaming callbacks
      onChunk({ chunk }) {
        // Publish token to event bus
        Bus.publish(MessageV2.Event.PartUpdated, {
          sessionID,
          messageID,
          part: textPart,
          delta: chunk.text
        });
      },

      async onStepFinish({ stepType, toolCalls, toolResults }) {
        if (stepType === "tool") {
          // Execute tools in parallel
          for (const call of toolCalls) {
            await executeTool(call);
          }
        }
      }
    });

    // Check for completion
    if (result.finishReason === "stop") {
      break;  // Conversation complete
    }

    // Check for doom loop (same error 3x)
    if (isDoomLoop(msgs)) {
      throw new Error("Doom loop detected");
    }

    // Continue loop with tool results
  }
}
```

**Key Features:**

1. **Unlimited Steps:**
   ```typescript
   maxSteps: Infinity
   ```
   Agent can use as many tool calls as needed.

2. **Doom Loop Detection:**
   ```typescript
   // Stop if same error occurs 3 times
   const lastErrors = getLastNErrors(msgs, 3);
   if (lastErrors.every(e => e.message === lastErrors[0].message)) {
     throw new Error("Doom loop detected");
   }
   ```

3. **Retry with Exponential Backoff:**
   ```typescript
   for (let attempt = 0; attempt < 10; attempt++) {
     try {
       return await streamText(...);
     } catch (error) {
       if (attempt === 9) throw error;
       await sleep(1000 * Math.pow(2, attempt));
     }
   }
   ```

4. **Parallel Tool Execution:**
   ```typescript
   // AI SDK handles parallel tool calls automatically
   const results = await Promise.all(
     toolCalls.map(call => executeTool(call))
   );
   ```

5. **Live Streaming Updates:**
   ```typescript
   onChunk({ chunk }) {
     // Real-time token updates
     Bus.publish(MessageV2.Event.PartUpdated, { delta: chunk.text });
   }
   ```

### 4.3 Provider Abstraction

**File:** `packages/opencode/src/provider/provider.ts`

**Supported Providers (10+):**
- Anthropic (Claude)
- OpenAI (GPT-4, GPT-3.5)
- Amazon Bedrock (Claude, Titan)
- Google Vertex AI (Gemini)
- Ollama (local models)
- OpenRouter
- xAI (Grok)
- Groq
- Perplexity
- Together AI

**Provider Definition:**

```typescript
interface Provider {
  id: string;              // e.g., "anthropic"
  name: string;            // Display name
  apiKeyUrl?: string;      // Where to get API key
  models: Model[];
  defaultModel: string;
  supportsStreaming: boolean;
  supportsTools: boolean;
  supportsVision: boolean;
}

interface Model {
  id: string;              // e.g., "claude-sonnet-4"
  name: string;            // Display name
  contextWindow: number;
  maxOutput: number;
  supportsStreaming: boolean;
  supportsTools: boolean;
  supportsVision: boolean;
  inputPrice: number;      // Per 1M tokens
  outputPrice: number;
}
```

**Custom Loaders:**

```typescript
// providers with custom initialization
const CUSTOM_LOADERS: Record<string, CustomLoader> = {
  async anthropic() {
    return {
      autoload: false,
      options: {
        headers: {
          "anthropic-beta": "max-tokens-3-5-sonnet-2024-07-15"
        }
      }
    };
  },

  async "amazon-bedrock"() {
    // Dynamic AWS credential resolution
    const credentials = await resolveAWSCredentials();
    return {
      autoload: false,
      options: {
        credentials,
        region: process.env.AWS_REGION ?? "us-east-1"
      }
    };
  },

  async ollama() {
    // Fetch available local models
    const response = await fetch("http://localhost:11434/api/tags");
    const { models } = await response.json();
    return {
      models: models.map(m => ({
        id: m.name,
        name: m.name,
        // ...
      }))
    };
  }
};
```

**Model Transformations:**

Some providers require message transformation:

```typescript
// Example: Bedrock's converse API
function transformForBedrock(messages: CoreMessage[]): ConverseMessage[] {
  return messages.map(msg => {
    if (msg.role === "assistant" && msg.content.includes("<thinking>")) {
      // Extract thinking blocks
      const thinking = extractThinking(msg.content);
      const content = removeThinking(msg.content);
      return {
        role: "assistant",
        content: [
          { type: "thinkingBlock", content: thinking },
          { type: "text", text: content }
        ]
      };
    }
    return msg;
  });
}
```

### 4.4 Event Bus

**File:** `packages/opencode/src/bus/bus.ts`

**Type-Safe Pub/Sub:**

```typescript
// Define event
const SessionUpdated = Bus.event(
  "session.updated",
  z.object({
    info: SessionInfoSchema
  })
);

// Publish
Bus.publish(SessionUpdated, {
  info: session
});

// Subscribe
const unsub = Bus.subscribe(SessionUpdated, (event) => {
  console.log("Session updated:", event.properties.info);
});

// Cleanup
unsub();
```

**Built-in Events:**

```typescript
// Message events
MessageV2.Event.PartUpdated
MessageV2.Event.PartFinalized
MessageV2.Event.MessageCreated

// Session events
Session.Event.Updated
Session.Event.Created
Session.Event.Deleted

// Tool events
Tool.Event.PermissionRequested
Tool.Event.PermissionGranted
Tool.Event.Executed

// LSP events
LSP.Event.DiagnosticsUpdated
```

**Event Streaming to Clients:**

```typescript
// Server endpoint streams events via SSE
app.get("/event", async (c) => {
  return streamSSE(c, async (stream) => {
    const unsub = Bus.subscribeAll(async (event) => {
      await stream.writeSSE({
        event: event.type,
        data: JSON.stringify(event)
      });
    });

    await stream.sleep(1000 * 60 * 60);  // Keep alive 1h
    unsub();
  });
});
```

---

## 5. Agent Architecture

### 5.1 Agent System Overview

**File:** `packages/opencode/src/agent/agent.ts` (251 lines)

**Philosophy:** Agents are **pre-configured personas** with specific capabilities and permissions.

**Built-in Agents:**

```typescript
const BUILT_IN_AGENTS = {
  build: {
    name: "build",
    description: "Primary coding agent with full capabilities",
    mode: "primary",
    tools: {
      bash: true,
      edit: true,
      read: true,
      write: true,
      glob: true,
      grep: true,
      ls: true,
      webfetch: true,
      task: true,
      todowrite: true,
      todoread: true,
      multiedit: true,
      patch: true
    },
    permission: {
      edit: "allow",
      bash: {
        "*": "allow"  // Allow all commands
      }
    }
  },

  general: {
    name: "general",
    description: "Research and search agent (subagent only)",
    mode: "subagent",
    tools: {
      bash: false,      // No shell access
      edit: false,      // No file editing
      read: true,
      glob: true,
      grep: true,
      ls: true,
      webfetch: true,
      task: false       // Cannot spawn subagents
    },
    permission: {
      edit: "deny"
    }
  },

  plan: {
    name: "plan",
    description: "Read-only planning agent",
    mode: "all",
    tools: {
      bash: true,       // Limited bash
      edit: false,
      read: true,
      // ...
    },
    permission: {
      edit: "deny",
      bash: {
        "cat *": "allow",
        "ls *": "allow",
        "find *": "allow",
        "*": "deny"      // Deny everything else
      }
    }
  }
};
```

### 5.2 Permission System

**Permission Types:**

```typescript
type Permission = "allow" | "deny" | "ask";

interface AgentPermission {
  edit: Permission;
  bash: Record<string, Permission>;  // Wildcard patterns
  webfetch?: Permission;
}
```

**Bash Permission Matching:**

```typescript
// Uses tree-sitter to parse bash AST
const ast = await parseBash(command);
const commands = extractCommands(ast);  // ["rm", "-rf", "/"]

// Match against permission patterns
for (const [pattern, permission] of Object.entries(agent.permission.bash)) {
  if (minimatch(command, pattern)) {
    return permission;
  }
}

return "deny";  // Default deny
```

**Permission Request Flow:**

```
Agent wants to execute: rm -rf node_modules
    ↓
Check permission: agent.permission.bash["rm *"]
    ↓
Result: "ask"
    ↓
Publish event: Tool.Event.PermissionRequested
    ↓
TUI shows modal: "Allow agent to run 'rm -rf node_modules'?"
    ↓
User clicks "Allow" or "Deny"
    ↓
Publish event: Tool.Event.PermissionGranted/Denied
    ↓
Execute or abort
```

### 5.3 Custom Agents

**Definition via Markdown:**

```markdown
<!-- .opencode/agent/my-agent.md -->

---
name: my-agent
description: Custom agent for specific task
mode: primary
model:
  providerID: anthropic
  modelID: claude-sonnet-4
temperature: 0.2
---

You are a specialized agent for [specific task].

Your responsibilities:
- Task 1
- Task 2

Guidelines:
- Guideline 1
- Guideline 2
```

**Frontmatter + Body:**
- **Frontmatter:** Agent configuration (YAML)
- **Body:** Custom system prompt (appended to base prompt)

**Tool Override:**

```yaml
tools:
  bash: true
  edit: true
  webfetch: false  # Disable webfetch

permission:
  edit: ask
  bash:
    "npm *": allow
    "git *": allow
    "*": deny
```

### 5.4 Subagent Delegation

**Tool:** `task` (subagent spawning)

```typescript
// Agent can delegate to subagent
await task({
  agent: "general",  // Spawn "general" agent
  prompt: "Research the latest trends in AI"
});
```

**Execution Flow:**

```
Main Agent (build)
    ↓ task({ agent: "general", prompt: "..." })
Spawn Subagent (general)
    ↓
Subagent runs with own permissions
    ↓
Subagent completes, returns result
    ↓
Main Agent continues with result
```

**Restrictions:**
- Subagents cannot spawn their own subagents (prevents infinite recursion)
- Subagents inherit limited tool access
- Separate session tracking

---

## 6. Tool System

### 6.1 Tool Architecture

**File:** `packages/opencode/src/tool/registry.ts`

**Tool Definition Pattern:**

```typescript
export const MyTool = Tool.define("my_tool", {
  description: `Tool description for LLM`,

  parameters: z.object({
    param1: z.string().describe("Parameter description"),
    param2: z.number().optional()
  }),

  async execute(params, ctx) {
    // ctx provides:
    // - sessionID, messageID, callID
    // - agent name
    // - abort signal
    // - metadata() callback

    // Send live updates
    ctx.metadata({ progress: 0.5 });

    // Do work
    const result = await doWork(params);

    return {
      title: "Success",
      output: result,
      metadata: { /* custom data */ }
    };
  }
});

// Register
ToolRegistry.register(MyTool);
```

### 6.2 Built-in Tools

#### 1. **bash** - Shell Execution

**File:** `tool/bash.ts` (379 lines)

**Features:**
- Tree-sitter AST parsing for permission checks
- Sandbox mode (restricted commands)
- Timeout support
- Abort signal handling
- Live stdout/stderr streaming

**Permission Checking:**

```typescript
// Parse command into AST
const ast = await parseBash(command);
const commands = extractCommands(ast);  // ["git", "add", "."]

// Check each command
for (const cmd of commands) {
  const permission = checkPermission(agent, cmd);
  if (permission === "deny") {
    throw new Error(`Permission denied: ${cmd}`);
  }
  if (permission === "ask") {
    await requestPermission(cmd);
  }
}

// Execute
const proc = Bun.spawn(["bash", "-c", command], {
  cwd,
  env,
  signal: ctx.abort
});
```

#### 2. **edit** - Smart File Editing

**File:** `tool/edit.ts` (641 lines) ⭐

**The Most Sophisticated Tool**

**Problem:** LLMs are bad at exact string matching. They:
- Add/remove whitespace
- Change indentation
- Include line numbers
- Truncate long lines

**Solution:** 9 different matching strategies, tried in order:

```typescript
const REPLACERS = [
  exactReplacer,          // Exact match
  lineTrimReplacer,       // Trim line endings
  blockAnchorReplacer,    // Match first/last line of block
  whitespaceReplacer,     // Normalize whitespace
  indentFlexReplacer,     // Flexible indentation
  escapeReplacer,         // Normalize escapes
  boundaryTrimReplacer,   // Trim boundaries
  contextReplacer,        // Similarity-based (Levenshtein)
  multiOccurrenceReplacer // Multiple matches
];

// Try each replacer
for (const replacer of REPLACERS) {
  const result = replacer(content, oldString, newString);
  if (result.success) {
    return result;
  }
}

throw new Error("Could not find exact match");
```

**Context Replacer** (most powerful):

```typescript
// Uses Levenshtein distance for fuzzy matching
const SIMILARITY_THRESHOLD = 0.85;

function contextReplacer(content, old, new) {
  const lines = content.split("\n");
  const oldLines = old.split("\n");

  // Find best matching block
  let bestMatch = { similarity: 0, index: -1 };

  for (let i = 0; i < lines.length - oldLines.length; i++) {
    const block = lines.slice(i, i + oldLines.length).join("\n");
    const similarity = levenshtein(block, old) / Math.max(block.length, old.length);

    if (similarity > bestMatch.similarity) {
      bestMatch = { similarity, index: i };
    }
  }

  if (bestMatch.similarity >= SIMILARITY_THRESHOLD) {
    // Replace block
    lines.splice(bestMatch.index, oldLines.length, ...new.split("\n"));
    return { success: true, content: lines.join("\n") };
  }

  return { success: false };
}
```

**LSP Integration:**

```typescript
// After edit, check for errors
const diagnostics = await LSP.getDiagnostics(filePath);

if (diagnostics.errors.length > 0) {
  // Include errors in tool output
  return {
    title: "Edit completed with errors",
    output: formatDiagnostics(diagnostics),
    metadata: { diagnostics }
  };
}
```

**Fuzzy File Matching:**

```typescript
// User can provide partial path
edit({
  file_path: "session.tsx",  // Could match multiple files
  // ...
})

// Tool uses fzf to find best match
const matches = await fzf(cwd, "session.tsx");
if (matches.length > 1) {
  // Ambiguous - ask user
  await requestClarification(matches);
}
```

#### 3. **read** - File Reading

**Features:**
- Offset/limit for large files
- Binary detection (skip binary files)
- Encoding detection
- Line number annotations

#### 4. **write** - File Writing

**Features:**
- Creates directories automatically
- Atomic write (write to temp, then rename)
- Backup on overwrite
- Permission preservation

#### 5. **glob** - Pattern Matching

**Features:**
- Uses `fast-glob` for speed
- Respects `.gitignore`
- Supports multiple patterns
- Returns relative paths

#### 6. **grep** - Content Search

**Features:**
- Uses `ripgrep` (fast)
- Context lines (before/after)
- Line numbers
- File type filtering
- Regex support

#### 7. **webfetch** - URL Fetching

**Features:**
- HTML-to-markdown conversion
- PDF text extraction
- Image OCR (via external service)
- Timeout/retry
- User-agent spoofing

#### 8. **task** - Subagent Delegation

See [Agent Architecture](#5-agent-architecture).

#### 9. **todowrite/todoread** - Task Management

**Features:**
- Persistent TODO list per session
- Status tracking (pending, in_progress, completed)
- Markdown formatting
- Progress visualization

#### 10. **multiedit** - Batch Editing

**Features:**
- Multiple file edits in one call
- Transactional (all-or-nothing)
- Uses same smart matching as `edit`
- Atomic commit

#### 11. **patch** - Git-Style Patching

**Features:**
- Apply unified diffs
- Fuzzy matching (handles offset changes)
- Dry-run mode
- Revert support

#### 12. **ls** - Directory Listing

**Features:**
- Tree view
- File size, permissions
- Gitignore filtering
- Depth limiting

### 6.3 Custom Tools

**Loading:**

```typescript
// Load from .opencode/tool/*.{js,ts}
const tools = await glob(".opencode/tool/*.{js,ts}");

for (const file of tools) {
  const module = await import(file);
  if (module.default) {
    ToolRegistry.register(module.default);
  }
}
```

**Example Custom Tool:**

```typescript
// .opencode/tool/deploy.ts
import { Tool } from "opencode/tool";
import { z } from "zod";

export default Tool.define("deploy", {
  description: "Deploy application to production",

  parameters: z.object({
    environment: z.enum(["staging", "production"]),
    message: z.string()
  }),

  async execute({ environment, message }, ctx) {
    // Custom deployment logic
    const result = await deployApp(environment, message);

    return {
      title: `Deployed to ${environment}`,
      output: result.logs,
      metadata: {
        url: result.url,
        version: result.version
      }
    };
  }
});
```

---

## 7. UI/UX Implementation

### 7.1 Terminal UI Framework

**Custom Framework:** `@opentui/solid`

**Why Custom?**
- Ink (React-based) is too slow for complex TUIs
- Better control over rendering
- SolidJS fine-grained reactivity is faster
- Tight integration with OpenCode architecture

**Rendering Pipeline:**

```
SolidJS Component Tree
    ↓
Virtual DOM (custom)
    ↓
Diffing Algorithm
    ↓
ANSI Escape Sequences
    ↓
Terminal Output (stdout)
```

**Performance:**
- Target: 60 FPS
- Debounced renders (16ms)
- Incremental updates only
- Static optimization for unchanged sections

### 7.2 Component Architecture

**Main App Structure:**

```tsx
// cli/cmd/tui/app.tsx
<ExitProvider>           {/* Handle Ctrl+C, exit codes */}
  <KVProvider>           {/* Persistent key-value storage */}
    <ToastProvider>      {/* Notifications */}
      <RouteProvider>    {/* Routing (home/session) */}
        <SDKProvider>    {/* OpenCode SDK client */}
          <SyncProvider> {/* Sync state with server */}
            <ThemeProvider>
              <LocalProvider>
                <KeybindProvider>
                  <DialogProvider>
                    <CommandProvider>
                      <PromptHistoryProvider>
                        <App />
```

**Context Providers:**

| Provider | Purpose |
|----------|---------|
| ExitProvider | Handle process exit, cleanup |
| KVProvider | Persistent storage (terminal state) |
| ToastProvider | Toast notifications |
| RouteProvider | Client-side routing |
| SDKProvider | OpenCode client SDK |
| SyncProvider | Sync sessions/messages with server |
| ThemeProvider | Theme switching (light/dark) |
| LocalProvider | Local-only state (UI state) |
| KeybindProvider | Configurable keybindings |
| DialogProvider | Modal dialogs |
| CommandProvider | Command palette |
| PromptHistoryProvider | Input history (up/down arrows) |

### 7.3 Routes

**Home Route** (`route/home.tsx`):

```tsx
// Session list view
<Box flexDirection="column">
  <Header />
  <SessionList>
    {sessions.map(session => (
      <SessionItem
        key={session.id}
        session={session}
        onClick={() => navigate(`/session/${session.id}`)}
      />
    ))}
  </SessionList>
  <Footer>
    <Text>Press N to create new session</Text>
  </Footer>
</Box>
```

**Session Route** (`route/session.tsx`):

```tsx
// Chat view
<Box flexDirection="column">
  <Header>
    <SessionTitle>{session.title}</SessionTitle>
    <ModelBadge>{session.model}</ModelBadge>
    <AgentBadge>{session.agent}</AgentBadge>
  </Header>

  <MessageList>
    {messages.map(msg => (
      <Message key={msg.id} message={msg} />
    ))}
  </MessageList>

  <InputBar
    onSubmit={handleSubmit}
    placeholder="Message OpenCode..."
  />
</Box>
```

### 7.4 Key Components

**Message Rendering:**

```tsx
// component/message.tsx
function Message({ message }: Props) {
  return (
    <Box flexDirection="column">
      <Text color={message.role === "user" ? "blue" : "green"}>
        {message.role === "user" ? "You" : "OpenCode"}
      </Text>

      {message.parts.map(part => (
        <Show when={part.type === "text"}>
          <Markdown>{part.text}</Markdown>
        </Show>

        <Show when={part.type === "tool"}>
          <ToolExecution tool={part} />
        </Show>

        <Show when={part.type === "reasoning"}>
          <Collapsible title="Reasoning">
            <Text dimmed>{part.text}</Text>
          </Collapsible>
        </Show>
      ))}
    </Box>
  );
}
```

**Tool Execution Display:**

```tsx
function ToolExecution({ tool }: Props) {
  return (
    <Box borderStyle="round" padding={1}>
      <Text bold>🔧 {tool.name}</Text>

      <Collapsible title="Input">
        <Code>{JSON.stringify(tool.input, null, 2)}</Code>
      </Collapsible>

      <Show when={tool.output}>
        <Collapsible title="Output" defaultOpen>
          <Text>{tool.output.output}</Text>
        </Collapsible>
      </Show>

      <Show when={tool.error}>
        <Text color="red">Error: {tool.error.message}</Text>
      </Show>
    </Box>
  );
}
```

### 7.5 Keyboard Input

**Kitty Protocol Support:**

```typescript
// Enable Kitty keyboard protocol for enhanced keys
process.stdout.write("\x1b[>1u");

// Cleanup on exit
process.on("exit", () => {
  process.stdout.write("\x1b[<u");
});
```

**Benefits:**
- Distinguish `Ctrl+I` from `Tab`
- Support `Ctrl+Shift+Key` combinations
- Modifier + function keys
- More accurate input handling

**Keybindings:**

```typescript
// Default keybinds (configurable)
const KEYBINDS = {
  "ctrl+c": "exit",
  "ctrl+k": "command_palette",
  "ctrl+s": "switch_session",
  "ctrl+m": "switch_model",
  "ctrl+a": "switch_agent",
  "ctrl+l": "clear_screen",
  "ctrl+r": "reload",
  "esc": "close_dialog",
  "enter": "submit",
  "up": "history_prev",
  "down": "history_next",
  "ctrl+up": "scroll_up",
  "ctrl+down": "scroll_down",
  "tab": "autocomplete",
  "shift+tab": "autocomplete_prev"
};
```

### 7.6 Dialogs

**Command Palette:**

```tsx
<Dialog title="Command Palette">
  <Input
    placeholder="Search commands..."
    value={search}
    onChange={setSearch}
  />

  <List>
    {filteredCommands.map(cmd => (
      <ListItem
        key={cmd.id}
        label={cmd.label}
        description={cmd.description}
        onSelect={() => cmd.execute()}
      />
    ))}
  </List>
</Dialog>
```

**Session Picker:**

```tsx
<Dialog title="Switch Session">
  <List>
    {sessions.map(session => (
      <ListItem
        key={session.id}
        label={session.title}
        description={session.directory}
        metadata={formatDate(session.time.updated)}
        onSelect={() => switchSession(session.id)}
      />
    ))}
  </List>
</Dialog>
```

---

## 8. State Management

### 8.1 Instance-Scoped State

**Pattern:** Each project directory gets isolated state

```typescript
// Define state factory
const myState = Instance.state(
  // Initialize (runs once per instance)
  async () => {
    const data = await loadData();
    return { data };
  },

  // Cleanup (runs on dispose)
  async (state) => {
    await saveData(state.data);
  }
);

// Usage in instance context
Instance.provide({
  directory: "/path/to/project",
  async fn() {
    const state = myState();  // Always same instance
    state.data.foo = "bar";
  }
});
```

**Benefits:**
- Automatic state isolation per project
- Lazy initialization
- Automatic cleanup
- No global state pollution

### 8.2 Configuration Hierarchy

**Loading Order:**

```
1. Global config (~/.opencode/opencode.json)
2. Project configs (walk up from cwd)
   - /project/.opencode/opencode.json
   - /project/opencode.json
3. Environment override (OPENCODE_CONFIG)
4. Content override (OPENCODE_CONFIG_CONTENT)
5. Well-known configs (if authenticated)
```

**Merging Strategy:**

```typescript
function mergeConfigs(configs: Config[]): Config {
  return configs.reduce((acc, config) => {
    return mergeDeep(acc, config);
  }, {});
}
```

**Example:**

```json
// ~/.opencode/opencode.json (global)
{
  "provider": {
    "id": "anthropic",
    "apiKey": "sk-..."
  },
  "agent": "build"
}

// /project/.opencode/opencode.json (project)
{
  "agent": "my-custom-agent",
  "tools": {
    "bash": {
      "npm *": "allow"
    }
  }
}

// Result: merge deep
{
  "provider": {
    "id": "anthropic",
    "apiKey": "sk-..."
  },
  "agent": "my-custom-agent",  // Override
  "tools": {
    "bash": {
      "npm *": "allow"
    }
  }
}
```

### 8.3 Storage Layer

**File:** `packages/opencode/src/storage/storage.ts`

**API:**

```typescript
// Write
await Storage.write(["session", projectID, sessionID], sessionData);

// Read
const session = await Storage.read<Session>(["session", projectID, sessionID]);

// Update (atomic)
await Storage.update<Session>(["session", projectID, sessionID], (draft) => {
  draft.title = "New title";
  draft.time.updated = Date.now();
});

// List
const sessions = await Storage.list<Session>(["session", projectID]);

// Delete
await Storage.delete(["session", projectID, sessionID]);
```

**Implementation:**

```typescript
// Path-based storage
function getPath(key: string[]): string {
  return path.join(
    Config.dataDir,      // ~/.opencode/data/
    "storage",
    ...key
  ) + ".json";
}

async function write(key: string[], data: unknown): Promise<void> {
  const filePath = getPath(key);
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, JSON.stringify(data, null, 2));
}
```

**Benefits:**
- Simple, inspectable (plain JSON files)
- No database dependency
- Easy to backup/restore
- Git-friendly (can commit .opencode/data/)

### 8.4 SDK Client

**File:** `packages/sdk/src/client.ts`

**Purpose:** Client library for connecting to OpenCode server

**API:**

```typescript
const client = new OpenCodeClient({
  url: "http://localhost:3000"
});

// Session operations
const sessions = await client.sessions.list();
const session = await client.sessions.get(sessionId);
await client.sessions.create({ directory: "/path" });

// Message operations
const messages = await client.messages.list(sessionId);
await client.messages.create(sessionId, {
  role: "user",
  content: "Hello"
});

// Streaming
client.stream(sessionId, async (event) => {
  if (event.type === "message.part.updated") {
    console.log(event.data.delta);
  }
});

// Config operations
const config = await client.config.get();
await client.config.update({ agent: "build" });
```

**TUI Integration:**

```tsx
// SDKProvider wraps entire app
<SDKProvider url="http://localhost:3000">
  <App />
</SDKProvider>

// Components use SDK via context
function MyComponent() {
  const sdk = useSDK();
  const [sessions, setSessions] = createSignal([]);

  onMount(async () => {
    const list = await sdk.sessions.list();
    setSessions(list);
  });

  return <SessionList sessions={sessions()} />;
}
```

---

## 9. Design Patterns

### 9.1 Instance-Scoped Context

**Pattern:** Request-scoped state without DI container

```typescript
// Define context
const MyContext = Context.create<MyData>();

// Provide value
MyContext.provide(myData, async () => {
  // All code in this closure has access to myData
  const data = MyContext.use();  // Returns myData
});

// Nested provision
MyContext.provide(outer, async () => {
  // data === outer

  MyContext.provide(inner, async () => {
    // data === inner (shadowing)
  });

  // data === outer again
});
```

**Benefits:**
- No globals
- No prop drilling
- Type-safe
- Automatic cleanup

### 9.2 Lazy Initialization

**Pattern:** One-time async init with caching

```typescript
const parser = lazy(async () => {
  const { Parser } = await import("web-tree-sitter");
  await Parser.init();
  const parser = new Parser();
  const lang = await Parser.Language.load("tree-sitter-bash.wasm");
  parser.setLanguage(lang);
  return parser;
});

// First call initializes
const p1 = await parser();  // Load & init

// Subsequent calls return cached
const p2 = await parser();  // Returns cached
```

### 9.3 Event-Driven Architecture

**Pattern:** Decouple producers from consumers

```typescript
// Producer doesn't know about consumers
Bus.publish(SessionUpdated, { info: session });

// Multiple consumers
Bus.subscribe(SessionUpdated, async (event) => {
  await syncToCloud(event.properties.info);
});

Bus.subscribe(SessionUpdated, async (event) => {
  await updateUI(event.properties.info);
});

Bus.subscribe(SessionUpdated, async (event) => {
  await logAnalytics(event.properties.info);
});
```

### 9.4 Provider Abstraction

**Pattern:** Unified interface across providers

```typescript
// Provider-agnostic code
async function generateText(prompt: string): Promise<string> {
  const provider = Config.provider;
  const model = getModel(provider.id, provider.model);

  const result = await streamText({
    model,  // Works with any provider
    messages: [{ role: "user", content: prompt }]
  });

  return result.text;
}
```

### 9.5 Tool Composition

**Pattern:** Decorators for cross-cutting concerns

```typescript
// Base tool
const BaseTool = Tool.define("edit", { ... });

// Add permission checking
const PermissionTool = withPermission(BaseTool);

// Add LSP diagnostics
const LSPTool = withLSP(PermissionTool);

// Add file watching
const WatchedTool = withWatcher(LSPTool);

// Register composed tool
ToolRegistry.register(WatchedTool);
```

### 9.6 Type-Safe Events

**Pattern:** Zod schemas for runtime validation

```typescript
// Define event with schema
const MyEvent = Bus.event(
  "my.event",
  z.object({
    id: z.string(),
    data: z.number()
  })
);

// Compile-time type inference
Bus.publish(MyEvent, {
  id: "123",
  data: 456  // TypeScript knows this is a number
});

// Runtime validation
Bus.subscribe(MyEvent, (event) => {
  // event.properties is validated at runtime
  console.log(event.properties.data + 1);  // Safe
});
```

### 9.7 Incremental File Operations

**Pattern:** Stream large files, avoid loading entire file

```typescript
// Read file in chunks
async function* readFileChunks(path: string): AsyncGenerator<string> {
  const file = await open(path);

  for await (const line of file.readLines()) {
    yield line;
  }
}

// Usage
for await (const line of readFileChunks("large-file.txt")) {
  process(line);
}
```

---

## 10. Code Quality

### 10.1 Type Safety

**Score: 9/10** ✅

**Strengths:**
- 100% TypeScript with strict mode
- Zod schemas for all data structures
- Runtime validation on boundaries
- Type inference from Zod (`z.infer<typeof Schema>`)
- Discriminated unions for events/messages

**Example:**

```typescript
// Schema definition
const SessionSchema = z.object({
  id: z.string(),
  projectID: z.string(),
  directory: z.string(),
  title: z.string(),
  time: z.object({
    created: z.number(),
    updated: z.number()
  })
});

// Type inference
type Session = z.infer<typeof SessionSchema>;  // Full TypeScript type

// Runtime validation
const session = SessionSchema.parse(data);  // Throws if invalid
```

### 10.2 Testing

**Score: 4/10** ⚠️

**Test Files:**
- `packages/opencode/test/` directory exists
- Limited coverage (appears to be early stage)
- Uses Bun test runner

**Gaps:**
- No integration tests
- No E2E tests
- Limited unit tests
- No performance benchmarks

**Recommendation:** Increase test coverage to 60%+

### 10.3 Documentation

**Score: 8/10** ✅

**Strengths:**
- Inline JSDoc comments
- Architecture docs (`AGENTS.md`, `CONTRIBUTING.md`)
- Tool descriptions in separate `.txt` files
- OpenAPI spec generation
- Code is self-documenting (good naming)

**Gaps:**
- No comprehensive architecture doc (addressed by this analysis!)
- Limited inline examples
- Few diagrams

### 10.4 Error Handling

**Score: 8/10** ✅

**Patterns:**

1. **Custom Error Types:**
   ```typescript
   class PermissionDeniedError extends NamedError {
     name = "PermissionDeniedError";
   }

   throw new PermissionDeniedError("Cannot execute command");
   ```

2. **Retry Logic:**
   ```typescript
   async function withRetry<T>(fn: () => Promise<T>, maxRetries = 10): Promise<T> {
     for (let i = 0; i < maxRetries; i++) {
       try {
         return await fn();
       } catch (error) {
         if (i === maxRetries - 1) throw error;
         await sleep(1000 * Math.pow(2, i));
       }
     }
   }
   ```

3. **Graceful Degradation:**
   ```typescript
   // LSP failures don't block tool execution
   try {
     const diagnostics = await LSP.getDiagnostics(file);
     return { ...result, diagnostics };
   } catch (error) {
     return result;  // Continue without diagnostics
   }
   ```

### 10.5 Logging

**Score: 7/10** ✅

**Implementation:**

```typescript
// Structured logging
Log.info("session.created", {
  sessionID,
  projectID,
  directory
});

Log.error("tool.failed", {
  tool: "bash",
  error: error.message,
  command
});

// Service-based organization
const log = Log.service("session");
log.debug("Prompt starting", { sessionID });
```

**File Output:**
```
~/.opencode/data/logs/
├── 2025-11-05.log
├── 2025-11-04.log
└── ...
```

---

## 11. Key Learnings for Penguin

### 11.1 Architecture Patterns to Adopt

#### 1. Client/Server Split

**OpenCode:**
```
TUI (client) ←→ HTTP Server ←→ LLM Provider
     ↑              ↓
     └──── SSE ─────┘ (streaming)
```

**Benefits for Penguin:**
- Multiple clients (CLI, web, desktop)
- State isolation
- Real-time updates
- Future-proof for mobile

**Implementation:**
```typescript
// Penguin could add HTTP server
// penguin-cli/src/server/server.ts
import { Hono } from "hono";

const app = new Hono();

app.get("/api/sessions", async (c) => {
  const sessions = await Session.list();
  return c.json(sessions);
});

app.get("/event", (c) => {
  return streamSSE(c, async (stream) => {
    Bus.subscribeAll((event) => {
      stream.writeSSE({ data: JSON.stringify(event) });
    });
  });
});
```

#### 2. Instance-Scoped State

**OpenCode Pattern:**
```typescript
const state = Instance.state(
  async () => ({ data: await load() }),
  async (s) => await save(s.data)
);

Instance.provide({
  directory: "/project",
  fn: async () => {
    const s = state();  // Isolated per directory
  }
});
```

**Benefit:** No global state, automatic cleanup

**For Penguin:**
```typescript
// Replace ConnectionContext with instance-scoped client
const chatClient = Instance.state(
  async () => new ChatClient(Instance.directory),
  async (client) => client.disconnect()
);
```

#### 3. Type-Safe Event Bus

**OpenCode:**
```typescript
const Event = Bus.event("session.updated", z.object({ info: SessionInfo }));
Bus.publish(Event, { info });
Bus.subscribe(Event, (e) => console.log(e.properties.info));
```

**For Penguin:**
```typescript
// Replace callbacks with event bus
const TokenEvent = Bus.event("stream.token", z.object({ token: z.string() }));

// Publisher
Bus.publish(TokenEvent, { token });

// Multiple subscribers
Bus.subscribe(TokenEvent, (e) => setStreamingText(prev => prev + e.properties.token));
Bus.subscribe(TokenEvent, (e) => logToken(e.properties.token));
```

#### 4. Smart Edit Tool

**OpenCode's 9 Replacers:**
- Exact match
- Line-trimmed
- Block anchor
- Whitespace normalized
- Indent flexible
- Escape normalized
- Boundary trimmed
- Context-aware (Levenshtein)
- Multi-occurrence

**For Penguin:**
```typescript
// Add smart edit replacers to Penguin's edit tool
// penguin/tools/edit.py

def smart_replace(content: str, old: str, new: str) -> str:
    for replacer in REPLACERS:
        result = replacer(content, old, new)
        if result.success:
            return result.content
    raise ValueError("Could not find match")
```

### 11.2 Tool System Improvements

**OpenCode Tool API:**
```typescript
Tool.define("bash", {
  description: DESCRIPTION,
  parameters: z.object({ command: z.string() }),
  async execute(params, ctx) {
    // ctx provides:
    // - sessionID, messageID, callID
    // - agent name
    // - abort signal
    // - metadata() for live updates

    ctx.metadata({ progress: 0.5 });
    return { title, output, metadata };
  }
});
```

**For Penguin:**
```python
# penguin/tools/base.py
class Tool(ABC):
    @abstractmethod
    async def execute(self, params: dict, ctx: ToolContext) -> ToolResult:
        pass

class ToolContext:
    session_id: str
    message_id: str
    call_id: str
    agent_name: str
    abort_signal: AbortSignal

    def metadata(self, data: dict) -> None:
        """Send live updates"""
        bus.publish(ToolMetadataEvent, data)

# Usage
class BashTool(Tool):
    async def execute(self, params, ctx):
        ctx.metadata({"progress": 0.5})
        result = await run_bash(params["command"])
        return ToolResult(title="Success", output=result)
```

### 11.3 Permission System

**OpenCode's Granular Permissions:**
```typescript
agent: {
  permission: {
    edit: "ask",
    bash: {
      "npm *": "allow",
      "git *": "allow",
      "rm *": "ask",
      "*": "deny"
    }
  }
}
```

**For Penguin:**
```python
# penguin/agents/permissions.py
@dataclass
class AgentPermission:
    edit: Permission = Permission.ASK
    bash: dict[str, Permission] = field(default_factory=dict)
    webfetch: Permission = Permission.ASK

def check_bash_permission(agent: Agent, command: str) -> Permission:
    for pattern, permission in agent.permission.bash.items():
        if fnmatch(command, pattern):
            return permission
    return Permission.DENY  # Default deny
```

### 11.4 Session Management

**OpenCode's Session Features:**
- Forking (create child session from any message)
- Reverting (roll back to earlier state)
- Sharing (generate shareable URL)
- Compaction (merge similar messages)
- Summary (track file changes)

**For Penguin:**
```python
# penguin/sessions/session.py
@dataclass
class Session:
    id: str
    project_id: str
    directory: str
    parent_id: Optional[str] = None  # For forking
    title: str = ""
    summary: Optional[SessionSummary] = None

    def fork(self, from_message_id: str) -> "Session":
        """Create child session from specific message"""
        pass

    def revert(self, to_message_id: str) -> None:
        """Roll back to earlier state"""
        pass

    def share(self) -> str:
        """Generate shareable URL"""
        pass
```

### 11.5 Storage Strategy

**OpenCode's File-Based Storage:**
```
storage/
  session/{projectID}/{sessionID}.json
  message/{sessionID}/{messageID}.json
  part/{messageID}/{partID}.json
```

**Benefits:**
- Inspectable (plain JSON)
- No database needed
- Easy backup/restore
- Git-friendly

**For Penguin:**
```python
# penguin/storage/filesystem.py
class FileSystemStorage:
    def __init__(self, base_dir: Path = Path.home() / ".penguin" / "data"):
        self.base_dir = base_dir

    def write(self, key: list[str], data: dict) -> None:
        path = self.base_dir / "/".join(key) + ".json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))

    def read(self, key: list[str]) -> dict:
        path = self.base_dir / "/".join(key) + ".json"
        return json.loads(path.read_text())
```

### 11.6 Performance Optimizations

**OpenCode's Optimizations:**

1. **SolidJS over React:**
   - Fine-grained reactivity
   - No virtual DOM
   - Faster updates

2. **Bun over Node:**
   - 3x faster startup
   - Built-in SQLite, Glob, etc.
   - Better developer experience

3. **MaxSizedBox pattern:**
   ```tsx
   <MaxSizedBox maxHeight={30}>
     {/* Only render visible content */}
   </MaxSizedBox>
   ```

4. **Incremental rendering:**
   - Only update changed parts
   - Static sections never re-render

**For Penguin (React Ink):**
```typescript
// Add MaxSizedBox to Penguin
export function MaxSizedBox({ maxHeight, children }) {
  const [offset, setOffset] = useState(0);
  const lines = Children.toArray(children);

  const visible = lines.slice(offset, offset + maxHeight);

  return (
    <Box flexDirection="column">
      {visible}
    </Box>
  );
}
```

### 11.7 What Penguin Already Does Well

**Similarities with OpenCode:**

1. ✅ **Event-driven architecture** (callbacks, though not type-safe)
2. ✅ **Streaming tokens** (StreamProcessor similar to OpenCode)
3. ✅ **Tool system** (Penguin has good tool implementations)
4. ✅ **Provider abstraction** (OpenRouter)
5. ✅ **React-based TUI** (Ink vs SolidJS)

**Penguin Advantages:**

1. **Python backend** - easier for AI tool implementations
2. **OpenRouter integration** - unified access to many providers
3. **Simpler architecture** - easier to understand/modify

### 11.8 Priority Improvements for Penguin

**High Priority (Week 1-2):**

1. **Fix critical bugs** (session switching, duplicate WebSocket)
2. **Add type-safe event bus** (replace callbacks)
3. **Implement smart edit tool** (fuzzy matching)
4. **Add error boundaries**

**Medium Priority (Week 3-4):**

1. **Instance-scoped state** (replace Context API)
2. **Permission system** (granular tool permissions)
3. **Client/server split** (HTTP API + SSE)
4. **Session forking/reverting**

**Low Priority (Month 2+):**

1. **Migrate to Bun** (performance boost)
2. **Consider SolidJS** (if Ink performance issues)
3. **Add LSP integration**
4. **Add MCP support**

---

## Conclusion

OpenCode represents a **mature, production-ready** AI coding agent with sophisticated architecture patterns. Key takeaways:

### Strengths
- ✅ Clean client/server separation
- ✅ Strong type safety (Zod + TypeScript)
- ✅ Extensible (plugins, custom tools, custom agents)
- ✅ Granular permissions
- ✅ Smart edit tool (9 replacers)
- ✅ File-based storage (simple, inspectable)

### Opportunities for Penguin
1. Adopt instance-scoped state pattern
2. Implement type-safe event bus
3. Add client/server split for multi-client support
4. Enhance edit tool with fuzzy matching
5. Implement granular permission system
6. Consider Bun for performance gains

### Overall Assessment
**Grade: A** (Production-ready, well-architected)

OpenCode is an excellent reference for Penguin's evolution. The patterns are proven, the architecture is scalable, and the codebase quality is high. Penguin can adopt these patterns incrementally without a full rewrite.

---

**Next Steps:**
1. Review this analysis with team
2. Prioritize improvements
3. Create detailed implementation plans
4. Begin incremental adoption of OpenCode patterns
