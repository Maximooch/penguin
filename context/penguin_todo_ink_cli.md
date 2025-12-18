# Penguin Ink CLI Migration Plan

**Last Updated:** 2025-12-17
**Status:** Phase 2 - Active Development
**Goal:** Migrate Penguin's CLI from Python (Rich/Typer) to TypeScript + Ink (React for Terminal)

---

## Executive Summary

### Why Migrate?
1. **Better TUI/CLI ecosystem** - Ink offers React-like composability, Pastel for styling, better terminal widgets
2. **Existing API infrastructure** - FastAPI backend already supports REST + WebSocket streaming
3. **Developer Experience** - Declarative React components vs imperative Rich panels (200+ lines → ~30 lines)
4. **Modern tooling** - TypeScript, npm ecosystem, better async/streaming patterns

### Architecture
```
┌─────────────────────────┐
│  TypeScript CLI Client  │ ← Ink components (new)
│  (Terminal UI)          │
└──────────┬──────────────┘
           │ HTTP/WebSocket
┌──────────▼──────────────┐
│  Python Backend         │ ← Existing FastAPI server
│  (Core + API)           │ ← PenguinCore, tools, LLM logic
└─────────────────────────┘
```

---

## Research Findings

### Ink Library Overview
- **Latest Version:** 6.3.1 (released Sep 19, 2025)
- **Maintenance Status:** Transferred to Sindre Sorhus (May 2024), actively maintained
- **Core Concept:** React renderer for terminal UIs using Yoga (Flexbox layouts)
- **TypeScript:** First-class support via `npx create-ink-app --typescript`
- **React Compatibility:** Full support for hooks, functional components, lifecycle methods
- **Developer Tools:** React Devtools integration (`DEV=true` + `react-devtools-core`)

### Key Components
- `<Text>` - Styled text display (color, bold, italic, underline, wrapping)
- `<Box>` - Flexbox layout container (width, spacing, alignment)
- `useInput()` - Keyboard input handling
- `useApp()` - Application lifecycle management
- `useStdin/useStdout()` - Stream access
- `useFocus()` - Component focus management

### Ecosystem
- **Ink UI (`@inkjs/ui`)** - Official component library with inputs, spinners, progress bars, lists, and theming
- **Pastel** - Next.js-like framework for CLIs (filesystem-based commands, help generation, code-splitting)
- **Chalk** - Advanced color handling (terminal styling)
- **Community packages** - `ink-text-input`, `ink-table`, `ink-markdown`, `ink-syntax-highlight`, `ink-select-input`
- **Inquirer.js** - For classic Q&A prompts; prefer Ink UI input components to avoid TTY conflicts in active render cycles

### WebSocket/Streaming Patterns
- Standard React patterns apply (useState, useEffect, useReducer)
- React Query pattern: Use cache invalidation or `queryClient.setQueryData` on WS events
- RTK Query pattern: `onCacheEntryAdded` lifecycle for streaming updates
- **Key Pattern:** Use effect cleanup to prevent WebSocket recreation on every render
- **Node Version Note:** Node ≥22 has stable global `WebSocket`; Node 18/20 requires `npm i ws`

---

## Migration Phases

### Phase 1: Proof of Concept ✅ COMPLETE
**Goal:** Validate Ink + FastAPI integration with basic chat

#### Tasks
- [x] Research Ink documentation
- [x] Create `penguin-cli/` directory structure
- [x] Initialize TypeScript project with Ink template
- [x] Build WebSocket client connecting to `/api/v1/chat/stream`
- [x] Implement basic chat UI:
  - User input component (MultiLineInput)
  - Streaming response display
  - Basic styling with colors
- [x] Compare DX with current Rich implementation

#### Success Criteria ✅
- WebSocket connection works reliably
- Streaming text displays correctly
- Code is significantly simpler than Python version
- Performance is acceptable (< 100ms render updates)

---

### Phase 2: Core Features (IN PROGRESS)
**Goal:** Port main interactive session features

#### Tasks
- [x] Streaming message display with accumulator pattern (Static item freezing)
- [x] Markdown rendering component
- [x] Multi-line input handling (MultiLineInput component)
- [x] Tool execution display with phase-based indicators
- [x] Progress indicators
- [x] Error handling
- [x] Session state management (useChatState hook)
- [x] Major refactor - ChatSession reduced from 1,124 to ~470 lines
- [ ] Diff rendering using `diff` package + Chalk (git-style colored output)
- [ ] Backend crash detection and auto-restart with telemetry
- [ ] Conversation pagination (last 50 messages, "Load more" button)
- [ ] Syntax highlighting for code blocks

#### Component Hierarchy (Implemented)
```typescript
<ChatSession />
  └─ useChatState()        // Consolidated UI state
  └─ useChatAccumulator()  // Static/dynamic message split
  └─ useChatCommands()     // Command handling
  └─ useRunMode()          // Autonomous execution
  └─ <ChatMessageArea />
       ├─ <Static items={staticItems}>   // Frozen history (never re-renders)
       │    ├─ <UserMessage />
       │    ├─ <AssistantMessage />
       │    ├─ <ToolCallMessage phase="finished" />
       │    ├─ <ReasoningMessage />
       │    ├─ <ErrorMessage />
       │    └─ <StatusMessage />
       └─ {dynamicItems.map(...)}        // In-flight content
            ├─ <AssistantMessage phase="streaming" />
            └─ <ToolCallMessage phase="running" />
  └─ <MultiLineInput />
  └─ <StatusPanel />
  └─ Modal components...
```

---

### Phase 3: Advanced Features
**Goal:** Match feature parity with Python CLI

#### Tasks
- [ ] Subcommands (config, agent, project, task)
- [ ] Tab-based multi-session UI (see "Multiple Sessions" in Technical Decisions)
  - Basic 2-3 tab support with keyboard shortcuts
  - Session persistence across restarts
  - Active session indicator
- [ ] Setup wizard (prefer Ink UI components; use Inquirer.js outside active render if needed)
- [ ] Context file handling
- [ ] Image support using `ink-picture` (Kitty/iTerm2/Sixel/ASCII fallback)
- [ ] Multi-agent coordination UI (leverage existing `/api/v1/agents` endpoints)
- [ ] Checkpoint/branching display
- [ ] Performance profiling commands
- [ ] Offline mode for local models (Ollama detection and fallback)
- [ ] Full session dashboard with sidebar (Phase 3 extension of tab UI)

---

### Phase 4: Distribution & Polish
**Goal:** Production-ready release

#### Tasks
- [ ] Bundle backend + frontend
  - **Preferred:** Node SEA (Single Executable Applications) - built-in but CommonJS-only
  - **Alternative:** `nexe` or maintained `pkg` forks (`@yao-pkg/pkg`)
  - **Note:** `pkg` was archived by Vercel in Jan 2024
- [ ] Update installation instructions
- [ ] Write migration guide for users
- [ ] Performance optimization
- [ ] Accessibility testing (Ink screen reader support: `INK_SCREEN_READER=true`)
- [ ] Cross-platform testing (macOS, Linux, Windows)
- [ ] Documentation updates

---

## Patterns Learned from Letta-Code

**Reference:** [Letta Code CLI](https://github.com/letta-ai/letta-code) - Apache 2.0

### 1. Static Item Freezing (Critical for Performance)

**Problem:** Terminal flickering caused by full buffer redraws (see [claude-code issue #769](https://github.com/anthropics/claude-code/issues/769))

**Solution:** Use Ink's `<Static>` component for finished messages that never change.

```typescript
const [staticItems, setStaticItems] = useState<StaticItem[]>([]);
const [dynamicItems, setDynamicItems] = useState<Line[]>([]);

// Static items render ONCE and never re-render
<Static items={staticItems}>{renderItem}</Static>
// Dynamic items re-render normally during streaming
{dynamicItems.map(item => <MessageComponent key={item.id} item={item} />)}
```

**Commit Flow:**
1. Line starts as dynamic (streaming/running)
2. When finished, commit to staticItems
3. Remove from dynamicItems
4. Static never re-renders → no flickering

### 2. Accumulator Pattern for Transcript State

**Data Structure:** Dual-structure for efficient operations
```typescript
interface Buffers {
  order: string[];              // Maintains insertion order for rendering
  byId: Map<string, Line>;      // O(1) lookups and in-place updates
  toolCallIdToLineId: Map<string, string>;  // Correlates tool returns
  tokenCount: number;
  usage: UsageStats;
}
```

**Line Types:**
- `user` - User messages (always finished)
- `assistant` - AI responses (streaming → finished)
- `tool_call` - Tool executions (streaming → ready → running → finished)
- `reasoning` - Internal thinking (streaming → finished)
- `error` - Error messages
- `status` - System status updates
- `separator` - Visual separators

### 3. useSyncedState Hook

**Problem:** Stale closures in async callbacks (streaming, approvals)

**Solution:** Keep state and ref in sync
```typescript
function useSyncedState<T>(initialValue: T): [T, (v: T) => void, Ref<T>] {
  const [state, setState] = useState(initialValue);
  const ref = useRef(initialValue);

  const setSyncedState = useCallback((value: T) => {
    ref.current = value;  // Always current
    setState(value);       // Triggers re-render
  }, []);

  return [state, setSyncedState, ref];
}
```

### 4. Tool Phase Tracking

**Phases:** `streaming` → `ready` → `running` → `finished`

**Visual Indicators:**
- `.` streaming (parsing args)
- `?` ready (awaiting approval)
- `*` running (executing)
- `+` finished_ok
- `x` finished_error

### 5. Two-Column Layout

**Pattern:** Fixed 2-char gutter + flexible content
```typescript
const GUTTER_WIDTH = 2;

<Box flexDirection="row">
  <Box width={GUTTER_WIDTH} flexShrink={0}>
    <Text color={phaseColor}>{indicator}</Text>
  </Box>
  <Box flexGrow={1}>
    <Text wrap="wrap">{content}</Text>
  </Box>
</Box>
```

---

## Technical Decisions

### Distribution Strategy
- **Phase 1-2:** Separate processes
  - FastAPI runs via `uvicorn`, CLI via `node`
  - User runs: `pip install penguin && npm install -g @penguin/cli`
  - Backend starts automatically when CLI launches
- **Phase 3+:** Bundled approach
  - **Preferred:** Node SEA (Single Executable Applications) - bundle to single CJS file first
    - **Constraint:** CommonJS-only, requires esbuild/rollup preprocessing
  - **Fallback:** `nexe` or maintained `pkg` fork (`@yao-pkg/pkg`) if SEA limitations block
  - **Alternative:** Docker container with both runtimes

### Project Structure (Updated)
```
penguin/
├── penguin/                    # Python backend (existing)
│   ├── api/                   # FastAPI server
│   ├── core.py                # PenguinCore logic
│   ├── tools/                 # Tool implementations
│   └── llm/                   # LLM adapters
├── penguin-cli/               # TypeScript CLI
│   ├── src/
│   │   ├── core/
│   │   │   ├── accumulator/   # Transcript state management
│   │   │   │   ├── types.ts   # Line types, Buffers
│   │   │   │   ├── accumulator.ts
│   │   │   │   ├── stream.ts
│   │   │   │   └── index.ts
│   │   │   ├── api/           # REST clients (Session, Project, Run, Model)
│   │   │   ├── connection/    # WebSocket client
│   │   │   └── types.ts       # Domain types
│   │   ├── ui/
│   │   │   ├── components/
│   │   │   │   ├── messages/  # Message components (two-column layout)
│   │   │   │   │   ├── UserMessage.tsx
│   │   │   │   │   ├── AssistantMessage.tsx
│   │   │   │   │   ├── ToolCallMessage.tsx
│   │   │   │   │   ├── ReasoningMessage.tsx
│   │   │   │   │   ├── ErrorMessage.tsx
│   │   │   │   │   └── StatusMessage.tsx
│   │   │   │   ├── ChatSession.tsx      # ~470 lines (refactored)
│   │   │   │   ├── ChatMessageArea.tsx  # Static pattern
│   │   │   │   ├── MultiLineInput.tsx
│   │   │   │   ├── Markdown.tsx
│   │   │   │   └── ... modals, status
│   │   │   ├── hooks/
│   │   │   │   ├── useChatAccumulator.ts  # Static/dynamic split
│   │   │   │   ├── useChatState.ts        # UI state reducer
│   │   │   │   ├── useChatCommands.ts     # Command handling
│   │   │   │   ├── useRunMode.ts          # Autonomous execution
│   │   │   │   ├── useSyncedState.ts      # Async closure fix
│   │   │   │   └── useTerminalWidth.ts    # Reactive width
│   │   │   ├── contexts/      # React contexts
│   │   │   └── theme/         # Theme tokens
│   │   ├── config/            # Configuration loader
│   │   └── index.tsx          # Entry point
│   ├── package.json
│   └── tsconfig.json
├── pyproject.toml
└── README.md
```

### State Management (Implemented)

**Decision:** Hybrid approach with specialized hooks

1. **Accumulator Pattern** for transcript state
   - `useChatAccumulator` - manages Buffers with static/dynamic split
   - Order array + Map for O(1) updates
   - Static item freezing for performance

2. **useReducer** for UI state
   - `useChatState` - modal state, pagination, flags
   - Centralized dispatch for predictable updates

3. **Extracted domain hooks**
   - `useChatCommands` - command handling (~580 lines)
   - `useRunMode` - autonomous execution
   - `useSyncedState` - async closure safety

### WebSocket Client Pattern
```typescript
// Node 22+: global WebSocket is available
// Node 18/20: npm i ws && import WebSocket from 'ws'
const makeWS = (url: string) => {
  // @ts-expect-error allow global in Node 22+
  return typeof WebSocket !== 'undefined'
    ? new WebSocket(url)
    : new (require('ws'))(url);
};

const useChat = (conversationId?: string) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [streaming, setStreaming] = useState(false);
  const wsRef = useRef<any>(null);

  useEffect(() => {
    // Connect once
    wsRef.current = makeWS('ws://localhost:8000/api/v1/chat/stream');

    const handleMessage = (event: any) => {
      const data = JSON.parse(event.data ?? event);
      // Handle streaming tokens
    };

    wsRef.current.addEventListener?.('message', handleMessage);
    wsRef.current.on?.('message', handleMessage); // ws library

    return () => wsRef.current?.close?.(); // Cleanup
  }, []); // Empty deps - connect once!

  const sendMessage = useCallback((text: string) => {
    wsRef.current?.send?.(JSON.stringify({ text, conversationId }));
  }, [conversationId]);

  return { messages, streaming, sendMessage };
};
```

---

## Current Python CLI Pain Points (To Solve)

### From `penguin/cli/cli.py` Analysis
1. **Complex streaming logic** (lines 1900-3380)
   - Manual panel creation/updates
   - Buffer management for chronological ordering
   - Duplicate message prevention logic
   - Progress indicator cleanup

2. **Syntax highlighting** (20+ languages)
   - Rich's Syntax class works but verbose
   - Ink: Use `ink-syntax-highlight` (ANSI output, highlight.js under the hood)
   - `npm i ink-syntax-highlight` → `<SyntaxHighlight code={...} language="ts" />`

3. **Multi-line input** (prompt_toolkit integration)
   - Alt+Enter for newlines
   - Ink: Build custom hook with buffer

4. **Tool result display**
   - Buffering during streaming
   - Ink: Simple state array, map to components

---

## Technical Decisions (Resolved)

### Binary Tool Execution
**Decision:** Stream stdout/stderr in real-time using Ink's `useStdout` + `@inkjs/ui` Spinner.
- Display spinners during long-running commands
- Detect binary output and save to temp files, show path: "Saved: /tmp/output.png"
- Use `child_process.spawn` for streaming subprocess output

### Diff Display
**Decision:** Use standard ANSI diff approach with `diff` npm package + Chalk colorization.
```typescript
import { createPatch } from 'diff';
// Colorize: '+' lines → green, '-' lines → red, context → gray
```

### Image Display
**Decision:** Use `ink-picture` (auto-detects Kitty/iTerm2/Sixel/ASCII).
- Document that full image support requires compatible terminal
- Graceful fallback to ASCII art for unsupported terminals

### Packaging
**Decision:** Start with separate processes (Python backend + Node CLI).
- Backend starts automatically when CLI launches
- Show startup progress: "Starting Penguin backend on port 8000..."
- Bundle as single executable in Phase 4 using Node SEA

### Backend Lifecycle

**Startup Message:**
```
┌─────────────────────────────────┐
│ ⏳ Starting Penguin backend...  │
│ Port: 8000                       │
│ Status: Initializing models...   │
└─────────────────────────────────┘
```

**Crash Handling:**
1. **Crash Detection:** Monitor WebSocket close events (code !== 1000)
2. **Crash Summary:** Display crash panel with:
   - Error code/reason
   - Last successful message
   - Timestamp
   - Stack trace (if available)
3. **Telemetry:** Send crash report to `/api/v1/telemetry/crash`
4. **Auto-restart:** Attempt backend restart with exponential backoff
5. **Session Resume:** Reconnect to last `conversation_id` after restart

```typescript
wsRef.current.on('close', (code, reason) => {
  if (code !== 1000) {
    setCrashInfo({ code, reason, lastMessage, timestamp });
    sendCrashTelemetry({ code, reason, conversationId });
    restartBackend(); // With backoff: 1s, 2s, 4s, 8s...
  }
});
```

### Offline Mode
**Decision:** Phase 3 feature for local model support (Ollama, etc.).
- Detect backend unreachable → check for local endpoints
- Switch to "local mode" with reduced features (no memory search, basic tools)
- Clear "Backend offline" error in Phase 1-2

### Multiple Sessions (Tab-Based UI)
**Decision:** Implement tab-based session management leveraging existing multi-agent support.

**Design:**
```
┌─────────────────────────────────────────────────┐
│ [1: default] [2: research*] [3: planner] [+]   │ ← Tab bar
├─────────────────────────────────────────────────┤
│ research (Agent: research, Conv: abc-123)       │
│ ────────────────────────────────────────────    │
│ > Summarize latest changelog                    │
│ 📝 Analyzing 15 commits...                      │
│                                                  │
│ [Type message or Ctrl+Tab to switch]            │
└─────────────────────────────────────────────────┘
```

**Implementation:**
- Each tab = unique `conversation_id` + optional `agent_id`
- Sessions persist in `WORKSPACE_PATH/conversations/*.json`
- Keyboard shortcuts:
  - `Ctrl+T`: New session
  - `Ctrl+W`: Close session
  - `Ctrl+Tab`/`Ctrl+Shift+Tab`: Next/previous session
  - `Ctrl+1-9`: Jump to session N
- Active session indicated by `*` in tab label

**Phase 2 Task:** Basic 2-3 tab support
**Phase 3 Task:** Full multi-session dashboard with session list sidebar

### Performance Targets

**Latency:**
- WebSocket round-trip (localhost): **<10ms**
- First token from LLM: **100-500ms** (model-dependent)
- UI render update: **<16ms** (60 FPS)
- **Total:** User presses Enter → first token visible: **<200ms** (excluding model thinking time)

**Token Streaming:**
**Decision:** Micro-batching strategy for smooth rendering.
```typescript
// Buffer tokens for 50ms or 5 tokens, whichever comes first
let buffer = '';
let flushTimeout: NodeJS.Timeout;

ws.on('message', (token) => {
  buffer += token;
  clearTimeout(flushTimeout);

  if (buffer.length >= 5) { // 5-token batch
    setStreamingText(prev => prev + buffer);
    buffer = '';
  } else { // or 50ms timeout
    flushTimeout = setTimeout(() => {
      setStreamingText(prev => prev + buffer);
      buffer = '';
    }, 50);
  }
});
```

Later on try to have its max be 100-500 tokens per second. Because 5 tps can be extremely slow


**Conversation Pagination:**
**Decision:** Virtualized rendering with 100-message chunks.
- **Phase 1-2:** Show last 50 messages, "Load more" button
- **Phase 3:** Implement virtualization (only render visible viewport)
  - Load 100-message chunks on scroll
  - Store full conversation in memory
  - Use `react-window` or custom virtualization

**Memory Management:**
- Conversations > 10,000 messages → paginate from backend
- Each session limited to 1000 messages in memory
- Older messages lazy-loaded from `conversations/*.json`

---

## Success Metrics

### Phase 1 (PoC)
- [ ] WebSocket streaming works without dropped messages
- [ ] Code is < 50% the size of Python equivalent
- [ ] Render performance: < 100ms for typical message
- [ ] Developer verdict: "This is way better"

### Final Release
- [ ] Feature parity with Python CLI
- [ ] < 2s cold start time (including backend)
- [ ] Works on macOS, Linux, Windows
- [ ] Positive user feedback on DX improvement
- [ ] Installation is single command (or close to it)

---

## Next Steps (Immediate)

1. ✅ Research Ink documentation
2. 🔄 Create this planning document
3. ⬜ Initialize `penguin-cli/` with `create-ink-app`
4. ⬜ Build hello-world WebSocket test
5. ⬜ Implement basic chat message display
6. ⬜ Compare with Python version, gather team feedback

---

## References

- [Ink GitHub](https://github.com/vadimdemedes/ink)
- [Ink UI Components (`@inkjs/ui`)](https://github.com/vadimdemedes/ink-ui)
- [Pastel CLI Framework](https://github.com/vadimdemedes/pastel)
- [ink-syntax-highlight](https://github.com/vsashyn/ink-syntax-highlight)
- [ink-picture (terminal images)](https://github.com/endernoke/ink-picture)
- [Node SEA Documentation](https://nodejs.org/api/single-executable-applications.html)
- [Node 22 WebSocket API](https://blog.appsignal.com/2024/05/07/whats-new-in-nodejs-22.html)
- [React DevTools Integration](https://github.com/facebook/react-devtools)
- [WebSocket + React Query Patterns](https://tkdodo.eu/blog/using-web-sockets-with-react-query)
- [Moving on from Ink (Vadim's announcement)](https://vadimdemedes.com/posts/moving-on-from-ink)

---

## Appendix: Code Size Comparison

### Current Python CLI (Rich)
```python
# penguin/cli/cli.py - Streaming display logic
# ~480 lines for PenguinCLI class
# Manual panel management, buffer tracking, progress cleanup
```

### Proposed Ink CLI (React)
```typescript
// Equivalent streaming display (estimated)
// ~80-100 lines with hooks + components
// Declarative, React handles updates
```

**Expected reduction:** 70-80% less code for same features
