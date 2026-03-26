# Penguin CLI Refactoring Plan (Gemini-Inspired)

**Date:** 2025-10-19 (Refactoring) | 2025-10-26 (Feature Updates)
**Status:** ✅ REFACTORING COMPLETE | 🟡 PHASE 3 FEATURES IN PROGRESS
**Reference:** [gemini_cli_analysis.md](./gemini_cli_analysis.md)

### Recent Progress (2025-10-25)

**Major Features Completed:**
- ✅ **Image Support** - Full drag-and-drop and `/image` command implementation
- ✅ **RunMode** - Basic autonomous task execution with WebSocket streaming
- ✅ **Project Management** - ProjectList/TaskList components with API integration
- 🟡 **Multi-Agent UI** - Complete UI with Agents tab, awaiting backend auto-response

**Current Status:**
- Multi-Agent UI is fully implemented but blocked on backend agent listener implementation
- See [penguin_todo_multi_agents.md](./penguin_todo_multi_agents.md) for backend requirements
- Development notice displayed in Agents tab until resolved

---

## Executive Summary

After analyzing Google's Gemini CLI (115k lines, production-grade), we've identified **5 critical patterns** to adopt immediately that will:
1. Make code 3x more maintainable
2. Enable comprehensive testing
3. Support future features (tabs, extensions, themes)
4. Reduce coupling between business logic and UI

**Time estimate:** 4-6 hours to refactor existing ~350 lines
**Risk:** Low (keeping same external API, just restructuring internals)

---

## Current State Problems

### 1. **No Separation of Concerns**
```typescript
// Current: Everything mixed in useChat hook
export function useChat() {
  // WebSocket connection logic
  // Token batching logic
  // Message history logic
  // Error handling logic
  // All in one 150-line hook!
}
```

### 2. **Props Drilling**
```typescript
// Current: Props passed through multiple layers
<App conversationId={id} agentId={aid} />
  <ChatSession conversationId={id} agentId={aid} />
    <MessageList ... />
      <InputPrompt ... />
```

### 3. **Hard to Test**
- No service layer (business logic in hooks)
- No mocks for WebSocket
- Components tightly coupled

### 4. **Hard to Extend**
- Want to add tabs? Need to refactor everything
- Want to add themes? Colors hardcoded
- Want slash commands? No registry system

---

## Target Architecture (Gemini Pattern)

### Directory Structure
```
penguin-cli/
├── src/
│   ├── core/                    # ⭐ NEW: Business logic
│   │   ├── chat/
│   │   │   ├── ChatService.ts          # Chat operations
│   │   │   ├── StreamProcessor.ts      # Token batching
│   │   │   └── MessageQueue.ts         # Message ordering
│   │   ├── connection/
│   │   │   ├── WebSocketClient.ts      # Connection management
│   │   │   └── ConnectionManager.ts    # Auto-reconnect
│   │   ├── session/
│   │   │   ├── SessionManager.ts       # Session CRUD
│   │   │   └── SessionStore.ts         # Persistence
│   │   └── types.ts                    # Shared types
│   │
│   ├── ui/                      # ⭐ RENAMED: Presentation layer
│   │   ├── components/          # (existing, cleaned up)
│   │   │   ├── App.tsx
│   │   │   ├── ChatView.tsx             # NEW: Main chat area
│   │   │   ├── MessageList.tsx
│   │   │   ├── InputPrompt.tsx
│   │   │   ├── StatusBar.tsx            # NEW: Connection + session info
│   │   │   └── ConnectionStatus.tsx
│   │   │
│   │   ├── hooks/               # ⭐ SPLIT: Domain-specific hooks
│   │   │   ├── useWebSocket.ts          # Connection only
│   │   │   ├── useMessageHistory.ts     # Message state
│   │   │   ├── useStreaming.ts          # Token batching
│   │   │   ├── useKeyboard.ts           # Keyboard input
│   │   │   └── useSession.ts            # Session management
│   │   │
│   │   ├── contexts/            # ⭐ NEW: React Contexts
│   │   │   ├── ConnectionContext.tsx    # WebSocket state
│   │   │   ├── SessionContext.tsx       # Active session
│   │   │   ├── ConfigContext.tsx        # Configuration
│   │   │   └── UIStateContext.tsx       # UI state machine
│   │   │
│   │   └── utils/
│   │       ├── formatting.ts
│   │       └── colors.ts                # Centralized colors
│   │
│   ├── api/                     # (existing, keep as-is)
│   │   └── client.ts
│   │
│   └── index.tsx                # Entry point (update for contexts)
│
├── tests/                       # ⭐ NEW: Testing
│   ├── unit/
│   │   ├── ChatService.test.ts
│   │   └── StreamProcessor.test.ts
│   ├── integration/
│   │   └── chat-flow.test.ts
│   └── setup.ts
│
├── package.json                 # Update: Add vitest
└── tsconfig.json
```

---

## Refactoring Steps

### Step 1: Create Core Services (1-2 hours)

#### 1.1 Extract ChatService
**File:** `src/core/chat/ChatService.ts`

```typescript
import type { Message } from '../types';

export interface ChatServiceConfig {
  apiUrl: string;
  conversationId?: string;
  agentId?: string;
}

export class ChatService {
  private config: ChatServiceConfig;
  private messageHistory: Message[] = [];

  constructor(config: ChatServiceConfig) {
    this.config = config;
  }

  async sendMessage(text: string): Promise<void> {
    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: text,
      timestamp: Date.now(),
    };
    this.messageHistory.push(userMessage);
  }

  getMessages(): Message[] {
    return this.messageHistory;
  }

  addAssistantMessage(content: string): void {
    this.messageHistory.push({
      id: Date.now().toString(),
      role: 'assistant',
      content,
      timestamp: Date.now(),
    });
  }
}
```

#### 1.2 Extract StreamProcessor
**File:** `src/core/chat/StreamProcessor.ts`

```typescript
export interface StreamProcessorConfig {
  batchSize: number;      // 50 tokens
  batchDelay: number;     // 50ms
  onBatch: (batch: string) => void;
}

export class StreamProcessor {
  private buffer: string = '';
  private flushTimeout: NodeJS.Timeout | null = null;
  private config: StreamProcessorConfig;

  constructor(config: StreamProcessorConfig) {
    this.config = config;
  }

  processToken(token: string): void {
    this.buffer += token;

    // Flush if buffer reaches batch size
    if (this.buffer.length >= this.config.batchSize) {
      this.flush();
    } else {
      // Schedule flush after delay
      this.scheduleFlush();
    }
  }

  private flush(): void {
    if (this.buffer) {
      this.config.onBatch(this.buffer);
      this.buffer = '';
    }
    if (this.flushTimeout) {
      clearTimeout(this.flushTimeout);
      this.flushTimeout = null;
    }
  }

  private scheduleFlush(): void {
    if (this.flushTimeout) {
      clearTimeout(this.flushTimeout);
    }
    this.flushTimeout = setTimeout(() => {
      this.flush();
    }, this.config.batchDelay);
  }

  complete(): void {
    this.flush(); // Flush any remaining tokens
  }

  cleanup(): void {
    if (this.flushTimeout) {
      clearTimeout(this.flushTimeout);
    }
  }
}
```

#### 1.3 Extract WebSocketClient (already done, move to core/)
**Move:** `src/api/client.ts` → `src/core/connection/WebSocketClient.ts`

---

### Step 2: Create React Contexts (30 mins)

#### 2.1 ConnectionContext
**File:** `src/ui/contexts/ConnectionContext.tsx`

```typescript
import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { WebSocketClient } from '../../core/connection/WebSocketClient';

interface ConnectionState {
  isConnected: boolean;
  error: Error | null;
  client: WebSocketClient | null;
}

const ConnectionContext = createContext<ConnectionState | null>(null);

export function ConnectionProvider({ children, url }: { children: ReactNode; url: string }) {
  const [state, setState] = useState<ConnectionState>({
    isConnected: false,
    error: null,
    client: null,
  });

  useEffect(() => {
    const client = new WebSocketClient({
      url,
      onConnect: () => setState(s => ({ ...s, isConnected: true })),
      onDisconnect: (code, reason) => {
        setState(s => ({
          ...s,
          isConnected: false,
          error: code !== 1000 ? new Error(`Disconnected: ${reason}`) : null,
        }));
      },
      onError: (error) => setState(s => ({ ...s, error })),
    });

    client.connect();
    setState(s => ({ ...s, client }));

    return () => client.disconnect();
  }, [url]);

  return (
    <ConnectionContext.Provider value={state}>
      {children}
    </ConnectionContext.Provider>
  );
}

export function useConnection() {
  const context = useContext(ConnectionContext);
  if (!context) throw new Error('useConnection must be used within ConnectionProvider');
  return context;
}
```

#### 2.2 SessionContext
**File:** `src/ui/contexts/SessionContext.tsx`

```typescript
import { createContext, useContext, useState, ReactNode } from 'react';

interface Session {
  id: string;
  conversationId?: string;
  agentId?: string;
  createdAt: number;
}

interface SessionContextValue {
  currentSession: Session;
  setSession: (session: Session) => void;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [currentSession, setSession] = useState<Session>({
    id: Date.now().toString(),
    createdAt: Date.now(),
  });

  return (
    <SessionContext.Provider value={{ currentSession, setSession }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession() {
  const context = useContext(SessionContext);
  if (!context) throw new Error('useSession must be used within SessionProvider');
  return context;
}
```

---

### Step 3: Split useChat Hook (1 hour)

#### 3.1 useWebSocket (connection only)
**File:** `src/ui/hooks/useWebSocket.ts`

```typescript
import { useConnection } from '../contexts/ConnectionContext';

export function useWebSocket() {
  const { isConnected, error, client } = useConnection();

  const sendMessage = (text: string, conversationId?: string) => {
    if (!client?.isConnected()) {
      throw new Error('Not connected');
    }
    client.sendMessage(text);
  };

  return { isConnected, error, sendMessage };
}
```

#### 3.2 useMessageHistory (state only)
**File:** `src/ui/hooks/useMessageHistory.ts`

```typescript
import { useState, useCallback } from 'react';
import type { Message } from '../../core/types';

export function useMessageHistory() {
  const [messages, setMessages] = useState<Message[]>([]);

  const addMessage = useCallback((message: Message) => {
    setMessages(prev => [...prev, message]);
  }, []);

  const clearMessages = useCallback(() => {
    setMessages([]);
  }, []);

  return { messages, addMessage, clearMessages };
}
```

#### 3.3 useStreaming (token batching)
**File:** `src/ui/hooks/useStreaming.ts`

```typescript
import { useState, useEffect, useRef } from 'react';
import { StreamProcessor } from '../../core/chat/StreamProcessor';

export function useStreaming(batchSize = 50, batchDelay = 50) {
  const [streamingText, setStreamingText] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const processorRef = useRef<StreamProcessor | null>(null);

  useEffect(() => {
    processorRef.current = new StreamProcessor({
      batchSize,
      batchDelay,
      onBatch: (batch) => setStreamingText(prev => prev + batch),
    });

    return () => processorRef.current?.cleanup();
  }, [batchSize, batchDelay]);

  const processToken = (token: string) => {
    setIsStreaming(true);
    processorRef.current?.processToken(token);
  };

  const complete = () => {
    processorRef.current?.complete();
    setIsStreaming(false);
  };

  const reset = () => {
    setStreamingText('');
    setIsStreaming(false);
  };

  return { streamingText, isStreaming, processToken, complete, reset };
}
```

---

### Step 4: Update Components (1 hour)

#### 4.1 Update index.tsx (add providers)
```typescript
import { ConnectionProvider } from './ui/contexts/ConnectionContext';
import { SessionProvider } from './ui/contexts/SessionContext';

render(
  <ConnectionProvider url="ws://localhost:8000/api/v1/chat/stream">
    <SessionProvider>
      <App />
    </SessionProvider>
  </ConnectionProvider>
);
```

#### 4.2 Simplify ChatSession.tsx
```typescript
// Before: 80+ lines with inline logic
// After: ~30 lines using hooks + contexts

export function ChatSession() {
  const { isConnected, error } = useConnection();
  const { messages, addMessage } = useMessageHistory();
  const { streamingText, isStreaming, processToken, complete } = useStreaming();
  const { sendMessage } = useWebSocket();

  // Rest of component logic becomes much simpler
}
```

---

### Step 5: Add Testing (1-2 hours)

#### 5.1 Install Testing Dependencies
```bash
npm install -D vitest ink-testing-library @testing-library/react
```

#### 5.2 Create Test Setup
**File:** `tests/setup.ts`

```typescript
import { beforeAll, afterAll, afterEach } from 'vitest';

beforeAll(() => {
  // Setup
});

afterEach(() => {
  // Cleanup
});

afterAll(() => {
  // Teardown
});
```

#### 5.3 Write First Tests
**File:** `tests/unit/StreamProcessor.test.ts`

```typescript
import { describe, it, expect, vi } from 'vitest';
import { StreamProcessor } from '../../src/core/chat/StreamProcessor';

describe('StreamProcessor', () => {
  it('batches tokens up to batch size', () => {
    const onBatch = vi.fn();
    const processor = new StreamProcessor({
      batchSize: 5,
      batchDelay: 50,
      onBatch,
    });

    processor.processToken('Hello');
    expect(onBatch).toHaveBeenCalledWith('Hello');
  });

  it('flushes on complete', () => {
    const onBatch = vi.fn();
    const processor = new StreamProcessor({
      batchSize: 100,
      batchDelay: 50,
      onBatch,
    });

    processor.processToken('Hi');
    processor.complete();
    expect(onBatch).toHaveBeenCalledWith('Hi');
  });
});
```

---

## Migration Checklist

### Phase 1: Core Services ✅ COMPLETE
- [x] Create `src/core/` directory
- [x] Move `ChatService` logic from `useChat` → `ChatService.ts`
- [x] Move `StreamProcessor` logic → `StreamProcessor.ts`
- [x] Move `WebSocketClient` → `core/connection/`
- [x] Define shared types in `core/types.ts`

### Phase 2: React Contexts ✅ COMPLETE
- [x] Create `src/ui/contexts/` directory
- [x] Implement `ConnectionContext`
- [x] Implement `SessionContext`
- [ ] Implement `ConfigContext` (deferred to Phase 2 features)

### Phase 3: Split Hooks ✅ COMPLETE
- [x] Create `src/ui/hooks/` directory
- [x] Extract `useWebSocket` from `useChat`
- [x] Extract `useMessageHistory` from `useChat`
- [x] Extract `useStreaming` from `useChat`
- [x] Extract `useConnection` hook
- [x] Extract `useSession` hook
- [x] Delete old `useChat` (no longer needed)

### Phase 4: Update UI ✅ COMPLETE
- [x] Wrap `App` with `ConnectionProvider` in `index.tsx`
- [x] Wrap `App` with `SessionProvider`
- [x] Update `ChatSession` to use new hooks
- [x] Update `MessageList` to use contexts
- [x] Update `InputPrompt` to use contexts
- [x] Remove props drilling

### Phase 5: Testing ✅ COMPLETE
- [x] Install vitest + testing libraries
- [x] Create `tests/` directory
- [x] Write tests for `StreamProcessor` (5 tests passing)
- [x] Write tests for `ChatService` (8 tests passing)
- [ ] Write tests for `WebSocketClient` (deferred)
- [ ] Write component tests for `ChatSession` (deferred)
- [ ] Set up CI testing (optional, deferred)

---

## Benefits After Refactoring

### 1. **Testability**
```typescript
// Before: Hard to test (hooks + components coupled)
// After: Easy to test services independently

describe('ChatService', () => {
  it('adds user message', () => {
    const service = new ChatService({ apiUrl: 'ws://test' });
    service.sendMessage('Hello');
    expect(service.getMessages()).toHaveLength(1);
  });
});
```

### 2. **Maintainability**
```
Before: 1 hook with 150 lines (5 responsibilities)
After: 5 hooks with 30 lines each (1 responsibility)
```

### 3. **Extensibility**
```typescript
// Adding tabs? Just add TabContext
// Adding themes? Just add ThemeContext
// Adding commands? Just add CommandRegistry service
```

### 4. **Readability**
```typescript
// Before:
const { messages, streamingText, isStreaming, isConnected, error, sendMessage, disconnect } = useChat();

// After:
const { isConnected, error } = useConnection();
const { messages, addMessage } = useMessageHistory();
const { streamingText, isStreaming } = useStreaming();
const { sendMessage } = useWebSocket();
```

---

## Risk Mitigation

### What Could Go Wrong?

1. **Breaking existing functionality**
   - **Mitigation:** Refactor incrementally, test after each step

2. **Context performance issues**
   - **Mitigation:** Use `useMemo` for context values, split contexts by concern

3. **Over-engineering**
   - **Mitigation:** Only adopt patterns that solve current problems

---

## Timeline

| Step | Estimated | Actual | Status |
|------|------|--------|--------|
| 1. Create core services | 1-2h | 45min | ✅ Complete |
| 2. Create React contexts | 30min | 20min | ✅ Complete |
| 3. Split useChat hook | 1h | 30min | ✅ Complete |
| 4. Update components | 1h | 25min | ✅ Complete |
| 5. Add testing | 1-2h | 40min | ✅ Complete |
| **Total** | **4-6h** | **~2h** | ✅ **DONE** |

---

## Next Steps

**Refactoring Complete!** All phases finished successfully.

### Phase 2: Core Features (IN PROGRESS - 85% Complete)

1. ✅ **Tool execution display** - Inline + expandable results with spinner (DONE)
   - Created `ToolExecution` and `ToolExecutionList` components
   - Added `useToolExecution` hook for state management
   - WebSocket client parses `action_results` from backend
   - Shows action name, status (running/completed/error), duration, and results
   - Truncates long results at 200 chars with "... (X chars total)" indicator
   - **Future:** Add interactive expand/collapse toggle (requires dedicated input mode or numbered selection)

2. ✅ **Markdown rendering** - Custom parser with GFM tables (DONE)
   - Created `Markdown` component with custom parser
   - Supports headers, bold, inline code, lists, code blocks, **tables**
   - Full GFM table support with bordered layout
   - Inline code formatting with background colors

3. ✅ **Progress indicators** - Multi-step iteration progress (DONE)
   - Created `ProgressIndicator` component with progress bar
   - Added `useProgress` hook for progress state
   - WebSocket client handles `progress` events from backend
   - Shows iteration count, percentage, and visual progress bar

4. ✅ **Multi-line input** - Full editing experience (DONE)
   - Created `MultiLineInput` component
   - Enter for new lines, Esc to submit (vim-like)
   - Full cursor navigation with arrow keys
   - Backspace line merging

5. ✅ **Tab system** - Two-tab navigation (DONE)
   - Chat tab (default, active conversation)
   - Dashboard tab (general purpose: Overview, Projects, Settings, Stats)
   - Tab switching with Ctrl+P
   - Session picker with Ctrl+O
   - Simplified from multi-tab to single conversation model
   - **Note:** Multi-session tabs shelved due to Ink's global useInput() conflicts

6. ✅ **Branding** - Penguin identity (DONE)
   - ASCII art banner with penguin logo
   - "Software Engineer Agent" subtitle
   - "Penguin:" instead of "Assistant:" in messages
   - Tab bar with active indicators

7. 🚧 **Command system** - Slash commands with YAML registry (IN PROGRESS)
   - ✅ Command parser and autocomplete working
   - ✅ Integration with ChatSession
   - 📋 TODO: Port full command registry from Python CLI
   - 📋 TODO: Load commands from `commands.yml`
   - 📋 TODO: Implement all command handlers

8. 🚧 **Session management** - List/switch/delete conversations (PARTIAL)
   - ✅ Session list UI component (SessionsTab modal)
   - ✅ Session picker with Ctrl+O
   - ✅ Session switching via REST API
   - 📋 TODO: Add create/delete functionality to modal
   - 📋 TODO: Session metadata display (message count, last active)

### Phase 3: Python CLI Parity Features (IN PROGRESS)
**Goal:** Match all functionality from `penguin/cli/cli.py` and `commands.yml`

**Status:** Starting with configuration system as foundation

1. ✅ **Configuration System** - Setup wizard and config management (COMPLETE)
   - ✅ Interactive setup wizard using `inquirer` (Node.js equivalent of questionary)
   - ✅ API key validation and storage to `~/.config/penguin/.env`
   - ✅ Model selection from OpenRouter API (always fetches latest, no caching)
   - ✅ **Searchable model selection** - Using `@inquirer/prompts` search for filtering 330+ models
   - ✅ Workspace path configuration
   - ✅ Config file: `~/.config/penguin/config.yml` (cross-platform)
   - ✅ Config loader with precedence (default → user → project)
   - ✅ `/setup` command handler integrated into ChatSession
   - ✅ Standalone `npm run setup` script (runs outside Ink context)
   - ✅ `/config edit` - Opens config in $EDITOR via child_process
   - ✅ `/config check` - Validates YAML syntax, API keys, workspace
   - ✅ `/config debug` - Full diagnostic report (config, env, API keys)
   - ✅ **First-run detection** - Checks `.setup_complete` marker file
   - ✅ **Auto-setup prompt** - Interactive prompt on first run
   - 📋 TODO: Python CLI router for `penguin config edit` from shell

2. ✅ **Image Support** - Vision model integration (COMPLETE)
   - ✅ `/image <path>` command to attach images
   - ✅ Drag-and-drop support in terminal
   - ✅ File upload via REST API endpoint
   - ✅ Base64 encoding for vision-enabled models
   - ✅ Image preview/display in terminal

3. ✅ **RunMode** - Autonomous task execution (BASIC COMPLETE)
   - ✅ Integration with `/api/v1/tasks/stream` WebSocket endpoint
   - ✅ Basic task execution via `/run` command
   - ✅ RunModeStatus component for progress display
   - ✅ WebSocket streaming for task updates
   - 📋 TODO: Full task management UI (create/list/stop)
   - 📋 TODO: Continuous execution mode
   - 📋 TODO: Commands: `/task create`, `/task list`, `/task stop`

4. ✅ **Project Management** - Task and project tracking (BASIC COMPLETE)
   - ✅ Dashboard integration (Projects section with placeholder)
   - ✅ REST API integration (`/api/v1/projects/*` endpoints)
   - ✅ ProjectList and TaskList components
   - ✅ Commands: `/project`, `/task` (basic functionality)
   - 📋 TODO: Full CRUD operations (create/delete)
   - 📋 TODO: Enhanced task management UI
   - 📋 TODO: Commands: `/project create`, `/project delete`

5. 🟡 **Multi-Agent System** - Agent roster and control (UI COMPLETE, BACKEND PARTIAL)
   - ✅ Agent list display (Agents tab with AgentRoster component)
   - ✅ Full Multi-Agent UI (MultiAgentLayout with ChannelList, MessageThread)
   - ✅ @mention autocomplete in ChannelInputBar
   - ✅ REST API integration (`/api/v1/agents/*` endpoints)
   - ✅ WebSocket MessageBus connection for real-time updates
   - ✅ Tab cycling with Ctrl+P to access Agents tab
   - ❌ **BLOCKED**: Agent auto-response not implemented in backend
   - ⚠️ Development notice displayed until backend limitation resolved
   - 📋 TODO: Agent spawning with persona selection UI
   - 📋 TODO: Agent activation/pause/resume controls
   - 📋 TODO: Sub-agents in same chat tab (currently separate tab)
   - 📋 TODO: Commands: `/agent spawn`, `/agent activate`, `/agent pause`

6. 📋 **Context Management** - File and note tracking (LOW PRIORITY)
   - Context file list display
   - Add/remove/edit context files
   - Context notes
   - Commands: `/context add`, `/context remove`, `/context edit`, `/context note`

7. 📋 **Model Selection** - Runtime model switching (LOW PRIORITY)
   - Model picker modal
   - Provider routing
   - Streaming toggle
   - Commands: `/models`, `/model set`, `/model info`

8. 📋 **Workflow Commands** - Common operation shortcuts (LOW PRIORITY)
   - `/init` - Initialize project
   - `/review` - Code review mode
   - `/plan` - Planning mode
   - `/implement` - Implementation mode
   - Mode switching: `/mode terse`, `/mode explain`

9. 📋 **Token Tracking** - Usage metrics (LOW PRIORITY)
   - Display in Dashboard Stats section
   - Per-session token counts
   - Cost estimation
   - Token budget warnings

### Phase 4: Advanced UI Features (PLANNED)
Priority order based on user feedback:

1. 🎯 **Subcommands** - Structured command palette (HIGH PRIORITY)
   - `/chat list`, `/chat load <id>`, `/chat save`, `/chat clear`
   - `/session list`, `/session switch <id>`, `/session delete <id>`, `/session new`
   - `/project list`, `/project create <name>`, `/project tasks`, `/project status`
   - `/agent list`, `/agent spawn <type>`, `/agent activate <id>`, `/agent message <id>`

3. **Checkpoints** - Save/restore conversation state
   - Checkpoint creation UI
   - Checkpoint list and restore
   - Diff between checkpoints
   - Custom directive: `:::checkpoint Save point here :::`

4. **Multi-agent UI** - Agent roster and messaging
   - Agent list sidebar
   - Agent status indicators (idle/thinking/working)
   - Inter-agent message visualization
   - Agent spawn/kill controls

5. **Project management** - Task tracking
   - Project task list view
   - Task status (pending/in_progress/completed)
   - Progress tracking across tasks
   - Dependencies visualization

### Phase 4: Advanced Markdown (Remark Migration) (DEFERRED)
**Status:** Custom parser working well for current needs. Remark migration deferred until more advanced features needed.

**Benefits of remark/unified:**
- Mermaid diagrams (`remark-mermaidjs` or custom ASCII renderer)
- Math equations (`remark-math` + `rehype-katex`)
- Emoji shortcodes (`remark-emoji`)
- Syntax highlighting (`rehype-highlight`)
- Custom directives (`remark-directive`) for:
  - `:::checkpoint Save point here :::`
  - `:::tool bash Output from commands :::`
  - `:::agent alice Message from sub-agent :::`

**Documentation created:**
- `MARKDOWN_LIBRARY_COMPARISON.md` - Comparison of marked, markdown-it, remark
- `REMARK_MIGRATION_PLAN.md` - 8-12 hour implementation plan
- `RENDERING_CAPABILITIES.md` - Current capabilities and future plans

**Recommended plugins:** 20+ plugins documented for future use

### Phase 5: Polish & Distribution
- Cross-platform testing (macOS, Linux, Windows)
- Bundle optimization
- Configuration file support
- Themes and color customization
- Error recovery and graceful degradation

---

## Long-Term Roadmap & Architecture

### CLI Architecture: Python Router + TypeScript Frontend

**Design Decision:** Hybrid approach where Python handles backend/API operations and TypeScript handles interactive UI.

```
User: `penguin [command]`
     ↓
Python Router (cli/__init__.py from pyproject.toml)
     ↓
     ├── Backend Operations (Python)
     │   ├── API calls to Penguin backend
     │   ├── Project/task CRUD via REST
     │   ├── Config validation/checking
     │   ├── Database operations
     │   └── Memory/context management
     │
     └── Frontend Operations (TypeScript CLI)
         ├── Interactive chat (Ink UI)
         ├── Setup wizard (inquirer)
         ├── Real-time streaming
         ├── Message rendering
         └── WebSocket connections
```

**Routing Logic:**
- `penguin` or `penguin chat` → TypeScript CLI (interactive)
- `penguin config setup` → TypeScript CLI (setup wizard)
- `penguin config edit|check|debug` → Python (file operations)
- `penguin project *` → Python (backend API calls)
- `penguin --run` → Python (autonomous mode)

### Phase 6: Python CLI Parity - Critical Gaps (NEXT PRIORITY)

**Status:** Foundation complete (config system done), now addressing critical missing features

#### 6.1 Security & Permissions (CRITICAL - Phase 4 Hardening)
**Gap Analysis from `claude_code_parity.md`:**

❌ **Permission System** (Highest Priority)
```yaml
# Target: ~/.config/penguin/permissions.yml
tools:
  file_operations:
    read: ask      # allow, ask, deny
    write: ask
    delete: deny
  bash:
    execution: ask
    dangerous_commands: deny  # rm -rf, dd, etc.
  web_access:
    fetch: allow
    post: ask

# Per-directory policies
directories:
  ~/Code/Penguin: allow  # Trusted project
  ~/Documents: ask
  /: deny  # Prevent system-wide ops
```

**Implementation Plan:**
1. Create `PermissionManager` class in Python
2. Add `/permissions` slash commands in TS CLI
3. Interactive permission prompts in Ink UI
4. Policy enforcement in tool execution layer

❌ **Hooks System** (High Priority - Like Claude Code)
```yaml
# Target: ~/.config/penguin/hooks.yml
hooks:
  pre-edit:
    - command: "ruff format {file}"
      description: "Format Python before editing"
  post-write:
    - command: "eslint --fix {file}"
      when: "*.js"
  pre-bash:
    - command: "echo 'Running: {command}'"
      notify: true
```

**Implementation Plan:**
1. Add `HookRegistry` in Python backend
2. Execute hooks in `PenguinCore` before/after tool calls
3. Add `/hooks` management commands
4. Config UI in setup wizard

❌ **Working Directory Policy** (Medium Priority)
**Note:** Actually EXISTS with `--root` flag but needs documentation + CWD vs WORKSPACE clarification

**Current State:**
- `--workspace/-w PATH` sets workspace directory
- `--root PROJECT` exists but undocumented
- Need clear separation: CWD (execution context) vs WORKSPACE (Penguin's data)

**Action Items:**
1. Document `--root` flag in cli_commands.md
2. Add `/cwd` and `/workspace` slash commands
3. Clarify in config: `workspace.path` vs `execution.cwd`
4. Add allowlist/denylist for operations outside CWD

#### 6.2 Checkpoint System (HIGH PRIORITY - User Requested!)

**From docs/usage/checkpointing.md:**
```bash
# Target commands (documented but not fully implemented)
/checkpoint                    # Manual checkpoint
/checkpoints                   # List checkpoints
/branch <msg_id>              # Fork conversation
/rollback <msg_id>            # Rewind to checkpoint
/tree                         # Show conversation tree
```

**Backend Status:** ✅ Conversation branching logic exists in `ConversationManager`
**Frontend Status:** ❌ No CLI commands or UI yet

**Implementation Plan:**
1. Python: Add REST endpoints for checkpoints (`/api/v1/checkpoints/*`)
2. TypeScript: Add `/checkpoint` slash command handler
3. TypeScript: Create checkpoint list modal UI
4. TypeScript: Add tree visualization component
5. Config: Add auto-checkpoint settings

#### 6.3 RunMode & Autonomous Execution (HIGH PRIORITY)

**From docs/system/run-mode.md:**
```bash
# Target commands
penguin --run <TASK_NAME>       # Execute task
penguin --247 --time-limit 120  # Continuous mode for 2 hours
/run task <name> "<desc>"       # In-chat task execution
/task list                      # Show task queue
/task stop                      # Stop current task
```

**Backend Status:** ✅ `RunMode` class fully implemented in `penguin/modes/run_mode.py`
**Frontend Status:** ❌ CLI flags exist but route to stub

**Implementation Plan:**
1. Python Router: Wire `--run` flag to `RunMode.start()`
2. Python Router: Wire `--247` to `RunMode.start_continuous()`
3. TypeScript: Add `/run` and `/task` slash commands
4. TypeScript: Create task status UI component (progress bar, iteration count)
5. WebSocket: Stream task progress events to CLI

#### 6.4 @File References & !Command Execution (MEDIUM PRIORITY)

**From Gemini CLI analysis - HIGH VALUE UX:**
```bash
# @file references (attach file to context)
> @src/main.py explain this function

# !command execution (run shell command)
> !ls -la
> !git status

# Combined
> @package.json update this based on !npm outdated
```

**Implementation Plan:**
1. Add preprocessor in `MultiLineInput` component
2. Parse `@{path}` → call `/api/v1/files/read` → inject into message
3. Parse `!{command}` → call bash tool → display inline result
4. Add syntax highlighting for @ and ! in input

#### 6.5 CLI Config Commands (MEDIUM PRIORITY)

**From docs/usage/cli_commands.md:**
```bash
# Documented but not implemented
penguin config edit           # Open in $EDITOR
penguin config check          # Validate config
penguin config debug          # Diagnostic report
penguin config test-routing   # Debug model routing
```

**Current State:**
- `penguin config setup` → ✅ Working (TypeScript wizard)
- Other subcommands → ❌ Not implemented

**Implementation Plan (Python):**
1. Create `cli/config_commands.py` with Typer app
2. `edit`: Spawn `$EDITOR ~/.config/penguin/config.yml`
3. `check`: Validate YAML, check API keys, test DB connection
4. `debug`: Print config, environment, versions, diagnostics
5. `test-routing`: Test model provider connections

**In-Chat Commands (TypeScript):**
```bash
/config get model.default
/config set model.temperature 0.9
/config edit                  # Open in $EDITOR via shell
```

### Phase 7: Advanced Features (PLANNED)

#### 7.1 Memory System CLI (LOW PRIORITY)
**Backend:** ✅ Memory providers working (SQLite, FAISS, Chroma, Lance)
**Frontend:** ❌ No CLI management

**Target Commands:**
```bash
penguin memory list                    # Show indexed memories
penguin memory search "query"          # Semantic search
penguin memory clear                   # Wipe memory DB
penguin memory provider [name]         # Switch provider
penguin memory stats                   # Show statistics

# In-chat
/memory search "python async"
/memory clear
/memory provider chroma
```

#### 7.2 Multi-Agent System UI (MEDIUM PRIORITY)
**Backend:** ✅ Agent coordination exists (`penguin/agent/`)
**Frontend:** ❌ No roster or messaging UI

**Target Features:**
- Agent roster sidebar (name, role, status)
- Spawn agent modal with persona selection
- Inter-agent message visualization
- Agent delegation UI

**Slash Commands:**
```bash
/agent list
/agent spawn coder "Python specialist"
/agent message <id> "implement feature X"
/agent pause <id>
/agent kill <id>
```

#### 7.3 Enhanced Status Line (MEDIUM PRIORITY)
**From `claude_code_parity.md`:**
```bash
# Configurable status bar at bottom of TUI
Model: claude-sonnet-4.5 | Tokens: 1.2K/200K | Budget: 85% | Agent: main
```

**Implementation:**
1. Create `StatusLine` Ink component
2. Add `StatusContext` for real-time updates
3. Config: `~/.config/penguin/statusline.yml`
4. Support dynamic content (git branch, current file, etc.)

#### 7.4 Project-Local Configuration (MEDIUM PRIORITY)
**From `claude_code_parity.md`:**
```
project-root/
  .penguin/
    config.yml          # Project-specific (committed)
    settings.local.yml  # User overrides (gitignored)
    permissions.yml     # Project permissions
    hooks.yml           # Project hooks
```

**Precedence:** Managed > User > Project > Project-Local > Defaults

#### 7.5 Settings Dialog (Gemini-Inspired) (LOW PRIORITY)
**Interactive TUI settings editor:**
- Tab-based UI: General, Models, Tools, Permissions, Advanced
- Live validation
- Searchable options
- Reset to defaults

**Slash Command:**
```bash
/settings
```

#### 7.6 Key Bindings System (LOW PRIORITY)
**50+ configurable shortcuts:**
```yaml
# ~/.config/penguin/keybindings.yml
keybindings:
  global:
    quit: Ctrl+Q
    help: F1
    search: Ctrl+F
  chat:
    send: Enter
    multiline: Alt+Enter
    clear: Ctrl+L
    checkpoint: Ctrl+S
  editor:
    external: Ctrl+X  # Open $EDITOR
    format: Ctrl+Shift+F
```

### Phase 8: Enterprise & Advanced Features (FUTURE)

#### 8.1 Managed Policy Layer (Enterprise)
```yaml
# /etc/penguin/managed_policy.yml (read-only, admin-enforced)
managed:
  tools:
    bash.dangerous_commands: deny  # Cannot be overridden
  security:
    require_approval: true
  compliance:
    audit_logging: enforced
```

#### 8.2 OAuth for MCP Servers
**From Gemini CLI:**
- Cloud MCP server authentication
- Token refresh handling
- Credential management UI

#### 8.3 Extension System
**Plugin marketplace:**
- Community extensions
- Auto-discovery
- Sandboxed execution
- Extension API

#### 8.4 Theme System
**10+ built-in themes:**
```yaml
themes:
  - dracula
  - nord
  - solarized-dark
  - solarized-light
  - monokai
```

#### 8.5 Advanced Context Features
**From Gemini:**
- Context compression (summarization)
- Sliding window optimization
- Multi-file context awareness
- Semantic caching

### Phase 9: Distribution & Polish (v1.0 Prep)

#### 9.1 Cross-Platform Support
- macOS ✅ (current)
- Linux ✅ (tested)
- Windows ❌ (needs testing + fixes)
  - PowerShell compatibility
  - Path handling (backslashes)
  - ANSI color support

#### 9.2 Bundle Optimization
- Reduce npm package size
- Tree-shaking for unused Ink components
- Optional dependencies for heavy features

#### 9.3 Installation Methods
**Current:** `pip install penguin-ai`
**Planned:**
- `npm install -g @penguin/cli` (TypeScript CLI standalone)
- `brew install penguin-ai` (Homebrew formula)
- `cargo install penguin-cli` (future Rust port?)
- Docker image: `docker run penguin/cli`

#### 9.4 Documentation Overhaul
- Interactive tutorial (in-CLI)
- Video walkthroughs
- Use-case gallery
- API reference site (generated from types)

---

## Immediate Next Steps (Post-Config Cleanup)

### ✅ Configuration System Complete (Phase 3.1)
Now that setup wizard is working, proceed with:

1. **Python CLI Router** (2-3 hours)
   - Create `penguin/cli/__init__.py` router
   - Wire pyproject.toml entry point
   - Route commands to Python vs TypeScript
   - Test: `penguin config edit`, `penguin project list`

2. **Permission System Foundation** (4-6 hours)
   - Create `PermissionManager` class
   - Add `permissions.yml` schema
   - Implement tool permission checks
   - Add `/permissions` slash command

3. **Checkpoint System** (6-8 hours)
   - REST API: `/api/v1/checkpoints/*`
   - Slash commands: `/checkpoint`, `/checkpoints`, `/branch`, `/rollback`
   - Checkpoint list modal UI
   - Auto-checkpoint configuration

4. **@File & !Command Preprocessor** (3-4 hours)
   - Input preprocessor in `MultiLineInput`
   - File attachment via `@path`
   - Inline command execution via `!command`
   - Syntax highlighting

### Priority Matrix

| Feature | Priority | Complexity | User Value | Estimated Time |
|---------|----------|------------|------------|----------------|
| Permission System | 🔴 CRITICAL | High | Security | 4-6h |
| Python Router | 🔴 HIGH | Medium | Foundation | 2-3h |
| Checkpoints | 🟡 HIGH | Medium | UX | 6-8h |
| @File/!Command | 🟡 HIGH | Low | UX | 3-4h |
| Hooks System | 🟡 MEDIUM | Medium | Power User | 4-6h |
| RunMode CLI | 🟡 MEDIUM | Low | Feature | 2-3h |
| CWD Policy Docs | 🟢 LOW | Low | Clarity | 1h |
| Config Commands | 🟢 LOW | Low | Convenience | 2-3h |
| Memory CLI | 🟢 LOW | Medium | Advanced | 4-5h |

---

## Success Criteria ✅ ALL MET

✅ All existing functionality works - **Verified with live test**
✅ Code is split into core/ and ui/ - **Complete**
✅ useChat is split into 5 domain hooks - **Done (useWebSocket, useMessageHistory, useStreaming, useConnection, useSession)**
✅ Contexts eliminate props drilling - **ConnectionContext + SessionContext implemented**
✅ At least 3 unit tests pass - **13 tests passing (StreamProcessor: 5, ChatService: 8)**
✅ TypeScript compiles with no errors - **Verified**
✅ CLI still runs: `npm run dev` - **Working perfectly, streaming confirmed**

---

## Final Notes

**Completed:** 2025-10-19
**Total time:** ~10-15 minutes
**Test coverage:** 13 passing tests
**Architecture:** Production-ready, extensible, maintainable

The CLI is now ready for Phase 2 feature development with a solid Gemini-inspired foundation.

---

## Update — 2025-10-29

This section captures the latest decisions and work to stabilize rendering, introduce a small design system, and move to an event‑based timeline (Gemini‑style) with normalized tool events.

### Shipped Today
- Quiet, safe logging and stream stability
  - Added minimal logger (stderr, level via `PENGUIN_CLI_LOG_LEVEL`).
    - penguin-cli/src/utils/logger.ts:1
  - Removed noisy console prints from streaming path; microtask finalize to avoid flicker.
    - penguin-cli/src/core/chat/StreamProcessor.ts:1
    - penguin-cli/src/ui/hooks/useStreaming.ts:1
  - Prevented crash on offline backend; better ECONNREFUSED message.
    - penguin-cli/src/ui/components/ChatSession.tsx:1
    - penguin-cli/src/ui/components/ConnectionStatus.tsx:1
- Design tokens and primitives
  - Semantic tokens (brand cyan/blue, status colors, spacing).
    - penguin-cli/src/ui/theme/tokens.ts:1
  - Panel primitive and unified Status panel (connection + progress + active tool).
    - penguin-cli/src/ui/components/Panel.tsx:1
    - penguin-cli/src/ui/components/StatusPanel.tsx:1
  - Integrated StatusPanel into Chat view.
    - penguin-cli/src/ui/components/ChatSession.tsx:1
- Event timeline foundation
  - Timeline event types and normalized tool event type.
    - penguin-cli/src/core/types.ts:1
  - Tool event store hook (idempotent, ordered by timestamp).
    - penguin-cli/src/ui/hooks/useToolEvents.ts:1
  - EventTimeline component: renders messages + live stream + compact tool completions.
    - penguin-cli/src/ui/components/EventTimeline.tsx:1
  - ChatSession now feeds `action_results` into normalized tool events and renders EventTimeline.
    - penguin-cli/src/ui/components/ChatSession.tsx:1
- Message list stability
  - Memoized message items to avoid redraw churn.
    - penguin-cli/src/ui/components/MessageList.tsx:1
- Housekeeping
  - Ignore local run/session artifacts.
    - .gitignore:1

### Design System (Initial)
- Tokens: `tokens.text`, `tokens.brand`, `tokens.status`, `tokens.border`, `tokens.spacing`, `tokens.icons`.
- Primitives: `Panel`, `StatusPanel`.
- Direction: clean utility look (banner → tabs → Status → Timeline → Composer). Later: theme manager inspired by Gemini’s semantic‑colors.

### Event Timeline & Tool Normalization
- Event kinds: `message`, `stream`, `tool`, `progress` (types defined).
- Tool normalization: `{ id, phase: 'start'|'update'|'end', action, ts, status, result }`.
- Current mapping: backend `action_results[]` → single `end` event per action; timeline shows compact, dimmed result lines.
- Active tool is shown in StatusPanel; completed results appear in the timeline and `ToolExecutionList`.

### Paging & Interaction
- Default: render last 50 timeline events; add paging hotkeys.
  - Proposal: `PgUp/↑` = show older; `PgDn/↓` = newer; `O` toggles “older” block.
  - Keep input focus behavior unchanged.

### Theming
- Default brand: cyan/blue. Later add light/ansi themes with a `themeManager` similar to Gemini.
- Tokens make the palette swappable without changing components.

### Testing Plan (Vitest + ink‑testing‑library)
- Streaming finalize: last token included; no flicker when complete; stream cleared only after final message is added.
- Tool event mapping: a list of `action_results` yields exactly one `end` event per action in chronological order.
- ECONNREFUSED: CLI does not crash and shows actionable error in Status.
- Pagination: rendering capped to 50, “older” hotkey reveals previous batch.

### Next Tasks (Short Horizon)
1) EventTimeline pagination window (50) with hotkeys and “N older events…” indicator.
2) Reasoning block collapsed by default with expander in assistant messages.
3) Full tool event pipeline: handle `start`/`update` from server; throttle updates to ~20 fps.
4) StatusPanel: add subtle progress bar line (re‑use ProgressIndicator logic under the hood).
5) Theme hook scaffolding for future user‑selectable themes.
6) Tests for the above; CI job for `npm -C penguin-cli test`.

### Backend Contract (Agreed Direction)
- Emit stable tool events during a run:
  {"type":"tool","id":"<stable-id>","phase":"start","action":"find_files","ts":1730180000000}
  {"type":"tool","id":"<stable-id>","phase":"update","action":"find_files","ts":1730180000500,"payload":"…"}
  {"type":"tool","id":"<stable-id>","phase":"end","action":"find_files","ts":1730180002000,"status":"completed","result":"…"}
- `action_results` remain as a fall‑back for `end` mapping (already supported).

### Acceptance Criteria
- No TTY jitter during streaming; messages never disappear on finalize.
- Status panel always visible; active tool and progress don’t shift the timeline.
- Tool completions appear once in correct order; duplicates de‑duped.
- Paging works with last‑50 default; hotkeys navigate older/newer batches.
- All components pull colors/spacing from tokens.
