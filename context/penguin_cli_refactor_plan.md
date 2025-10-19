# Penguin CLI Refactoring Plan (Gemini-Inspired)

**Date:** 2025-10-19
**Status:** Ready to implement
**Reference:** [gemini_cli_analysis.md](./gemini_cli_analysis.md)

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

### Phase 1: Core Services ✅
- [ ] Create `src/core/` directory
- [ ] Move `ChatService` logic from `useChat` → `ChatService.ts`
- [ ] Move `StreamProcessor` logic → `StreamProcessor.ts`
- [ ] Move `WebSocketClient` → `core/connection/`
- [ ] Define shared types in `core/types.ts`

### Phase 2: React Contexts ✅
- [ ] Create `src/ui/contexts/` directory
- [ ] Implement `ConnectionContext`
- [ ] Implement `SessionContext`
- [ ] Implement `ConfigContext` (optional)

### Phase 3: Split Hooks ✅
- [ ] Create `src/ui/hooks/` directory (already exists)
- [ ] Extract `useWebSocket` from `useChat`
- [ ] Extract `useMessageHistory` from `useChat`
- [ ] Extract `useStreaming` from `useChat`
- [ ] Delete old `useChat` (no longer needed)

### Phase 4: Update UI ✅
- [ ] Wrap `App` with `ConnectionProvider` in `index.tsx`
- [ ] Wrap `App` with `SessionProvider`
- [ ] Update `ChatSession` to use new hooks
- [ ] Update `MessageList` to use contexts
- [ ] Update `InputPrompt` to use contexts
- [ ] Remove props drilling

### Phase 5: Testing ✅
- [ ] Install vitest + testing libraries
- [ ] Create `tests/` directory
- [ ] Write tests for `StreamProcessor`
- [ ] Write tests for `ChatService`
- [ ] Write tests for `WebSocketClient`
- [ ] Write component tests for `ChatSession`
- [ ] Set up CI testing (optional)

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

| Step | Time | Status |
|------|------|--------|
| 1. Create core services | 1-2h | ⬜ Not started |
| 2. Create React contexts | 30min | ⬜ Not started |
| 3. Split useChat hook | 1h | ⬜ Not started |
| 4. Update components | 1h | ⬜ Not started |
| 5. Add testing | 1-2h | ⬜ Not started |
| **Total** | **4-6h** | |

---

## Next Steps

1. **Review this plan** - Approve or request changes
2. **Refactor Phase 1** - Core services (1-2h)
3. **Refactor Phase 2** - Contexts (30min)
4. **Refactor Phase 3** - Hooks (1h)
5. **Test everything** - Ensure no regressions
6. **Update PHASE1_COMPLETE.md** - Document new architecture

---

## Success Criteria

✅ All existing functionality works
✅ Code is split into core/ and ui/
✅ useChat is split into 5 domain hooks
✅ Contexts eliminate props drilling
✅ At least 3 unit tests pass
✅ TypeScript compiles with no errors
✅ CLI still runs: `npm run dev`

---

**Ready to proceed?** This refactoring will set us up perfectly for Phase 2 features (tabs, syntax highlighting, tool display).
