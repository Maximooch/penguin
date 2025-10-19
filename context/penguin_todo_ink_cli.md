# Penguin Ink CLI Migration Plan

**Last Updated:** 2025-10-18
**Status:** Planning Phase
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
- **Latest Version:** 6.3.1 (actively maintained, updated 5 days ago)
- **Core Concept:** React renderer for terminal UIs using Yoga (Flexbox layouts)
- **TypeScript:** First-class support via `create-ink-app` template
- **React Compatibility:** Full support for hooks, functional components, lifecycle methods
- **Developer Tools:** React Devtools integration available

### Key Components
- `<Text>` - Styled text display (color, bold, italic, underline, wrapping)
- `<Box>` - Flexbox layout container (width, spacing, alignment)
- `useInput()` - Keyboard input handling
- `useApp()` - Application lifecycle management
- `useStdin/useStdout()` - Stream access
- `useFocus()` - Component focus management

### Ecosystem
- **Ink UI** - Pre-built components (TextInput, PasswordInput, Spinner, ProgressBar)
- **Pastel** - CSS-like styling API for terminal colors
- **Chalk** - Advanced color handling
- **Inquirer.js** - Interactive prompts (better than Python's questionary)

### WebSocket/Streaming Patterns
- Standard React patterns apply (useState, useEffect, useReducer)
- React Query integration for cache invalidation
- RTK Query for streaming updates
- **Key Pattern:** Use effect cleanup to prevent WebSocket recreation on every render

---

## Migration Phases

### Phase 1: Proof of Concept (Current Phase)
**Goal:** Validate Ink + FastAPI integration with basic chat

#### Tasks
- [x] Research Ink documentation
- [ ] Create `penguin-cli/` directory structure
- [ ] Initialize TypeScript project with Ink template
- [ ] Build WebSocket client connecting to `/api/v1/chat/stream`
- [ ] Implement basic chat UI:
  - User input component
  - Streaming response display
  - Basic styling with colors
- [ ] Compare DX with current Rich implementation

#### Success Criteria
- WebSocket connection works reliably
- Streaming text displays correctly
- Code is significantly simpler than Python version
- Performance is acceptable (< 100ms render updates)

---

### Phase 2: Core Features
**Goal:** Port main interactive session features

#### Tasks
- [ ] Streaming message display with buffering
- [ ] Syntax highlighting (use `highlight.js` or `prism.js`)
- [ ] Multi-line input handling (Ink's `useInput` + buffer)
- [ ] Tool execution display
- [ ] Progress indicators and spinners
- [ ] Error handling and retry logic
- [ ] Session state management

#### Components to Build
```typescript
<ChatSession />
  └─ <MessageList />
       ├─ <UserMessage />
       ├─ <AssistantMessage />
       │    ├─ <StreamingText />
       │    └─ <CodeBlock language="python" />
       └─ <ToolResult />
  └─ <InputPrompt />
```

---

### Phase 3: Advanced Features
**Goal:** Match feature parity with Python CLI

#### Tasks
- [ ] Subcommands (config, agent, project, task)
- [ ] Conversation management UI
- [ ] Setup wizard with Inquirer.js
- [ ] Context file handling
- [ ] Image support (via API)
- [ ] Multi-agent coordination UI
- [ ] Checkpoint/branching display
- [ ] Performance profiling commands

---

### Phase 4: Distribution & Polish
**Goal:** Production-ready release

#### Tasks
- [ ] Bundle backend + frontend (options: Docker, pkg, hybrid)
- [ ] Update installation instructions
- [ ] Write migration guide for users
- [ ] Performance optimization
- [ ] Accessibility testing (screen reader support)
- [ ] Cross-platform testing (macOS, Linux, Windows)
- [ ] Documentation updates

---

## Technical Decisions

### Distribution Strategy
- **Phase 1-2:** Separate install (Python backend + npm CLI)
  - User runs: `pip install penguin && npm install -g @penguin/cli`
  - Backend starts automatically when CLI launches
- **Phase 3+:** Bundled approach
  - Single binary with embedded backend (investigate `pkg` or `nexe`)
  - Or: Docker container with both runtimes

### Project Structure
```
penguin/
├── penguin/              # Python backend (existing)
│   ├── api/             # FastAPI server
│   ├── core.py          # PenguinCore logic
│   ├── tools/           # Tool implementations
│   └── llm/             # LLM adapters
├── penguin-cli/         # New TypeScript CLI
│   ├── src/
│   │   ├── components/  # Ink React components
│   │   ├── hooks/       # Custom React hooks
│   │   ├── api/         # WebSocket/REST client
│   │   └── index.tsx    # Entry point
│   ├── package.json
│   └── tsconfig.json
├── pyproject.toml
└── README.md
```

### State Management
- **Option A:** Plain React hooks (useState, useReducer) - Start here
- **Option B:** Zustand (lightweight, no Provider needed)
- **Option C:** React Query (if complex caching needed)

### WebSocket Client Pattern
```typescript
const useChat = (conversationId?: string) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [streaming, setStreaming] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    // Connect once
    wsRef.current = new WebSocket('ws://localhost:8000/api/v1/chat/stream');

    wsRef.current.onmessage = (event) => {
      const data = JSON.parse(event.data);
      // Handle streaming tokens
    };

    return () => wsRef.current?.close(); // Cleanup
  }, []); // Empty deps - connect once!

  const sendMessage = useCallback((text: string) => {
    wsRef.current?.send(JSON.stringify({ text, conversationId }));
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
   - Ink: Use `react-syntax-highlighter` (drop-in)

3. **Multi-line input** (prompt_toolkit integration)
   - Alt+Enter for newlines
   - Ink: Build custom hook with buffer

4. **Tool result display**
   - Buffering during streaming
   - Ink: Simple state array, map to components

---

## Open Questions

### Technical
- [ ] How to handle binary tool execution (shell commands)?
- [ ] Best way to display diffs in terminal (git-style)?
- [ ] Image display in terminal (Sixel/iTerm2 protocols)?
- [ ] How to package Python backend with Node CLI?

### UX
- [ ] Should we show a "backend starting..." message?
- [ ] How to handle backend crashes/restarts?
- [ ] Offline mode support?
- [ ] Multiple simultaneous sessions?

### Performance
- [ ] What's acceptable latency for WebSocket round-trip?
- [ ] Should we batch streaming tokens?
- [ ] Memory usage for long conversations?

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
- [Ink UI Components](https://github.com/vadimdemedes/ink-ui)
- [React DevTools Integration](https://github.com/facebook/react-devtools)
- [WebSocket + React Patterns](https://tkdodo.eu/blog/using-web-sockets-with-react-query)
- [Building CLIs with Ink (Medium)](https://medium.com/trabe/building-cli-tools-with-react-using-ink-and-pastel-2e5b0d3e2793)

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
