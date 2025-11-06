# Gemini CLI Architecture Diagrams

## 1. High-Level Application Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         index.ts (CLI entry)                      │
│                          ↓ npm run start                          │
└─────────────────────────────────────────────────────────────────┘
                                 ↓
┌─────────────────────────────────────────────────────────────────┐
│                       gemini.tsx (Main)                           │
│  • Loads config, settings, themes                                │
│  • Initializes services (Gemini client, extensions, etc)         │
│  • Sets up unhandled rejection handler                           │
└─────────────────────────────────────────────────────────────────┘
                                 ↓
┌─────────────────────────────────────────────────────────────────┐
│                  Provider Composition (Ink render)               │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  SettingsContext.Provider                               │   │
│  │  └─ KeypressProvider (keyboard input)                  │   │
│  │     └─ SessionStatsProvider (telemetry)                │   │
│  │        └─ VimModeProvider (vim mode state)             │   │
│  │           └─ AppContainer (creates UIState + UIActions)│   │
│  │              └─ App (renders UI layout)                │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. State Management Layers

```
┌───────────────────────────────────────────────────────────────┐
│               LAYER 1: Immutable Context References             │
├───────────────────────────────────────────────────────────────┤
│  UIStateContext          {history, dialogs, models, ...}       │
│  StreamingContext        {Idle | Responding | Waiting}         │
│  SettingsContext         {theme, layout, behavior}             │
│  ConfigContext           {api, paths, extensions}              │
│  AppContext              {version, startupWarnings}            │
│  SessionStatsContext     {metrics, startNewPrompt}             │
└───────────────────────────────────────────────────────────────┘
                                 ↑
          (Updated via Provider from Layer 2)
                                 ↑
┌───────────────────────────────────────────────────────────────┐
│             LAYER 2: Mutable Component State (AppContainer)     │
├───────────────────────────────────────────────────────────────┤
│  const historyManager = useHistory()                           │
│  const [isThemeDialogOpen, setIsThemeDialogOpen]              │
│  const [streamingState, setStreamingState]                    │
│  const [currentModel, setCurrentModel]                        │
│  const [pendingHistoryItems, setPendingHistoryItems]          │
│  ... 30+ useState hooks                                        │
└───────────────────────────────────────────────────────────────┘
                                 ↑
          (Computed from hooks + service callbacks)
                                 ↑
┌───────────────────────────────────────────────────────────────┐
│         LAYER 3: Derived/Computed State (Custom Hooks)         │
├───────────────────────────────────────────────────────────────┤
│  useSessionStats()       → Calculates metrics equality         │
│  useConsoleMessages()    → Filters messages by type            │
│  useLoadingIndicator()   → Derives loading phrase              │
│  useTerminalSize()       → Computes available width/height    │
│  useGeminiStream()       → Manages streaming lifecycle         │
└───────────────────────────────────────────────────────────────┘
```

---

## 3. Component Tree Structure

```
                          App
                    (StreamingContext)
                           │
                ┌──────────┴──────────┐
         (Screen Reader?)             
        /                 \
    ScreenReaderAppLayout  DefaultAppLayout
                                │
                    ┌───────────┼───────────┐
                    │           │           │
                MainContent  Notifications  (Controls)
                    │                       │
                    │           ┌───────────┴────────────┐
                    │        (Visible?)                  
                    │       /          \
                    │  DialogManager  Composer
                    │    │              │
         ┌──────────┤    │              │
         │          │    ├─ AuthDialog  │
         │          │    ├─ Theme...    ├─ InputPrompt
         │          │    ├─ Editor...   └─ Suggestions
         │          │    └─ 8+ more
      History       │
       Items    Dialogs
```

---

## 4. Streaming/Tool Call Lifecycle

```
┌─────────────────────────────────────────────────────────────┐
│                      User Input (Prompt)                      │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────┐
│           Process Input (useGeminiStream)                     │
│  • Parse slash commands (/chat, /settings, etc)             │
│  • Handle @mentions (file context)                           │
│  • Format shell commands                                     │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────┐
│        Send to Gemini API (GeminiClient.streamChat)          │
│  • Include history, context, system prompts                  │
│  • Use selected model (flash/pro)                            │
└──────────────────┬──────────────────────────────────────────┘
                   │
         ┌─────────┴────────────┐
         │                      │
         ▼                      ▼
    ContentEvent          ToolCallEvent
         │                      │
         │                  (Tool Request)
         │                      │
         │          ┌───────────┴────────────┐
         │          │                        │
         │     NeedConfirm?              Execute
         │     (useReactToolScheduler)    (CoreToolScheduler)
         │          │                      │
         │     ┌────┴────┐              ┌──┴──────┐
         │     │          │              │         │
         │   Confirm    Auto-Accept      │      Output
         │     │          │              │      Updates
         │     │          │              ▼        │
         ▼     ▼          ▼         ┌─────────┐  │
      AddToHistory ─────────────→  SubmitResult  │
         │                          │            │
         │  FinishedEvent           │            │
         │     │                    │            │
         ▼     ▼                    ▼            ▼
      ┌──────────────────────────────────────┐
      │   Update UIState (history)            │
      │   Trigger re-render                  │
      └──────────────────────────────────────┘
```

---

## 5. Keyboard Input Processing Pipeline

```
                    Raw Terminal Input
                           │
                           ▼
                  ┌──────────────────┐
                  │  KeypressProvider│ (KeypressContext)
                  └────────┬─────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
        ▼                  ▼                  ▼
   Protocol Detection  Input Buffering   Special Handling
   ├─ Kitty Protocol    ├─ Kitty Seq       ├─ Paste Mode
   ├─ CSI-u Form         │  Buffer (50ms)    │  ├─ Start
   ├─ Legacy Sequences   ├─ Drag Buffer      │  └─ End
   └─ Parameterized      └─ (100ms)          ├─ Backslash+Enter
                                              ├─ Alt Mapping
                                              └─ Overflow Check
        │                  │                  │
        └──────────────────┼──────────────────┘
                           │
                    (Parsed Key Object)
                           │
                ┌──────────┴──────────┐
                │                    │
                ▼                    ▼
        Broadcast to          Components
        Subscribers           Subscribe:
        (publish/sub)         • InputPrompt
                              • Editor
                              • Dialog handlers
```

---

## 6. Context Provider Hierarchy

```
┌────────────────────────────────────────────────────────────┐
│                 startInteractiveUI()                        │
│                  (from gemini.tsx)                          │
└───────────────────────┬────────────────────────────────────┘
                        │
                        ▼
        ┌───────────────────────────────┐
        │  SettingsContext.Provider      │  (LoadedSettings)
        │  Provides: theme, layout cfg   │
        │                                 │
        │  ┌────────────────────────────┐│
        │  │ KeypressProvider            ││ (subscription-based)
        │  │ Provides: subscribe/unsub   ││
        │  │                              ││
        │  │ ┌──────────────────────────┐││
        │  │ │SessionStatsProvider       │││ (with custom equality)
        │  │ │Provides: stats, methods  │││
        │  │ │                           │││
        │  │ │┌─────────────────────────┐│││
        │  │ ││ VimModeProvider         ││││ (vim mode state)
        │  │ ││ Provides: vim settings  ││││
        │  │ ││                          ││││
        │  │ ││┌────────────────────────┐││││
        │  │ │││ AppContainer           │││││ (creates contexts)
        │  │ │││ ├─ UIStateContext     │││││
        │  │ │││ ├─ UIActionsContext   │││││
        │  │ │││ └─ ConfigContext      │││││
        │  │ │││    │                   │││││
        │  │ │││    ▼                   │││││
        │  │ │││  App (root component) │││││
        │  │ │││    ↓                   │││││
        │  │ │││  DefaultAppLayout     │││││
        │  │ │││  (or ScreenReader...)  │││││
        │  │ └┤                         ││││
        │  │ └┤                         ││││
        │  │  └                         │││
        │  │                            ││
        │  └────────────────────────────┘│
        │                                 │
        └─────────────────────────────────┘
```

---

## 7. Service Integration Architecture

```
┌────────────────────────────────────────────────────────────┐
│                    Core Services                            │
│          (from @google/gemini-cli-core)                    │
├────────────────────────────────────────────────────────────┤
│  GeminiClient                                              │
│  ├─ streamChat()      ───→ Server Events                  │
│  ├─ models             ───→ Available Models              │
│  └─ submitToolResult()                                    │
│                                                             │
│  Config                                                    │
│  ├─ getScreenReader()  ───→ Accessibility                 │
│  ├─ getDebugMode()     ───→ Logging Level                 │
│  └─ paths, extensions                                     │
│                                                             │
│  ShellExecutionService                                    │
│  └─ executeCommand()   ───→ Shell Output                  │
│                                                             │
│  uiTelemetryService                                       │
│  ├─ on('update')       ───→ Metrics Updates              │
│  └─ getMetrics()       ───→ Current Metrics              │
│                                                             │
│  ideContextStore                                          │
│  └─ getContext()       ───→ IDE Info                      │
│                                                             │
│  ExtensionManager                                         │
│  ├─ loadExtensions()                                      │
│  ├─ getRegisteredCommands()                               │
│  └─ executeCommand()                                      │
└────────────────────────────────────────────────────────────┘
              ↑                    ↑                    ↑
              │                    │                    │
    ┌─────────┘          ┌─────────┘          ┌────────┘
    │                    │                    │
    ▼                    ▼                    ▼
┌──────────┐  ┌─────────────────┐  ┌──────────────┐
│useGemini│  │useReactToolSch.  │  │useExtensionU│
│Stream() │  │                  │  │pdates()     │
└──────────┘  └─────────────────┘  └──────────────┘
    │                    │                    │
    └─────────────────────┴────────────────────┘
              │
              ▼
    ┌─────────────────────┐
    │   AppContainer      │
    │  (Composes hooks)   │
    │   ↓                 │
    │ UIStateContext      │
    │ UIActionsContext    │
    └─────────────────────┘
```

---

## 8. Command Processing Pipeline

```
User Input: "/chat resume <tag>" (or any slash command)
                    │
                    ▼
    ┌─────────────────────────────────┐
    │ slashCommandProcessor.ts         │
    │ • Detect command name            │
    │ • Parse arguments                │
    └────────────┬────────────────────┘
                 │
                 ▼
    ┌─────────────────────────────────┐
    │ Find SlashCommand in registry    │
    │ • Check built-in commands       │
    │ • Check extension commands      │
    └────────────┬────────────────────┘
                 │
                 ▼
    ┌─────────────────────────────────┐
    │ CommandContext Created           │
    ├─────────────────────────────────┤
    │ services: {config, settings...} │
    │ ui: {addItem, clear, ...}       │
    │ session: {stats, allowlist}     │
    │ invocation: {raw, name, args}   │
    └────────────┬────────────────────┘
                 │
                 ▼
    ┌─────────────────────────────────┐
    │ Command Action Function          │
    │ (async or sync)                  │
    └────────────┬────────────────────┘
                 │
    ┌────────────┴────────────┐
    │                         │
    ▼                         ▼
Return Type               Return Type
(Discriminated Union)     (Discriminated Union)
├─ ToolActionReturn       ├─ QuitActionReturn
├─ MessageActionReturn    ├─ OpenDialogActionReturn
├─ SubmitPromptActionReturn
├─ LoadHistoryActionReturn
├─ ConfirmShellCommandsActionReturn
└─ ConfirmActionReturn
    │
    ▼
Process Result:
├─ Update history
├─ Open dialog
├─ Submit prompt
└─ Quit app
```

---

## 9. Tool Call State Machine

```
                        User Submits Prompt
                              │
                              ▼
    ┌──────────────────────────────────────┐
    │ Gemini API Returns Tool Call Request  │
    └──────────────┬───────────────────────┘
                   │
                   ▼
    ┌──────────────────────────────────────┐
    │ ToolCallStatus.Pending               │
    │ (Tool scheduled, not yet confirmed)  │
    └──────────────┬───────────────────────┘
                   │
        ┌──────────┴──────────┐
        │                     │
        ▼                     ▼
    AutoAccept?           Manual Confirm?
    (Settings)            (User approval)
        │                     │
        ▼                     ▼
    Confirming          Confirming
        │                     │
        └──────────┬──────────┘
                   │
                   ▼
    ┌──────────────────────────────────────┐
    │ ToolCallStatus.Executing             │
    │ (Tool running, PID tracked)          │
    └──────────────┬─────────���─────────────┘
                   │
        ┌──────────┴──────────┐
        │                     │
        ▼                     ▼
    Success                   Error
    (Exit code 0)          (Exit code ≠ 0)
        │                     │
        └──────────┬──────────┘
                   │
                   ▼
    ┌──────────────────────────────────────┐
    │ ToolCallStatus.Success/Error         │
    │ (Completed, result ready)            │
    └──────────────┬───────────────────────┘
                   │
                   ▼
    ┌──────────────────────────────────────┐
    │ Submit Result to Gemini              │
    │ (ResponseSubmittedToGemini flag set) │
    └──────────────┬───────────────────────┘
                   │
                   ▼
    ┌──────────────────────────────────────┐
    │ Next Turn: Stream New Content        │
    └──────────────────────────────────────┘
```

---

## 10. Data Flow: From Input to Display

```
User Types → KeypressContext → Components Subscribe
             (broadcast)                │
                                        ▼
                              InputPrompt/Editor
                                        │
                              (accumulate buffer)
                                        │
                              User Presses Enter
                                        │
                                        ▼
                          ┌────────────────────────┐
                          │ useGeminiStream() Hook │
                          │ (300+ lines)           │
                          └──────────┬─────────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    │                │                │
                    ▼                ▼                ▼
            Process Input    Query Gemini API    Stream Events
            ├─Slash cmds      └─ streamChat()    ├─ Content
            ├─@mentions                          ├─ ToolCall
            └─Shell mode                         └─ Finished
                    │                │                │
                    └────────────────┼────────────────┘
                                     │
                    ┌────────────────┴────────────────┐
                    │                                 │
                    ▼                                 ▼
            Process Tool Calls           Add to History
            (useReactToolScheduler)      └─ HistoryItemWithoutId
                    │                          │
            Execute/Confirm                     ▼
                    │                    ┌─────────────────────┐
                    │                    │ historyManager.     │
                    │                    │ addItem()           │
                    │                    └────────┬────────────┘
                    │                             │
                    └──────────────┬──────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │ Update UIState.history[]     │
                    └────────────┬─────────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────────┐
                    │ React Re-render              │
                    │ (HistoryItemDisplay)         │
                    └────────────┬─────────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────────┐
                    │ Render Message to Terminal   │
                    │ • HistoryItemGemini         │
                    │ • HistoryItemToolGroup      │
                    │ • HistoryItemStats          │
                    │ etc.                         │
                    └──────────────────────────────┘
```

---

## 11. Event Subscription Patterns

```
┌─────────────────────────────────────────┐
│     AppEvents (Pub/Sub Pattern)         │
├─────────────────────────────────────────┤
│ export enum AppEvent {                  │
│   LogError,                             │
│   OpenDebugConsole,                     │
│   ...                                   │
│ }                                       │
│                                         │
│ Usage:                                  │
│ appEvents.emit(AppEvent.LogError, msg)  │
│ appEvents.on(AppEvent.LogError, fn)     │
└─────────────────────────────────────────┘
           ↑                    ↑
     Publishers              Subscribers
     ├─ error handler      ├─ setDebugMessage
     ├─ tool complete      ├─ open dialog
     └─ ...                └─ ...

┌─────────────────────────────────────────┐
│   KeypressContext (Subscription)        │
├─────────────────────────────────────────┤
│ subscribe(handler: KeypressHandler)     │
│ unsubscribe(handler: KeypressHandler)   │
│                                         │
│ Broadcast from KeypressProvider:        │
│ • InputPrompt subscribes                │
│ • Editor subscribes                     │
│ • Dialog handlers subscribe             │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│   Service Events (e.g., telemetry)      │
├─────────────────────────────────────────┤
│ uiTelemetryService.on('update', fn)     │
│                                         │
│ Updates SessionStatsProvider:           │
│ → setStats() with new metrics           │
└────────────���────────────────────────────┘
```

---

## 12. Hook Composition in AppContainer

```
AppContainer (1419 lines)
│
├─ useHistory()
│  ├─ history: HistoryItem[]
│  ├─ addItem()
│  ├─ loadHistory()
│  └─ clearHistory()
│
├─ useMemoryMonitor()
│
├─ useThemeCommand()
│
├─ useAuthCommand()
│
├─ useSettings()
│
├─ useConfig()
│
├─ useGeminiStream()
│  ├─ Manages API streaming
│  ├─ Tool scheduling
│  └─ History updates
│
├─ useReactToolScheduler()
│  ├─ trackedToolCalls[]
│  ├─ schedule()
│  └─ markAsSubmitted()
│
├─ useConsoleMessages()
│
├─ useTerminalSize()
│
├─ useLoadingIndicator()
│
├─ useKeypress()
│
├─ useSessionStats()
│
└─ ... 10+ more hooks
   │
   └─→ Compose into UIState
       └─ Provider wraps App
          └─ Components use useUIState()
```

