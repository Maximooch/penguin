# Penguin TUI Improvement Plan

## Overview

This document outlines a comprehensive plan to enhance the Penguin TUI, bringing it to feature parity with the CLI while improving upon the user experience. The goal is to create a modern, efficient, and visually appealing interface that serves as the primary interaction method for Penguin.

---

## Core Requirements

### 1. Tool/Action Display System
**Priority: High**  
**Complexity: High**

#### Requirements
- Display both Action Tags (from `parser.py`) and Tool executions (from `tool_manager.py`)
- Collapsible details for both input parameters and output results
- Clear visual distinction between different action types
- Real-time status updates during execution

#### Implementation Considerations
- Need to handle both `ActionType` enum from parser.py and tool schemas from tool_manager.py
- Create unified display widget that can handle both paradigms
- Consider performance impact of rendering complex tool outputs

#### Proposed Design
```
┌─ 🔧 Tool: workspace_search ─────────────────[▼]─┐
│ Status: Running... ⟳                            │
│ ─────────────────────────────────────────────── │
│ ▼ Parameters:                                   │
│   query: "authentication flow"                  │
│   max_results: 5                                │
│ ─────────────────────────────────────────────── │
│ ▼ Results: (click to expand)                    │
└─────────────────────────────────────────────────┘
```

#### Immediate Visual Enhancements (Quick Wins)
These refinements keep the current architecture, focus on UX polish, and are safe to implement before Phase 2.

- Header
  - Show live elapsed time while running; freeze on completion.
  - Status-colored accent (pending, running, success, failed, cancelled) with a subtle fade on transition.
  - Hover/focus outline for keyboard users; header right-click/shortcut to copy raw execution JSON.

- Parameters
  - Auto-collapse oversized values (>15 lines) with a “show more” toggle per key.
  - Render keys in bold monospace; lightly highlight value types (bool, number, string, null).
  - Detect filesystem paths and URLs; make them activatable (open in viewer/editor or browser).

- Result
  - While streaming, show a tiny progress shimmer or dot animation in the gutter.
  - Mini toolbar: Copy result, Rerun tool, and Download if a file path is returned.
  - Pretty-print JSON with fold/unfold (keyboard j/k to expand/collapse when focused).
  - For very large plain-text/code, open in a pager dialog instead of overflowing the card.

- Layout & Spacing
  - Harmonize corner radii for card and its inner sections; slightly reduce vertical padding.
  - Darker divider between Parameters and Result for clearer separation.

- Accessibility & Navigation
  - Left/Right arrows toggle collapse in addition to Space/Enter.
  - Preserve scroll position when expanding/collapsing sections.
  - Provide quick jumps: “gg” to first widget, “G” to last.

- Performance hygiene (for long transcripts)
  - Lazy-mount inner content when a section first opens.
  - When a widget scrolls far off-screen, trim in-memory result strings to head/tail windows (persist full content on disk if downloadable).

- Extensibility hooks
  - `on_card_mount` signal so plugins can add custom tabs (e.g., Diff view for `apply_diff`).
  - Optional per-card footer area for thumbnails or action-specific controls.

These changes are Phase‑1 friendly (no streaming refactor required) and align with the Phase‑2 theme work.

### 2. Complete Command System Migration
**Priority: High**  
**Complexity: Medium**

#### Commands to Migrate
- **Config Commands**: `setup`, `edit`, `check`, `test-routing`, `debug`
- **Project Commands**: `create`, `list`, `delete`, `run`, `update`, `display`
- **Task Commands**: `create`, `list`, `start`, `complete`, `delete`, `update`, `display`
- **Utility Commands**: `perf-test`, `profile`
- **Conversation Commands**: `continue`, `resume`, `save`, `list`
- **Model Commands**: `models`, `model`, `set`
- **Context Commands**: `context`, `clear-context`


#### Future Enhancement
- Implement `commands.yml` for user customization
- Allow command aliases and shortcuts
- Support command history and autocomplete

### 3. Visual Theme System
**Priority: Medium**  
**Complexity: Low**

#### Proposed Themes
1. **Deep Ocean** (Current - dark blue)
2. **Nord** (Popular, muted colors)
3. **Dracula** (High contrast purple/pink)
4. **Solarized** (Light/Dark variants)
5. **Gruvbox** (Warm, retro feel)
6. **Custom** (User-defined via config)

#### Implementation
- CSS variables for easy theme switching
- Theme preview command
- Persist theme preference

### 4. Enhanced Status Panel
**Priority: Medium**  
**Complexity: Medium**

#### Components
- Current model indicator with provider
- Token usage (input/output/reasoning/total)
- Active task/project context
- Memory usage indicator
- Connection status (for remote models)
- Current working directory
- Time elapsed for current conversation

#### Design
```
┌─────────────────────────────────────────────────┐
│ gpt-4 | Tokens: 1.2k/0.8k/0.2k | Task: refactor│
│ Mem: 85MB | Project: penguin-tui | ⏱ 00:03:42  │
└─────────────────────────────────────────────────┘
```

### 5. Multi-Panel Layout with Conversation Sidebar
**Priority: Low (Phase 2)**  
**Complexity: Very High**

#### Layout Structure
```
┌─────┬───────────────────────────────────────────┐
│ ◀▶ │              Penguin AI                     │
├─────┼───────────────────────────────────────────┤
│     │                                             │
│ 🗨️  │                                             │
│     │         Main Conversation Area             │
│ T1  │                                             │
│ T2  │                                             │
│ T3  │                                             │
│ ... │                                             │
│     │                                             │
├─────┴───────────────────────────────────────────┤
│              Input Area                          │
├─────────────────────────────────────────────────┤
│              Status Bar                          │
└─────────────────────────────────────────────────┘
```

#### Sidebar Features
- Collapsible (◀▶ toggle button)
- List of conversation threads
- Thread preview (first message + timestamp)
- Quick switch between conversations
- Search conversations
- Pin important threads

---

## Implementation Phases

### Phase 1: Core Functionality (Week 1-2)
1. **Tool/Action Display Widget**
   - Create `ToolExecutionWidget` class
   - Implement collapsible sections
   - Add status indicators and spinners
   - Handle both action tags and tool executions

2. **Command Registry System**
   - Port all CLI commands to TUI
   - Create command router/registry
   - Implement help system with command discovery

3. **Enhanced Code Rendering**
   - Improve syntax highlighting
   - Add execution status indicators
   - Implement per-block copy functionality
   - Show diff views for file edits

### Phase 2: Visual Enhancement (Week 2-3)
1. **Theme System**
   - Implement CSS variables
   - Create theme switcher
   - Design additional themes
   - Add theme preview

2. **Status Panel Upgrade**
   - Design compact status layout
   - Implement real-time updates
   - Add progress indicators
   - Show contextual information

3. **Message Rendering Improvements**
   - Better handling of multimodal content
   - Improved table/list formatting
   - Enhanced error display
   - Smooth streaming updates

### Phase 3: Advanced Features (Week 3-4)
1. **Conversation Sidebar**
   - Implement collapsible sidebar
   - Create thread list widget
   - Add thread management
   - Implement search/filter

2. **Performance Optimization**
   - Virtual scrolling for long conversations
   - Lazy loading of thread previews
   - Efficient re-rendering
   - Memory management

3. **Polish & Testing**
   - Comprehensive testing
   - Performance profiling
   - Documentation
   - User feedback integration

---

## Technical Considerations

### Architecture Decisions

1. **Event-Driven Updates**
   - All UI updates through event system
   - No direct manipulation of UI from core
   - Clean separation of concerns

2. **Widget Composition**
   - Small, focused widgets
   - Composable design
   - Reusable components

3. **State Management**
   - Centralized state for UI
   - Reactive updates
   - Efficient diff computation

### Performance Optimizations

1. **Rendering**
   - Batch DOM updates
   - Use virtual scrolling for long lists
   - Lazy render collapsed sections
   - Debounce rapid updates

2. **Memory**
   - Limit conversation history in memory
   - Implement message pagination
   - Clean up old widget instances
   - Use weak references where appropriate

3. **Streaming**
   - Buffer streaming updates
   - Batch render on idle
   - Smart scroll behavior
   - Prevent layout thrashing

---

## Technical Debt to Address

### Current Issues

1. **Complex Streaming Logic**
   - The 297-line chain in `ChatMessage` needs refactoring
   - Should use state machine pattern
   - Separate concerns (cleaning, parsing, rendering)

2. **Command Handling**
   - Currently delegates everything to `interface.py`
   - Should have direct command implementations
   - Need better error handling

3. **CSS Organization**
   - No CSS variables for theming
   - Hardcoded colors throughout
   - Inconsistent spacing/sizing

4. **Memory Leaks**
   - Widgets not properly cleaned up
   - Event handlers not removed
   - Streaming artifacts accumulate

### Refactoring Plan

1. **Streaming State Machine**
   ```python
   class StreamingStateMachine:
       states = ['idle', 'streaming', 'cleaning', 'complete']
       
       def process_chunk(self, chunk):
           # Handle based on current state
           pass
   ```

2. **Command Architecture**
   ```python
   class CommandRegistry:
       def __init__(self):
           self.commands = {}
           self._register_builtin_commands()
       
       def register(self, name, handler, aliases=None):
           # Register command with optional aliases
           pass
   ```

3. **CSS Variables**
   ```css
   :root {
       --primary-bg: #0c141f;
       --primary-fg: #dadada;
       --accent: #89cff0;
       --spacing-unit: 0.5rem;
   }
   ```

4. **Widget Organization**
   - Create `penguin/cli/widgets.py` for custom widgets
   - Move complex widgets like `ToolExecutionWidget` to separate module
   - Establish widget base classes and interfaces
   - Enable widget reusability across different contexts

---

## Future Enhancements

### Short Term (1-3 months)
1. **Plugin System**
   - Allow custom widgets
   - User-defined commands
   - Theme marketplace

2. **Export Features**
   - Export conversation as markdown
   - Save code snippets
   - Generate documentation

3. **Collaboration**
   - Share conversations
   - Real-time collaboration
   - Comment on threads

### Long Term (3-6 months)
1. **Advanced UI Components**
   - Split panes for code/chat
   - Floating tool windows
   - Customizable layouts
   - Keyboard-driven workflow

2. **Intelligence Features**
   - Conversation search
   - Smart suggestions
   - Context awareness
   - Pattern learning

3. **Integration Ecosystem**
   - IDE plugins
   - Browser extension
   - Mobile companion
   - API access

### Additional Future Considerations
- **CommandRegistry as single source**: Make `CommandRegistry` authoritative for names, aliases, arg schemas, help text, and execution callbacks. Autogenerate help and autocomplete from specs. Allow user overrides via `commands.yml`.
- **Config layering and location**: Load `commands.yml` from the same directory as `config.yml`, layering: built-in → repo-level → user-level. Consider hot-reload on file changes.
- **Unified argument parsing**: Centralize parsing/validation in `PenguinInterface` so both non-interactive CLI (`-p/--prompt`) and TUI share logic without importing Textual.
- **Context-aware autocomplete**: Hierarchical completion (command → subcommand → flags → values) with dynamic value completers (e.g., model IDs, conversation IDs). Cache to maintain low latency.
- **Error UX for commands**: On parse/validation errors, display usage with examples and nearest-match suggestions. Keep behavior consistent across CLI and TUI.
- **Cancellation and concurrency**: Add `/cancel <id>` and a keybinding to cancel foreground commands; optionally support background jobs with job IDs and a lightweight jobs panel.
- **Permissions and safety**: Introduce a policy layer to gate destructive commands (filesystem, code execution), confirmations, environment-based restrictions, and a safe mode.
- **Telemetry and auditing**: Optional audit trail of executed commands (with redacted args), visible in TUI debug view and persisted; summarize command metrics in the status panel.
- **Dedicated output widgets**: Beyond markdown defaults, provide widgets for model picker, token usage table, and file diffs. Fix trailing whitespace/gap issues in tool/action widgets via content normalization and CSS/layout adjustments.
- **Hooks and extensibility**: Pre/post-command hooks, custom completers, and a plugin API to approach IDE/Claude Code parity while sandboxing third-party code.
- **Internationalization**: i18n/l10n for help, errors, and status messages; ensure RTL and wide-character rendering work well.
- **Accessibility**: Improve keyboard navigation maps, focus outlines, and screen-reader hints; configurable keybindings.
- **Testing strategy**: Golden tests for help/usage, parser property tests, latency budgets for autocomplete, and snapshot tests for widget rendering.
- **Observability**: Expose command/job states in the status panel, simple diagnostics toggles, and profiling hooks for command execution paths.

---

## Success Metrics

1. **Performance**
   - Startup time < 2 seconds
   - Smooth 60fps scrolling
   - Response time < 100ms for commands
   - Memory usage < 200MB baseline

2. **Usability**
   - All CLI features available
   - Intuitive command discovery
   - Efficient keyboard navigation
   - Clear visual feedback

3. **Reliability**
   - No crashes during streaming
   - Graceful error handling
   - State persistence
   - Clean shutdown

---

## Risk Mitigation

1. **Complexity Creep**
   - Start with MVP features
   - Iterate based on feedback
   - Avoid over-engineering
   - Keep it simple

2. **Performance Degradation**
   - Profile regularly
   - Set performance budgets
   - Monitor memory usage
   - Test with large conversations

3. **User Migration**
   - Maintain CLI during transition
   - Provide migration guide
   - Gather feedback early
   - Iterate quickly

---

## Conclusion

This improvement plan transforms the Penguin TUI from a basic interface into a powerful, modern development environment. By focusing on core functionality first, then enhancing visuals and finally adding advanced features, we ensure a stable and usable product at each phase.

The key to success is maintaining simplicity while adding power - making the common cases easy while enabling advanced workflows. With careful implementation of the outlined phases, the TUI will become the preferred interface for Penguin users.