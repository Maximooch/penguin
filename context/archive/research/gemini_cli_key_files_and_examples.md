# Gemini CLI Reference - Key Files and Code Examples

## Essential Files to Study

### 1. Entry Points & Initialization
- **`index.ts`** - CLI entry point, shebang, error handling
- **`src/gemini.tsx`** - Main initialization, provider setup, config loading
- **`src/ui/AppContainer.tsx`** - MEGA component, state composition (1419 lines)
- **`src/ui/App.tsx`** - Root component, simple layout switching

### 2. State Management (Contexts)
- **`src/ui/contexts/UIStateContext.tsx`** - Main state interface (40+ properties)
- **`src/ui/contexts/UIActionsContext.tsx`** - Action handlers interface
- **`src/ui/contexts/SessionContext.tsx`** - SessionStatsProvider pattern with custom equality
- **`src/ui/contexts/KeypressContext.tsx`** - Advanced keyboard input (963 lines!)
- **`src/ui/contexts/SettingsContext.tsx`** - Simple reference to settings
- **`src/ui/contexts/StreamingContext.tsx`** - Minimal context, passed via props

### 3. Core Hooks (50+ custom hooks)
- **`src/ui/hooks/useGeminiStream.ts`** - Streaming, tool management (300+ lines)
- **`src/ui/hooks/useReactToolScheduler.ts`** - Tool call lifecycle
- **`src/ui/hooks/useHistoryManager.ts`** - History management
- **`src/ui/hooks/useKeypress.ts`** - Keyboard input subscription
- **`src/ui/hooks/useTerminalSize.ts`** - Responsive sizing
- **`src/ui/hooks/useConsoleMessages.ts`** - Message filtering
- **`src/ui/hooks/useLoadingIndicator.ts`** - Loading phrase cycling

### 4. Commands System
- **`src/ui/commands/types.ts`** - SlashCommand interface, discriminated unions
- **`src/ui/commands/*.ts`** - 40+ command implementations
- **`src/ui/hooks/slashCommandProcessor.ts`** - Command parsing and execution

### 5. Components
- **`src/ui/components/MainContent.tsx`** - History display
- **`src/ui/components/HistoryItemDisplay.tsx`** - Polymorphic rendering
- **`src/ui/components/DialogManager.tsx`** - Dialog routing
- **`src/ui/components/Composer.tsx`** - Input orchestration
- **`src/ui/components/InputPrompt.tsx`** - User input component

### 6. Layouts
- **`src/ui/layouts/DefaultAppLayout.tsx`** - Main layout
- **`src/ui/layouts/ScreenReaderAppLayout.tsx`** - Accessibility layout

### 7. Types & Data Structures
- **`src/ui/types.ts`** - All history item types, streaming state enums

---

## Code Examples from the Codebase

### Example 1: Streaming Event Processing

**File**: `src/ui/hooks/useGeminiStream.ts` (Simplified excerpt)

```typescript
export const useGeminiStream = (
  geminiClient: GeminiClient,
  history: HistoryItem[],
  addItem: UseHistoryManagerReturn['addItem'],
  config: Config,
  settings: LoadedSettings,
) => {
  const [streamingState, setStreamingState] = useState<StreamingState>(StreamingState.Idle);

  const handlePromptSubmission = useCallback(
    async (prompt: string) => {
      setStreamingState(StreamingState.Responding);

      try {
        // Convert history to API format
        const apiHistory = history.map(toApiFormat);
        
        // Stream response
        const stream = await geminiClient.streamChat({
          messages: apiHistory,
          systemPrompt: buildSystemPrompt(settings),
        });

        // Process events
        for await (const event of stream) {
          if (event.type === 'content') {
            // Add content to history
            addItem({ type: 'gemini', text: event.text });
          } else if (event.type === 'tool_call') {
            // Schedule tool
            scheduleToolCall(event);
          } else if (event.type === 'finished') {
            // Mark complete
            setStreamingState(StreamingState.Idle);
          }
        }
      } catch (error) {
        addItem({ type: 'error', text: getErrorMessage(error) });
        setStreamingState(StreamingState.Idle);
      }
    },
    [geminiClient, history, addItem, config, settings]
  );

  return { handlePromptSubmission, streamingState };
};
```

### Example 2: Custom Equality Check in Provider

**File**: `src/ui/contexts/SessionContext.tsx`

```typescript
function areMetricsEqual(a: SessionMetrics, b: SessionMetrics): boolean {
  if (a === b) return true;
  if (!a || !b) return false;

  // Compare files
  if (
    a.files.totalLinesAdded !== b.files.totalLinesAdded ||
    a.files.totalLinesRemoved !== b.files.totalLinesRemoved
  ) {
    return false;
  }

  // Compare tools
  const toolsA = a.tools;
  const toolsB = b.tools;
  if (
    toolsA.totalCalls !== toolsB.totalCalls ||
    toolsA.totalSuccess !== toolsB.totalSuccess ||
    toolsA.totalFail !== toolsB.totalFail ||
    toolsA.totalDurationMs !== toolsB.totalDurationMs
  ) {
    return false;
  }

  // Compare tool decisions (exhaustive)
  if (
    toolsA.totalDecisions[ToolCallDecision.ACCEPT] !==
      toolsB.totalDecisions[ToolCallDecision.ACCEPT] ||
    toolsA.totalDecisions[ToolCallDecision.REJECT] !==
      toolsB.totalDecisions[ToolCallDecision.REJECT] ||
    // ... more comparisons
  ) {
    return false;
  }

  // Compare models
  const modelsAKeys = Object.keys(a.models);
  const modelsBKeys = Object.keys(b.models);
  if (modelsAKeys.length !== modelsBKeys.length) return false;

  for (const key of modelsAKeys) {
    if (!b.models[key] || !areModelMetricsEqual(a.models[key], b.models[key])) {
      return false;
    }
  }

  return true;
}

// Usage in provider
export const SessionStatsProvider = ({ children }) => {
  const [stats, setStats] = useState(/* ... */);

  useEffect(() => {
    const handleUpdate = ({ metrics, lastPromptTokenCount }) => {
      setStats((prevState) => {
        if (
          prevState.lastPromptTokenCount === lastPromptTokenCount &&
          areMetricsEqual(prevState.metrics, metrics)  // Only update if truly different
        ) {
          return prevState;
        }
        return {
          ...prevState,
          metrics,
          lastPromptTokenCount,
        };
      });
    };

    uiTelemetryService.on('update', handleUpdate);
    return () => uiTelemetryService.off('update', handleUpdate);
  }, []);

  // ...
};
```

### Example 3: Discriminated Union for Commands

**File**: `src/ui/commands/types.ts`

```typescript
export interface ToolActionReturn {
  type: 'tool';
  toolName: string;
  toolArgs: Record<string, unknown>;
}

export interface MessageActionReturn {
  type: 'message';
  messageType: 'info' | 'error';
  content: string;
}

export interface QuitActionReturn {
  type: 'quit';
  messages: HistoryItem[];
}

export interface LoadHistoryActionReturn {
  type: 'load_history';
  history: HistoryItemWithoutId[];
  clientHistory: Content[];
}

export type SlashCommandActionReturn =
  | ToolActionReturn
  | MessageActionReturn
  | QuitActionReturn
  | OpenDialogActionReturn
  | LoadHistoryActionReturn
  | SubmitPromptActionReturn
  | ConfirmShellCommandsActionReturn
  | ConfirmActionReturn;

// Example command using discriminated union
export const createChatCommand = (): SlashCommand => ({
  name: 'chat',
  description: 'Chat with Gemini',
  kind: CommandKind.BUILT_IN,
  async action(context, args) {
    const subcommand = args.split(' ')[0];
    
    if (subcommand === 'resume') {
      const tag = args.split(' ')[1];
      const history = await loadHistoryTag(tag);
      
      return {
        type: 'load_history',  // Type must match one of the union
        history: history.items,
        clientHistory: history.apiFormat,
      };
    }
    
    return {
      type: 'message',  // Different return type
      messageType: 'info',
      content: 'Chat started',
    };
  },
});
```

### Example 4: Hook Composition Pattern

**File**: `src/ui/AppContainer.tsx` (Simplified excerpt)

```typescript
export const AppContainer = (props: AppContainerProps) => {
  // Compose hooks to extract logic
  const historyManager = useHistory();
  const settings = useSettings();
  const { subscribe, unsubscribe } = useKeypressContext();
  const [stats, startNewPrompt] = useSessionStats();
  const [consoleMessages, filterConsoleMessages] = useConsoleMessages();
  const [terminalSize] = useTerminalSize();
  const [loadingPhrase] = useLoadingIndicator();
  
  // Local state
  const [isThemeDialogOpen, setIsThemeDialogOpen] = useState(false);
  const [streamingState, setStreamingState] = useState(StreamingState.Idle);
  const [pendingHistoryItems, setPendingHistoryItems] = useState([]);
  // ... many more useState calls

  // Complex hook with many dependencies
  const handleGeminiStream = useGeminiStream(
    geminiClient,
    historyManager.history,
    historyManager.addItem,
    config,
    settings,
    (msg) => setDebugMessage(msg),
    handleSlashCommand,
    shellModeActive
  );

  // Compose everything into single UIState object
  const uiState: UIState = useMemo(() => ({
    history: historyManager.history,
    historyManager,
    isThemeDialogOpen,
    themeError: themeError,
    isAuthenticating: isAuthenticating,
    isConfigInitialized: isConfigInitialized,
    authError: authError,
    streamingState,
    currentModel,
    contextFileNames,
    // ... 40+ properties
  }), [
    historyManager,
    isThemeDialogOpen,
    themeError,
    streamingState,
    // ... all dependencies
  ]);

  // Compose action handlers
  const uiActions: UIActions = useMemo(() => ({
    handleThemeSelect: (themeName, scope) => {
      applyTheme(themeName);
      setThemeError(null);
      setIsThemeDialogOpen(false);
    },
    closeThemeDialog: () => setIsThemeDialogOpen(false),
    // ... many more handlers
  }), []);

  return (
    <UIStateContext.Provider value={uiState}>
      <UIActionsContext.Provider value={uiActions}>
        <ConfigContext.Provider value={config}>
          <App />
        </ConfigContext.Provider>
      </UIActionsContext.Provider>
    </UIStateContext.Provider>
  );
};
```

### Example 5: Ref-Based Callback Update Pattern

**File**: `src/ui/hooks/useReactToolScheduler.ts` (Simplified)

```typescript
export function useReactToolScheduler(
  onComplete: (tools: CompletedToolCall[]) => Promise<void>,
  config: Config,
  getPreferredEditor: () => EditorType | undefined,
  onEditorClose: () => void,
) {
  const [toolCalls, setToolCalls] = useState<TrackedToolCall[]>([]);

  // Keep refs up-to-date without recreating handlers
  const onCompleteRef = useRef(onComplete);
  const getPreferredEditorRef = useRef(getPreferredEditor);
  const onEditorCloseRef = useRef(onEditorClose);

  useEffect(() => {
    onCompleteRef.current = onComplete;
  }, [onComplete]);

  useEffect(() => {
    getPreferredEditorRef.current = getPreferredEditor;
  }, [getPreferredEditor]);

  useEffect(() => {
    onEditorCloseRef.current = onEditorClose;
  }, [onEditorClose]);

  // Async handler uses refs, not dependency array
  const handleToolComplete = useCallback(
    async (completedTool: CompletedToolCall) => {
      setToolCalls((prev) => {
        // Use ref to get current value without re-creating handler
        return prev.map((tool) =>
          tool.id === completedTool.id
            ? { ...tool, responseSubmittedToGemini: true }
            : tool
        );
      });

      // Call the ref-based handler
      await onCompleteRef.current([completedTool]);
    },
    [] // Empty dependency array because we use refs!
  );

  return [toolCalls, schedule, markAsSubmitted, setToolCalls, cancelAll];
}
```

### Example 6: Polymorphic Display with Discriminated Union

**File**: `src/ui/components/HistoryItemDisplay.tsx` (Simplified)

```typescript
interface HistoryItemDisplayProps {
  item: HistoryItem;
  index: number;
}

export const HistoryItemDisplay = ({ item, index }: HistoryItemDisplayProps) => {
  // Switch on discriminated union - exhaustiveness checked by TypeScript
  switch (item.type) {
    case 'user':
      return (
        <Box flexDirection="column">
          <Text>You: </Text>
          <Text>{item.text}</Text>
        </Box>
      );

    case 'gemini':
      return (
        <Box flexDirection="column">
          <Text dimColor>Gemini:</Text>
          <Text>{item.text}</Text>
        </Box>
      );

    case 'tool_group':
      return (
        <Box flexDirection="column">
          {item.tools.map((tool) => (
            <ToolDisplay key={tool.callId} tool={tool} />
          ))}
        </Box>
      );

    case 'stats':
      return (
        <Box flexDirection="column">
          <Text>Session Duration: {item.duration}</Text>
        </Box>
      );

    case 'error':
      return (
        <Text color="red">Error: {item.text}</Text>
      );

    // TypeScript forces handling of ALL cases or adding default
    default:
      const _exhaustiveCheck: never = item;
      return _exhaustiveCheck;
  }
};
```

### Example 7: Advanced Keyboard Protocol Handling

**File**: `src/ui/contexts/KeypressContext.tsx` (Simplified excerpt)

```typescript
function parseKittyPrefix(buffer: string): { key: Key; length: number } | null {
  // Handles multiple keyboard protocols in order of specificity

  // 1. Reverse Tab (legacy): ESC [ Z
  const revTabLegacy = new RegExp(`^${ESC}\\[Z`);
  let m = buffer.match(revTabLegacy);
  if (m) {
    return {
      key: {
        name: 'tab',
        ctrl: false,
        meta: false,
        shift: true,  // Reverse tab implies shift
        paste: false,
        sequence: buffer.slice(0, m[0].length),
        kittyProtocol: true,
      },
      length: m[0].length,
    };
  }

  // 2. Reverse Tab (parameterized): ESC [ 1 ; <mods> Z
  const revTabParam = new RegExp(`^${ESC}\\[1;(\\d+)Z`);
  m = buffer.match(revTabParam);
  if (m) {
    let mods = parseInt(m[1], 10);
    if (mods >= KITTY_MODIFIER_EVENT_TYPES_OFFSET) {
      mods -= KITTY_MODIFIER_EVENT_TYPES_OFFSET;
    }
    const bits = mods - KITTY_MODIFIER_BASE;
    const alt = (bits & MODIFIER_ALT_BIT) === MODIFIER_ALT_BIT;
    const ctrl = (bits & MODIFIER_CTRL_BIT) === MODIFIER_CTRL_BIT;
    
    return {
      key: {
        name: 'tab',
        ctrl,
        meta: alt,
        shift: true,  // Always shift for reverse tab
        paste: false,
        sequence: buffer.slice(0, m[0].length),
        kittyProtocol: true,
      },
      length: m[0].length,
    };
  }

  // 3. CSI-u form: ESC [ <code> ; <mods> (u|~)
  const csiUPrefix = new RegExp(`^${ESC}\\[(\\d+)(;(\\d+))?([u~])`);
  m = buffer.match(csiUPrefix);
  if (m) {
    const keyCode = parseInt(m[1], 10);
    let modifiers = m[3] ? parseInt(m[3], 10) : KITTY_MODIFIER_BASE;
    if (modifiers >= KITTY_MODIFIER_EVENT_TYPES_OFFSET) {
      modifiers -= KITTY_MODIFIER_EVENT_TYPES_OFFSET;
    }
    const modifierBits = modifiers - KITTY_MODIFIER_BASE;
    const shift = (modifierBits & MODIFIER_SHIFT_BIT) === MODIFIER_SHIFT_BIT;
    const alt = (modifierBits & MODIFIER_ALT_BIT) === MODIFIER_ALT_BIT;
    const ctrl = (modifierBits & MODIFIER_CTRL_BIT) === MODIFIER_CTRL_BIT;

    // Map key codes to names
    const nameMap = {
      27: 'escape',
      9: 'tab',
      8: 'backspace',
      13: 'return',
      // ... more mappings
    };

    const name = nameMap[keyCode];
    if (name) {
      return {
        key: {
          name,
          ctrl,
          meta: alt,
          shift,
          paste: false,
          sequence: buffer.slice(0, m[0].length),
          kittyProtocol: true,
        },
        length: m[0].length,
      };
    }
  }

  return null;
}

// Usage in keyboard handler
const handleKeypress = (_: unknown, key: Key) => {
  if (kittyProtocolEnabled) {
    kittySequenceBuffer += key.sequence;

    let remainingBuffer = kittySequenceBuffer;
    let parsedAny = false;

    while (remainingBuffer) {
      const parsed = parseKittyPrefix(remainingBuffer);

      if (parsed) {
        // Successfully parsed one complete sequence
        broadcast(parsed.key);
        remainingBuffer = remainingBuffer.slice(parsed.length);
        parsedAny = true;
      } else {
        // Check if more data might complete the sequence
        const couldBeValid = couldBeKittySequence(remainingBuffer);

        if (!couldBeValid) {
          // Not a kitty sequence - flush immediately
          broadcast({
            name: '',
            sequence: remainingBuffer,
            // ...
          });
          remainingBuffer = '';
          parsedAny = true;
        } else if (remainingBuffer.length > MAX_KITTY_SEQUENCE_LENGTH) {
          // Buffer overflow - log and flush
          logKittySequenceOverflow(config, {
            length: remainingBuffer.length,
            buffer: remainingBuffer,
          });
          // ...
        } else {
          // Could be valid but incomplete - wait for more data
          kittySequenceTimeout = setTimeout(() => {
            broadcast({
              name: '',
              sequence: kittySequenceBuffer,
              // ...
            });
            kittySequenceBuffer = '';
          }, KITTY_SEQUENCE_TIMEOUT_MS);
          break;
        }
      }
    }

    kittySequenceBuffer = remainingBuffer;
  }
};
```

### Example 8: Paste Mode Handling

**File**: `src/ui/contexts/KeypressContext.tsx` (Simplified)

```typescript
// Bracketed paste protocol support
export const PASTE_MODE_START = `${ESC}[200~`;  // Terminal enters paste mode
export const PASTE_MODE_END = `${ESC}[201~`;    // Terminal exits paste mode

const handleKeypress = (_: unknown, key: Key) => {
  // Detect paste mode start
  if (key.name === 'paste-start') {
    flushKittyBufferOnInterrupt('paste start');
    pasteBuffer = Buffer.alloc(0);  // Start collecting paste data
    return;
  }

  // Detect paste mode end
  if (key.name === 'paste-end') {
    if (pasteBuffer !== null) {
      // All paste data collected - emit as single event
      broadcast({
        name: '',
        ctrl: false,
        meta: false,
        shift: false,
        paste: true,  // Mark as paste
        sequence: pasteBuffer.toString(),  // All accumulated data
      });
    }
    pasteBuffer = null;
    return;
  }

  // While in paste mode, accumulate data
  if (pasteBuffer !== null) {
    pasteBuffer = Buffer.concat([pasteBuffer, Buffer.from(key.sequence)]);
    return;  // Don't broadcast individual keys during paste
  }

  // Not in paste mode - normal key handling
  broadcast(key);
};
```

---

## Key Design Patterns Summary

| Pattern | File | Purpose |
|---------|------|---------|
| **Ref-Based Callbacks** | `useReactToolScheduler` | Stable closure for async handlers |
| **Custom Equality Check** | `SessionContext` | Prevent unnecessary re-renders |
| **Discriminated Union** | `commands/types.ts` | Type-safe command returns |
| **Hook Composition** | `AppContainer` | Extract logic from components |
| **Provider Hierarchy** | `gemini.tsx` | Strategic context layering |
| **Subscription Pattern** | `KeypressContext` | Pub/sub for keyboard input |
| **Polymorphic Rendering** | `HistoryItemDisplay` | Handle all item types |
| **Context + Local State** | `AppContainer` | Multi-layer state management |
| **Buffering Pattern** | `KeypressContext` | Handle terminal edge cases |
| **Service Abstraction** | `hooks/useGeminiStream` | Abstract API behind hooks |

