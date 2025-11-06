# Penguin TypeScript CLI Track - Implementation Plan

**Objective:** Refactor existing TypeScript CLI using Gemini-CLI patterns to improve architecture and compare against Python approach

**Duration:** 4-6 hours of focused refactoring

**Context:** This is Track 2 of a parallel implementation experiment. Track 1 is building a new Python CLI with Kimi patterns. We'll compare both approaches to make a data-driven decision.

**Reference Documents:**
- [Gemini-CLI Analysis](./context/gemini_cli_architecture_analysis.md)
- [Reference Comparison](./penguin-cli/docs/reference-comparison.md)
- [Current Penguin Architecture](./penguin-cli/docs/cli-architecture.md)

---

## Success Criteria

By the end of this refactoring, we should have:

✅ **Improved TypeScript CLI** that has:
- Decomposed ChatSession (currently 1,126 lines → <300 lines each component)
- Zustand state management (replacing React Context)
- Fixed session switching bug
- Single WebSocket connection source
- Error boundaries
- Improved performance (memoization, MaxSizedBox pattern)

✅ **Evaluation Document** (`evaluation_typescript.md`) with:
- Refactoring velocity notes
- Before/after comparisons
- Gemini patterns that helped
- Performance improvements
- Subjective "feel" assessment

✅ **Comparison-ready** codebase:
- Clean git history (atomic commits)
- Performance benchmarks
- Documented improvements

---

## Current State Analysis

**Existing Issues (from cli-architecture.md):**
- 🔴 ChatSession.tsx is 1,126 lines (monolithic)
- 🔴 Duplicate WebSocket connections (ConnectionContext + ChatSession)
- 🔴 Session switching bug (useRef in dependency array)
- 🔴 No error boundaries
- ⚠️ Uncoordinated batch timers (50ms, 100ms, 100ms)
- ⚠️ No memoization
- ⚠️ Type safety issues (excessive `any` types)

**Current Structure:**
```
penguin-cli/src/
├── ui/
│   ├── contexts/
│   │   ├── ConnectionContext.tsx    # WebSocket management
│   │   ├── SessionContext.tsx
│   │   └── TabContext.tsx
│   ├── components/
│   │   ├── ChatSession.tsx          # 1,126 lines! 🔴
│   │   ├── EventTimeline.tsx
│   │   └── [30+ other components]
│   └── hooks/
│       ├── useMessageHistory.ts
│       ├── useStreaming.ts
│       └── [8+ other hooks]
└── core/
    ├── api/                          # API clients
    ├── chat/                         # StreamProcessor
    └── commands/                     # CommandRegistry
```

---

## Phase 1: Setup & Evaluation Document (15 min)

### 1. Create Evaluation Document

Create `evaluation_typescript.md`:

```markdown
# TypeScript CLI Track - Evaluation Log

## Initial Assessment
- Starting point: Existing penguin-cli
- Major issues:
  - ChatSession: 1,126 lines
  - Duplicate WebSocket
  - Session switch bug
- Key improvements planned:
  - Decompose ChatSession
  - Adopt Zustand
  - Fix bugs

## Refactoring Log

### [Date/Time]
**Working on:** [feature]
**Status:** [in progress/blocked/completed]
**Before:** [measurements]
**After:** [measurements]
**Notes:**
-

---

## Final Metrics (fill at end)

### Code Metrics
**Before:**
- ChatSession: 1,126 lines
- Contexts: 4 providers
- Total LOC: ~10K

**After:**
- Largest component: X lines
- State management: Zustand
- Total LOC: X

### Performance
**Before:**
- Startup time: ? ms
- Memory usage: ? MB
- Render frequency: ? Hz

**After:**
- Startup time: X ms
- Memory usage: X MB
- Render frequency: X Hz

### Development Velocity
- Time to decompose ChatSession: X hours
- Time to migrate to Zustand: X hours
- Time to add error boundaries: X hours
- Total time: X hours

### Subjective Assessment (1-5)
- Refactoring experience: ?/5
- Gemini patterns helpfulness: ?/5
- Code organization improvement: ?/5
- TypeScript ecosystem: ?/5
- Overall satisfaction: ?/5

### Key Insights
1.
2.
3.

### Recommendation
- [ ] Continue with TypeScript track
- [ ] Switch to Python track
- [ ] Keep both
```

### 2. Create Feature Branch

```bash
cd penguin-cli
git checkout -b refactor/gemini-patterns
```

### 3. Install Additional Dependencies

```bash
npm install zustand immer
npm install -D @types/react-test-renderer
```

---

## Phase 2: Fix Critical Bugs (45-60 min)

### 1. Fix Session Switching Bug (15 min)

**Issue:** `ConnectionContext.tsx` uses `useRef` in dependency array

**Current (BROKEN):**
```typescript
// ConnectionContext.tsx
const conversationId = useRef<string | undefined>();

useEffect(() => {
  const client = new ChatClient({ conversationId: conversationId.current });
  // ...
}, [url, conversationId.current]); // ⚠️ Doesn't trigger re-run!
```

**Fix:**
```typescript
// ConnectionContext.tsx
const [conversationId, setConversationId] = useState<string | undefined>();

useEffect(() => {
  const client = new ChatClient({ conversationId });
  // ...
}, [url, conversationId]); // ✅ Now triggers correctly

// Export setter
return (
  <ConnectionContext.Provider value={{
    ...state,
    setConversationId  // Add this
  }}>
```

**Test:** Switch sessions, verify WebSocket reconnects

**Update evaluation_typescript.md:** Time taken, whether fix was straightforward

### 2. Remove Duplicate WebSocket Client (30 min)

**Issue:** ChatSession creates its own ChatClient instead of using ConnectionContext

**Find all instances:**
```typescript
// ChatSession.tsx
const clientRef = useRef<any>(null);

useEffect(() => {
  const client = new ChatClient(...);  // ⚠️ DUPLICATE!
  clientRef.current = client;
}, [conversationId]);
```

**Fix:**
```typescript
// ChatSession.tsx
const { client } = useConnection(); // Use context client

useEffect(() => {
  if (!client) return;

  // Register callbacks
  client.onToken = handleToken;
  client.onProgress = handleProgress;
  client.onToolEvent = handleToolEvent;

  return () => {
    // Cleanup callbacks
    client.onToken = undefined;
    // ...
  };
}, [client]);
```

**Test:** Verify single WebSocket connection, streaming still works

**Update evaluation_typescript.md:** Challenges, how much code removed

### 3. Add Error Boundaries (15 min)

**Create:** `ui/components/ErrorBoundary.tsx`

```typescript
import React, { Component, ReactNode } from 'react';
import { Box, Text } from 'ink';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('Error boundary caught:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <Box flexDirection="column" padding={1}>
          <Text color="red" bold>An error occurred:</Text>
          <Text>{this.state.error?.message}</Text>
          <Text color="yellow">Press Ctrl+C to exit</Text>
        </Box>
      );
    }

    return this.props.children;
  }
}
```

**Wrap App:**
```typescript
// App.tsx
<ErrorBoundary>
  <App />
</ErrorBoundary>
```

---

## Phase 3: Migrate to Zustand (60-75 min)

### Goal: Replace React Context with Zustand (Gemini pattern)

### 1. Create Zustand Store (`ui/store/index.ts`)

```typescript
import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';

interface Message {
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
}

interface ToolEvent {
  id: string;
  phase: 'start' | 'update' | 'end';
  // ...
}

interface AppState {
  // Connection
  isConnected: boolean;
  conversationId?: string;

  // Messages
  messages: Message[];
  streamingText: string;
  isStreaming: boolean;

  // Tool events
  toolEvents: ToolEvent[];

  // Progress
  iteration: number;
  maxIterations: number;

  // Session
  currentSession?: {
    id: string;
    conversationId: string;
  };

  // Actions
  addMessage: (message: Message) => void;
  appendStreamingText: (text: string) => void;
  addToolEvent: (event: ToolEvent) => void;
  setProgress: (iteration: number, max: number) => void;
  switchConversation: (conversationId: string) => void;
  reset: () => void;
}

export const useStore = create<AppState>()(
  immer((set) => ({
    // Initial state
    isConnected: false,
    messages: [],
    streamingText: '',
    isStreaming: false,
    toolEvents: [],
    iteration: 0,
    maxIterations: 0,

    // Actions
    addMessage: (message) => set((state) => {
      state.messages.push(message);
    }),

    appendStreamingText: (text) => set((state) => {
      state.streamingText += text;
      state.isStreaming = true;
    }),

    addToolEvent: (event) => set((state) => {
      state.toolEvents.push(event);
    }),

    setProgress: (iteration, max) => set((state) => {
      state.iteration = iteration;
      state.maxIterations = max;
    }),

    switchConversation: (conversationId) => set((state) => {
      state.conversationId = conversationId;
      state.messages = [];
      state.streamingText = '';
      state.toolEvents = [];
    }),

    reset: () => set((state) => {
      state.messages = [];
      state.streamingText = '';
      state.toolEvents = [];
      state.iteration = 0;
    }),
  }))
);
```

### 2. Migrate Hooks to Use Zustand

**Before (useMessageHistory):**
```typescript
export function useMessageHistory() {
  const [messages, setMessages] = useState<Message[]>([]);
  // ... batching logic
}
```

**After:**
```typescript
// Just use Zustand directly!
const messages = useStore((state) => state.messages);
const addMessage = useStore((state) => state.addMessage);

// No batching needed - Zustand handles efficiently
```

### 3. Migrate Components

**Example: ChatSession**

**Before:**
```typescript
const { messages } = useMessageHistory();
const { streamingText } = useStreaming();
const { toolEvents } = useToolEvents();
```

**After:**
```typescript
const messages = useStore((state) => state.messages);
const streamingText = useStore((state) => state.streamingText);
const toolEvents = useStore((state) => state.toolEvents);
```

### 4. Remove Old Contexts

Once migrated, remove:
- `SessionContext.tsx` (if fully replaced)
- Hook files that are now redundant

**Update evaluation_typescript.md:**
- Was Zustand easier than Context?
- Code reduction?
- Performance impact?

---

## Phase 4: Decompose ChatSession (90-120 min)

### Goal: Split 1,126-line component into smaller pieces

### Current Structure Analysis

ChatSession does:
1. **WebSocket management** (lines 50-120) → Already moving to ConnectionContext
2. **Message display** (lines 150-300) → Extract to `<ChatOutput>`
3. **Tool execution display** (lines 320-450) → Extract to `<ToolPanel>`
4. **Input handling** (lines 500-650) → Extract to `<ChatInput>`
5. **Session management UI** (lines 700-800) → Extract to `<SessionManager>`
6. **Model selection UI** (lines 820-900) → Extract to `<ModelManager>`
7. **Settings UI** (lines 920-1000) → Extract to `<SettingsManager>`

### 1. Create Component Structure

```bash
mkdir -p ui/components/chat/{output,input,panels,modals}
```

### 2. Extract ChatOutput Component

**Create:** `ui/components/chat/output/ChatOutput.tsx`

```typescript
import React, { memo } from 'react';
import { Box } from 'ink';
import { useStore } from '../../../store';
import { EventTimeline } from '../../EventTimeline';
import { StatusPanel } from './StatusPanel';

export const ChatOutput = memo(function ChatOutput() {
  const messages = useStore((state) => state.messages);
  const streamingText = useStore((state) => state.streamingText);
  const toolEvents = useStore((state) => state.toolEvents);
  const { iteration, maxIterations } = useStore((state) => ({
    iteration: state.iteration,
    maxIterations: state.maxIterations,
  }));

  return (
    <Box flexDirection="column" flexGrow={1}>
      <EventTimeline
        messages={messages}
        streamingText={streamingText}
        toolEvents={toolEvents}
      />
      <StatusPanel iteration={iteration} maxIterations={maxIterations} />
    </Box>
  );
});
```

### 3. Extract ChatInput Component

**Create:** `ui/components/chat/input/ChatInput.tsx`

```typescript
import React, { useState } from 'react';
import { Box } from 'ink';
import { MultiLineInput } from '../../MultiLineInput';
import { useStore } from '../../../store';
import { useConnection } from '../../../contexts/ConnectionContext';

export function ChatInput() {
  const [input, setInput] = useState('');
  const { client } = useConnection();
  const addMessage = useStore((state) => state.addMessage);

  const handleSubmit = async () => {
    if (!input.trim() || !client) return;

    // Add user message
    addMessage({
      role: 'user',
      content: input,
      timestamp: Date.now(),
    });

    // Send to backend
    client.sendMessage(input);

    setInput('');
  };

  return (
    <Box flexDirection="column">
      <MultiLineInput
        value={input}
        onChange={setInput}
        onSubmit={handleSubmit}
      />
    </Box>
  );
}
```

### 4. Extract Modal Components

**SessionManager, ModelManager, SettingsManager** - similar extraction pattern

### 5. Update Main ChatSession

**After extraction:**

```typescript
// ChatSession.tsx (now ~100 lines!)
import React from 'react';
import { Box } from 'ink';
import { ChatOutput } from './chat/output/ChatOutput';
import { ChatInput } from './chat/input/ChatInput';
import { SessionManager } from './chat/modals/SessionManager';
import { ModelManager } from './chat/modals/ModelManager';
import { SettingsManager } from './chat/modals/SettingsManager';

export function ChatSession() {
  const [showSettings, setShowSettings] = useState(false);
  const [showSessions, setShowSessions] = useState(false);
  const [showModels, setShowModels] = useState(false);

  return (
    <Box flexDirection="column" height="100%">
      <ChatOutput />
      <ChatInput />

      {showSettings && <SettingsManager onClose={() => setShowSettings(false)} />}
      {showSessions && <SessionManager onClose={() => setShowSessions(false)} />}
      {showModels && <ModelManager onClose={() => setShowModels(false)} />}
    </Box>
  );
}
```

**Update evaluation_typescript.md:**
- Time to decompose
- Was it straightforward?
- Component sizes after split
- Testing burden

---

## Phase 5: Performance Optimizations (45-60 min)

### Goal: Apply Gemini patterns for better performance

### 1. Add MaxSizedBox Component (Gemini pattern)

**Create:** `ui/components/common/MaxSizedBox.tsx`

```typescript
import React, { ReactNode, useMemo } from 'react';
import { Box } from 'ink';

interface Props {
  children: ReactNode[];
  maxHeight?: number;
}

export function MaxSizedBox({ children, maxHeight = 30 }: Props) {
  const visibleChildren = useMemo(() => {
    if (children.length <= maxHeight) {
      return children;
    }
    return children.slice(-maxHeight);
  }, [children, maxHeight]);

  return (
    <Box flexDirection="column">
      {visibleChildren}
    </Box>
  );
}
```

**Use in EventTimeline:**
```typescript
<MaxSizedBox maxHeight={30}>
  {messages.map((msg) => (
    <MessageRow key={msg.id} message={msg} />
  ))}
</MaxSizedBox>
```

### 2. Add Memoization

**Memoize EventTimeline:**
```typescript
import { memo } from 'react';

export const EventTimeline = memo(
  function EventTimeline({ messages, toolEvents }: Props) {
    // ... component logic
  },
  (prev, next) => {
    // Custom equality check
    return (
      prev.messages.length === next.messages.length &&
      prev.messages[prev.messages.length - 1] === next.messages[next.messages.length - 1] &&
      prev.toolEvents.length === next.toolEvents.length
    );
  }
);
```

**Memoize MessageRow:**
```typescript
export const MessageRow = memo(
  function MessageRow({ message }: Props) {
    // ... component logic
  },
  (prev, next) => prev.message.id === next.message.id
);
```

### 3. Coordinate Batch Timers

**Create:** `ui/hooks/useBatchScheduler.ts`

```typescript
import { useEffect, useRef } from 'react';

export function useBatchScheduler(callback: () => void, delay: number = 50) {
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);
  const callbackRef = useRef(callback);

  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  const schedule = () => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }

    timeoutRef.current = setTimeout(() => {
      callbackRef.current();
      timeoutRef.current = null;
    }, delay);
  };

  return schedule;
}
```

**Use in multiple places with same delay** (50ms for all)

### 4. Benchmark Performance

**Create:** `benchmark.ts`

```typescript
import { performance } from 'perf_hooks';

const start = performance.now();

// ... app startup

console.log(`Startup time: ${performance.now() - start}ms`);

// Memory
console.log(`Memory: ${process.memoryUsage().rss / 1024 / 1024}MB`);
```

**Update evaluation_typescript.md:**
- Before/after startup time
- Before/after memory
- Perceived smoothness

---

## Phase 6: Type Safety Improvements (30-45 min)

### Goal: Remove `any` types, add discriminated unions

### 1. Define Proper Types

**Create:** `shared/types/events.ts`

```typescript
// Discriminated union for events
export type StreamEvent =
  | { type: 'token'; data: { token: string } }
  | { type: 'progress'; data: { iteration: number; max: number } }
  | { type: 'tool'; data: ToolEvent }
  | { type: 'complete'; data: { action_results: ActionResult[] } };

export interface ToolEvent {
  id: string;
  phase: 'start' | 'update' | 'end';
  action: string;
  timestamp: number;
  status?: 'running' | 'success' | 'error';
  result?: string;
}
```

### 2. Replace `any` in ChatClient

**Before:**
```typescript
const clientRef = useRef<any>(null);
```

**After:**
```typescript
import { ChatClient } from '../../core/connection/WebSocketClient';
const clientRef = useRef<ChatClient | null>(null);
```

### 3. Add Type Guards

```typescript
export function isToolEvent(event: unknown): event is ToolEvent {
  return (
    typeof event === 'object' &&
    event !== null &&
    'id' in event &&
    'phase' in event &&
    ['start', 'update', 'end'].includes((event as ToolEvent).phase)
  );
}
```

**Update evaluation_typescript.md:**
- Type errors caught during refactoring?
- TypeScript helpfulness?

---

## Phase 7: Testing & Documentation (30-45 min)

### 1. Add Basic Tests

**Create:** `ui/components/chat/ChatOutput.test.tsx`

```typescript
import React from 'react';
import { render } from 'ink-testing-library';
import { ChatOutput } from './output/ChatOutput';

describe('ChatOutput', () => {
  it('renders messages', () => {
    const { lastFrame } = render(<ChatOutput />);
    expect(lastFrame()).toContain('...');
  });
});
```

### 2. Update README

Document changes:
- Architecture improvements
- Gemini patterns adopted
- Performance improvements
- Breaking changes (if any)

### 3. Create Migration Guide

**Create:** `MIGRATION.md`

```markdown
# Migration Guide: Gemini Patterns Refactoring

## Changes

### State Management
- **Before:** React Context (4 providers)
- **After:** Zustand (single store)
- **Migration:** Import `useStore` instead of context hooks

### Component Structure
- **Before:** ChatSession (1,126 lines)
- **After:** Split into 6 components
- **Migration:** No API changes, internal refactoring

### Bug Fixes
- Fixed: Session switching now works correctly
- Fixed: Single WebSocket connection source
- Added: Error boundaries

### Performance
- Added: MaxSizedBox for render limiting
- Added: Memoization for expensive components
- Added: Coordinated batch timers
```

---

## Phase 8: Evaluation & Comparison (30 min)

### 1. Complete evaluation_typescript.md

Fill in all sections:
- Final metrics (before/after)
- Subjective assessments
- Key insights
- Comparison points

### 2. Create Visual Comparison

Add to evaluation:

```markdown
## Before vs After

### Code Metrics
```
Before: ChatSession.tsx      1,126 lines
After:  ChatSession.tsx        100 lines
        ChatOutput.tsx         150 lines
        ChatInput.tsx          120 lines
        SessionManager.tsx     180 lines
        ModelManager.tsx       150 lines
        SettingsManager.tsx    150 lines
        (Other utilities)      ~100 lines
Total:                         950 lines (16% reduction!)
```

### Component Tree
**Before:**
```
App
└── ChatSession (1,126 lines)
    ├── Everything mixed together
    └── Hard to maintain
```

**After:**
```
App
└── ChatSession (100 lines)
    ├── ChatOutput (150 lines)
    ├── ChatInput (120 lines)
    └── Modals (3x ~150 lines)
```

### State Management
**Before:**
```
Context nesting (5 providers)
├── ThemeProvider
├── CommandProvider
├── TabProvider
├── ConnectionProvider
└── SessionProvider
```

**After:**
```
Zustand (single store)
├── Selective subscriptions
└── Better performance
```
```

### 3. Commit Changes

```bash
git add .
git commit -m "Refactor: Apply Gemini patterns

- Decompose ChatSession (1,126 → 100 lines)
- Migrate to Zustand state management
- Fix session switching bug
- Add error boundaries
- Add performance optimizations (MaxSizedBox, memoization)
- Improve type safety (remove any types)"
```

---

## Deliverables Checklist

At the end, you should have:

- [ ] ChatSession decomposed (<300 lines per component)
- [ ] Zustand state management working
- [ ] Session switching bug fixed
- [ ] Single WebSocket connection
- [ ] Error boundaries added
- [ ] Performance optimizations applied
- [ ] Type safety improved
- [ ] evaluation_typescript.md completed with:
  - [ ] Before/after metrics
  - [ ] Performance benchmarks
  - [ ] Gemini patterns assessment
  - [ ] Comparison points ready
- [ ] Tests passing
- [ ] Documentation updated
- [ ] Clean git history

---

## Troubleshooting Guide

### Issue: Zustand store not updating UI
**Solution:**
```typescript
// Make sure you're selecting state correctly
const messages = useStore((state) => state.messages); // ✅
const { messages } = useStore(); // ❌ Won't update
```

### Issue: TypeScript errors after decomposition
**Solution:** Check imports, may need to re-export types

### Issue: Ink rendering issues after refactoring
**Solution:** Check Box flexGrow/flexShrink props

### Issue: Tests failing after migration
**Solution:** Mock Zustand store in tests

### Issue: Performance worse after changes
**Solution:**
- Check memo equality functions
- Verify MaxSizedBox limits
- Profile with React DevTools

---

## Notes for Autonomous Execution

**If you're a Claude instance executing this plan:**

1. **Create evaluation_typescript.md FIRST** and update as you go
2. **Commit frequently** - atomic commits for each phase
3. **Test after each change** - don't break existing functionality
4. **Compare to Gemini** - reference analysis doc frequently
5. **Measure before/after** - get baseline metrics first
6. **Document decisions** - why Gemini pattern X helped/didn't help
7. **Be honest about challenges** - document what was hard

**Success = Working refactored CLI + Honest evaluation**

Not: Perfect architecture + No issues documented

---

## Gemini Patterns Reference

Quick reference from analysis:

1. **Zustand over Context** - Simpler, more performant
2. **MaxSizedBox** - Limit render scope
3. **Custom equality checks** - Optimize memo()
4. **Discriminated unions** - Better type safety
5. **Coordinated batching** - Single timer for updates
6. **Component decomposition** - <300 lines per component
7. **Error boundaries** - Catch and display errors
8. **Memoization** - Expensive components
9. **Type guards** - Runtime type validation
10. **Testing** - Unit + integration

---

## Final Notes

This is a **refactoring experiment**, not a rewrite. The goal is **evaluating Gemini patterns** and **comparing to Python approach**.

Focus on:
✅ Applying proven patterns
✅ Measuring improvements
✅ Honest evaluation

Don't worry about:
❌ Perfect implementation
❌ 100% test coverage
❌ Every single Gemini pattern

**Time budget: 4-6 hours max**

If something takes >30 min with no progress, document it as a challenge and move on.

Good luck! 🐧⚛️
