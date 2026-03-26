# Gemini CLI Architecture Analysis

**Date:** 2025-10-19
**Purpose:** Analyze Google's Gemini CLI as a reference for Penguin's Ink CLI migration

---

## Overview

### Scale
- **Total Lines**: ~115,500 lines of TypeScript
- **Packages**: 5 monorepo packages (cli, core, a2a-server, vscode-ide-companion, test-utils)
- **Maturity**: Production-ready with extensive testing (vitest), IDE integration, A2A server

### Technology Stack
```json
{
  "framework": "Ink 6.2.3 (React 19.1.0)",
  "testing": "vitest + ink-testing-library",
  "architecture": "Monorepo with workspace packages",
  "node": ">=20",
  "type": "module (ESM)",
  "cli": "yargs (not commander)"
}
```

---

## Package Structure

### 1. `packages/cli` - Main CLI Application
**Dependencies highlights:**
- `ink`: 6.2.3 + `ink-gradient`, `ink-spinner`
- `lowlight`: Syntax highlighting (vs. our `highlight.js`)
- `diff`: Same as ours
- `fzf`: Fuzzy finder integration
- `@modelcontextprotocol/sdk`: MCP support
- `yargs`: CLI arg parsing
- `zod`: Schema validation
- `update-notifier`: Auto-update checks

**Key directories:**
```
src/
├── commands/          # Slash commands (/auth, /chat, /clear, etc.)
│   ├── extensions/    # Extension management
│   └── mcp/           # MCP integration
├── config/            # Config system (multi-layered like ours)
│   ├── settings.ts    # Settings schema with Zod
│   ├── keyBindings.ts # Custom keybindings
│   ├── policy.ts      # Policy engine
│   └── extensions/    # Extension config
├── core/              # Core initialization
├── services/          # Business logic
│   ├── CommandService.ts
│   ├── FileCommandLoader.ts
│   └── prompt-processors/  # @file, shell, argument injection
├── ui/                # Ink components (HUGE - 82 files!)
│   ├── components/    # 82 component files
│   ├── hooks/         # 82 custom hooks
│   ├── contexts/      # 15 React contexts
│   ├── commands/      # UI-level slash commands
│   ├── themes/        # 23 theme files
│   └── utils/
└── test-utils/        # Testing utilities
```

### 2. `packages/core` - Business Logic Layer
**Purpose:** Separates platform-agnostic logic from UI

**Dependencies highlights:**
- `@google/genai`: Gemini API client
- `@modelcontextprotocol/sdk`: MCP protocol
- `@xterm/headless`: Terminal emulation
- `node-pty` (optional): PTY for shell execution
- `ripgrep`: Fast file search
- `ws`: WebSocket client
- OpenTelemetry stack: Tracing, metrics, logging

**Architecture pattern:**
```
core/ (business logic)
  ↓
cli/ (UI layer with Ink)
```

This is EXACTLY what we should do for Penguin!

### 3. `packages/a2a-server` - Agent-to-Agent Server
API server for agent communication (similar to our FastAPI backend)

### 4. `packages/vscode-ide-companion` - IDE Extension
VSCode extension for Gemini integration

### 5. `packages/test-utils` - Shared Test Utilities
Testing helpers used across packages

---

## Key Architectural Patterns

### 1. **Monorepo with Clear Separation**
```
gemini-cli/
├── packages/
│   ├── core/          # Business logic (platform-agnostic)
│   ├── cli/           # Ink UI
│   ├── a2a-server/    # API server
│   └── vscode-ide-companion/  # IDE integration
```

**Lesson for Penguin:**
```
penguin/
├── packages/
│   ├── core/          # Python business logic (existing)
│   ├── cli/           # TypeScript Ink CLI (new)
│   ├── api/           # FastAPI server (existing)
│   └── vscode-extension/  # Future IDE integration
```

### 2. **Context-Heavy React Architecture**
Gemini CLI uses **15 React Contexts**:
- `AppContext` - App-wide state
- `UIStateContext` - UI state machine
- `UIActionsContext` - UI action dispatchers
- `ConfigContext` - Configuration
- `SettingsContext` - User settings
- `SessionContext` - Session stats
- `VimModeContext` - Vim mode state
- `KeypressContext` - Keyboard handling
- `ShellFocusContext` - Shell focus state
- ... and more

**Our current approach:** Simple props drilling
**Better approach:** Adopt context pattern for:
- Connection state
- Config/settings
- Session management
- Keyboard/input state

### 3. **Custom Hook Architecture**
**82 custom hooks!** Examples:
- `useHistory` - Message history management
- `useGeminiStream` - Streaming API handler
- `useMemoryMonitor` - Memory usage tracking
- `useVimMode` - Vim keybindings
- `useKeypress` - Advanced keyboard handling
- `useTerminalSize` - Responsive sizing
- `useThemeCommand` - Theme switching
- `useAuthCommand` - Authentication flow
- `useMessageQueue` - Message queuing
- `useFolderTrust` - Folder trust/security

**Our current approach:** 1 hook (`useChat`)
**Better approach:** Split into domain-specific hooks

### 4. **Service Layer Pattern**
```typescript
services/
├── CommandService.ts        # Slash command registry/execution
├── FileCommandLoader.ts     # Load commands from files
├── McpPromptLoader.ts       # MCP prompt loading
└── prompt-processors/       # Input preprocessing
    ├── argumentProcessor.ts
    ├── atFileProcessor.ts   # @file injection
    └── shellProcessor.ts    # Shell command expansion
```

**Lesson:** Separate services from UI components

### 5. **Slash Command System**
```typescript
// commands/chatCommand.ts
export const chatCommand: SlashCommand = {
  name: 'chat',
  description: 'Start a new chat',
  execute: async (context) => {
    // Implementation
  }
};
```

**Current Penguin:** Commands mixed in Typer CLI
**Better approach:** Plugin-based command system like Gemini

### 6. **Extension System**
```
config/extensions/
├── extensionEnablement.ts  # Enable/disable extensions
├── github.ts               # GitHub extension loader
├── update.ts               # Extension updates
└── variables.ts            # Extension variables
```

**Commands:**
- `/extensions install <name>`
- `/extensions enable <name>`
- `/extensions list`
- `/extensions update`

**Lesson:** Build extensibility from day 1

### 7. **Theme System**
**23 theme files!** Including:
- Theme manager
- Semantic colors
- Multiple built-in themes
- User-definable themes

**Current Penguin:** Hardcoded colors
**Better approach:** Theming system

### 8. **Testing Strategy**
- **Unit tests**: `.test.ts` files colocated with source
- **Integration tests**: `.integration.test.ts`
- **Component tests**: `ink-testing-library` for Ink components
- **Mocking**: Custom matchers and mock utilities

**Current Penguin:** Minimal CLI testing
**Better approach:** Comprehensive test coverage like Gemini

### 9. **Configuration Layering**
```typescript
// config/settings.ts
export enum SettingScope {
  User = 'user',
  Workspace = 'workspace',
  Folder = 'folder'
}

// Zod schema for validation
const settingsSchema = z.object({
  model: z.string(),
  theme: z.string(),
  // ... etc
});
```

**Similar to Penguin's approach**, but with:
- Stronger typing (Zod schemas)
- More granular scopes
- Migration system for deprecated settings

### 10. **Advanced Keyboard Handling**
```typescript
// keyMatchers.ts - Keyboard command mapping
export enum Command {
  AcceptPreviousBlockCommand,
  CancelCommand,
  CopyToClipboard,
  DeletePreviousLine,
  // ... 50+ commands
}

// Custom keypress hook
const { keypress } = useKeypress();
useEffect(() => {
  if (keyMatchers.matches(keypress, Command.AcceptPreviousBlockCommand)) {
    // Handle command
  }
}, [keypress]);
```

**Lesson:** Build robust keyboard input system

---

## Critical Differences: Gemini CLI vs Our Current Ink CLI

| Feature | Gemini CLI | Penguin Ink CLI (Current) | Recommendation |
|---------|------------|---------------------------|----------------|
| **Lines of Code** | ~115,500 | ~350 | Start small, grow iteratively |
| **Package Structure** | Monorepo (5 packages) | Single package | Adopt core/cli split |
| **React Patterns** | 15 contexts, 82 hooks | 1 hook, no contexts | Use contexts for shared state |
| **Testing** | Comprehensive (vitest) | None | Add tests incrementally |
| **Commands** | Plugin system, 30+ commands | Hardcoded | Build command registry |
| **Extensions** | Full extension API | None | Phase 3 feature |
| **Themes** | 23 themes, manager | Hardcoded colors | Phase 2 feature |
| **Config** | Zod schemas, multi-scope | YAML files | Keep simple for now |
| **Keyboard** | 50+ commands, custom matchers | Basic useInput | Improve incrementally |
| **Services** | Separate service layer | Inline logic | Extract services |
| **MCP Integration** | Full MCP SDK | None | Already in Python backend |
| **IDE Integration** | VSCode extension | None | Future (Phase 4+) |
| **A2A Server** | Separate package | FastAPI backend | Already have this |

---

## What to Adopt Immediately (Phase 1-2)

### 1. **Core/CLI Package Split** ✅ CRITICAL
```
penguin-cli/
├── src/
│   ├── core/          # Business logic (new)
│   │   ├── chat.ts
│   │   ├── session.ts
│   │   └── websocket.ts
│   ├── ui/            # Ink components
│   │   ├── components/
│   │   ├── hooks/
│   │   └── contexts/
│   └── index.tsx
```

**Why:** Separates concerns, enables testing, allows reuse

### 2. **React Contexts for Shared State** ✅ HIGH PRIORITY
```typescript
// contexts/ConnectionContext.tsx
export const ConnectionContext = createContext<ConnectionState>();

// contexts/SessionContext.tsx
export const SessionContext = createContext<SessionState>();

// contexts/ConfigContext.tsx
export const ConfigContext = createContext<Config>();
```

**Why:** Eliminates props drilling, cleaner component tree

### 3. **Custom Hooks by Domain** ✅ HIGH PRIORITY
Split `useChat` into:
- `useWebSocket` - Connection management
- `useMessageHistory` - Message state
- `useStreaming` - Token streaming + batching
- `useKeyboard` - Keyboard input
- `useSession` - Session lifecycle

**Why:** Single responsibility, easier testing, more reusable

### 4. **Service Layer** ✅ MEDIUM PRIORITY
```typescript
// services/ChatService.ts
export class ChatService {
  async sendMessage(text: string): Promise<void> { }
  streamResponse(): AsyncIterator<string> { }
}

// services/SessionService.ts
export class SessionService {
  loadSession(id: string): Session { }
  saveSession(session: Session): void { }
}
```

**Why:** Testable business logic, decoupled from UI

### 5. **Testing Infrastructure** ✅ MEDIUM PRIORITY
```bash
npm install -D vitest ink-testing-library
```

**Why:** Prevent regressions, enable refactoring with confidence

---

## What to Defer (Phase 3+)

### 1. **Extension System**
- Complex API surface
- Requires stable core first
- **When:** After Phase 2 complete

### 2. **Theme System**
- Nice-to-have, not critical
- Can use simple color variables initially
- **When:** User requests it

### 3. **Advanced Keyboard Matchers**
- 50+ command enum is overkill for MVP
- **When:** Users request Vim mode or custom keybindings

### 4. **IDE Integration**
- Requires VSCode extension development
- **When:** CLI is stable and widely used

### 5. **MCP Extension Commands**
- MCP already works in Python backend
- **When:** Users need CLI-level MCP management

---

## Revised Architecture Proposal

### File Structure (Gemini-Inspired)
```
penguin-cli/
├── src/
│   ├── core/                    # Business logic layer
│   │   ├── chat/
│   │   │   ├── ChatService.ts
│   │   │   ├── MessageQueue.ts
│   │   │   └── StreamProcessor.ts
│   │   ├── session/
│   │   │   ├── SessionManager.ts
│   │   │   └── SessionStore.ts
│   │   ├── connection/
│   │   │   ├── WebSocketClient.ts
│   │   │   └── ConnectionManager.ts
│   │   └── config/
│   │       └── ConfigLoader.ts
│   │
│   ├── ui/                      # Presentation layer
│   │   ├── components/
│   │   │   ├── App.tsx
│   │   │   ├── ChatView.tsx
│   │   │   ├── MessageList.tsx
│   │   │   ├── InputPrompt.tsx
│   │   │   └── StatusBar.tsx
│   │   ├── hooks/
│   │   │   ├── useWebSocket.ts
│   │   │   ├── useMessageHistory.ts
│   │   │   ├── useStreaming.ts
│   │   │   ├── useKeyboard.ts
│   │   │   └── useSession.ts
│   │   ├── contexts/
│   │   │   ├── ConnectionContext.tsx
│   │   │   ├── SessionContext.tsx
│   │   │   ├── ConfigContext.tsx
│   │   │   └── UIStateContext.tsx
│   │   └── utils/
│   │       ├── formatting.ts
│   │       └── colors.ts
│   │
│   ├── commands/                # Slash commands (future)
│   │   ├── registry.ts
│   │   └── builtin/
│   │
│   ├── services/                # Application services
│   │   ├── CommandService.ts
│   │   └── HistoryService.ts
│   │
│   └── index.tsx                # Entry point
│
├── tests/                       # Tests separate from src
│   ├── unit/
│   ├── integration/
│   └── e2e/
│
├── package.json
└── tsconfig.json
```

### Component Tree (Gemini Pattern)
```tsx
<ConfigContext.Provider>
  <SessionContext.Provider>
    <ConnectionContext.Provider>
      <UIStateContext.Provider>
        <App>
          <StatusBar />
          <ChatView>
            <MessageList />
            <InputPrompt />
          </ChatView>
        </App>
      </UIStateContext.Provider>
    </ConnectionContext.Provider>
  </SessionContext.Provider>
</ConfigContext.Provider>
```

---

## Immediate Action Items

### Phase 1 Revision (Based on Gemini CLI)

1. **Restructure Current Code** ✅
   - Move business logic to `src/core/`
   - Move UI to `src/ui/`
   - Extract services

2. **Add React Contexts** ✅
   - `ConnectionContext` - WebSocket state
   - `SessionContext` - Current session
   - `ConfigContext` - Configuration

3. **Split useChat Hook** ✅
   - `useWebSocket` - Connection only
   - `useMessageHistory` - Message state only
   - `useStreaming` - Token batching only

4. **Add Service Layer** ✅
   - `ChatService` - Chat operations
   - `SessionService` - Session CRUD

5. **Set Up Testing** ✅
   - Install vitest + ink-testing-library
   - Write first component test

### Phase 2 Goals (Gemini-Aligned)

1. **Command System**
   - Build slash command registry
   - Port Python CLI commands to TypeScript

2. **Multi-Session UI**
   - Tab system (already planned)
   - Session switcher

3. **Syntax Highlighting**
   - Use `lowlight` (like Gemini) instead of `highlight.js`

4. **Testing Coverage**
   - 50%+ code coverage
   - All hooks tested

---

## Key Takeaways

### What Gemini CLI Does Right

1. **Clear separation**: core vs UI
2. **Context-heavy**: Avoids props drilling
3. **Hook decomposition**: Single-responsibility hooks
4. **Service layer**: Testable business logic
5. **Testing**: Comprehensive coverage
6. **Extensibility**: Plugin system from day 1
7. **Monorepo**: Shared packages (core, cli, server, IDE)

### What We Can Skip (For Now)

1. Extension API (too complex for MVP)
2. 23 themes (nice-to-have)
3. Advanced keyboard matchers (Vim mode can wait)
4. IDE integration (future)
5. 115k lines of code (we're not Google!)

### Our Competitive Advantage

1. **Python backend already exists** - No need to rewrite core
2. **FastAPI server** - Already have A2A equivalent
3. **Smaller scope** - Can ship faster
4. **Focused features** - What users actually need

---

## Conclusion

**Gemini CLI is an excellent reference architecture**, but we should adopt patterns incrementally:

### Adopt Now:
- Core/UI separation
- React Contexts
- Hook decomposition
- Service layer
- Testing infrastructure

### Adopt Later:
- Extension system
- Theme system
- Advanced keyboard
- IDE integration

### Skip:
- 115k lines of complexity
- Google-specific features

**Next Step:** Refactor Phase 1 CLI using Gemini patterns (core/ui split, contexts, split hooks).
