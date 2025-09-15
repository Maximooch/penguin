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
   - Batch updates to avoid unnecessary relayouts
   - Use virtual scrolling for long lists (Phase B)
   - Lazy render collapsed sections (mount heavy content on expand only)
   - Debounce rapid updates (throttle streaming Markdown updates)
   - Coalesce status/sidebar updates (skip identical frames)

2. **Scrolling & Autoscroll**
   - Implement an autoscroll gate: only auto-scroll when the user is at/near the bottom
   - Debounce scroll-to-bottom requests (≈80–120ms) to avoid fighting manual scrolling
   - Provide a quick jump-to-bottom to re-enable autoscroll
   - Prepare for Textual granular mouse reporting (pixel-level) when supported by terminal/Textual

3. **Memory**
   - Limit conversation history in memory
   - Implement message pagination
   - Clean up old widget instances
   - Use weak references where appropriate

4. **Streaming**
   - Buffer streaming updates (centralize in StreamingStateMachine)
   - Batch renders on a cadence (~8–10 FPS perceived)
   - Smart scroll behavior: do not scroll when user is browsing history
   - Prevent layout thrashing by minimizing parent refreshes and reflows

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

---

## Performance Plan (Updated)

This plan incorporates optimizations to address freezes during plain assistant streaming and choppy scrolling, while preparing for Textual’s granular (pixel-level) scrolling where available.

### High-Impact, Low-Risk Wins (Immediate)
- Lift hot regexes to module scope: precompile once and reuse.
  - Implementation: move `DETAILS_RE` from inside `ChatMessage.compose()` to module scope and reuse everywhere.
- Reduce parsing during streaming: keep the streaming path append-only and defer heavy transforms to finalization.
  - Implementation: append raw chunks during streaming; perform fence splitting, `<details>` parsing, and code fencing in `end_stream()`.
- Increase streaming buffer and cadence: reduce Markdown reparses.
  - Implementation: raise `ChatMessage._buffer_size_limit` from 500 → 1500–2000; increase `_stream_update_min_interval` from ~0.22s → ~0.28–0.32s (adaptive).
- Cache and reuse Markdown/Expander children: avoid remounting in hot paths.
  - Implementation: create child widgets on first compose; update via Markdown stream API; only rebuild on density toggles.
- Precompute language guesses with a tiny LRU: replace ad‑hoc `re.search` calls in `_format_system_output`.
  - Implementation: precompile language regexes, add a small LRU for recent guesses.
- Debounce scroll and gate by position: fewer `scroll_end()` calls, smoother streams.
  - Implementation: keep autoscroll only when near bottom (already implemented); increase debounce to ~200–240ms.
- Group response threads (from IDE extension message design): collapse non‑final phases by default.
  - Implementation: add response thread container keyed by `response_id` with phases `analysis|tools|final`, plus a single “Show steps” toggle.

### Immediate (Phase A)
- Autoscroll gate + debounced scroll (80–120ms) to prevent fighting the user while they scroll
- Throttle streaming Markdown updates (~120–160ms) and prefer Textual’s streaming API
- Coalesce sidebar/status updates (skip identical frames)
- Keep previews short for large tool/action outputs; defer heavy formatting to background threads

### Near-term (Phase B)
- Virtualized message list (render only visible messages)
- Adopt `StreamingStateMachine` to centralize chunk buffering and cleanup, reducing widget churn
- Enable granular mouse reporting (Textual ≥ 2.0, Kitty/Ghostty, etc.) for smoother scroll deltas; capability-gated

### Tool/Action Widgets
- Mount minimal previews when collapsed; mount full Markdown on expand (lazy mounting)
- Preserve head/tail windows for very large strings; offer copy/download for full content

### Response-thread Grouping (Performance-focused)
- Contract: emit `response_start`, `stream_chunk{phase}`, `response_final` with `response_id`.
- UI: group all interim messages by `response_id`; render `analysis` collapsed by default, `final` as the visible message; one “Show steps” toggle per response.
- Benefit: fewer live nodes and markdown reparses; de‑dupe hidden intermediary content; simpler autoscroll behavior.

### Profiling & Validation (Quick)
- Pyinstrument quick path: profile one end‑to‑end response and open HTML.
  - Example: `pyinstrument -r html -o tui_profile.html python -c "from penguin.cli.tui import TUI; TUI.run()"`
- Micro‑metrics: log per-frame render time, stream flush time, and scroll debounce trigger counts; raise warnings when budgets exceeded.
- Script: add `scripts/profile_tui_stream.py` to run a simple instrumented stream (no pytest required).
- Textual lessons learned: precompute static queries/regexes; avoid expensive object creation (e.g., prefer `tuple` over `NamedTuple` in hot loops) as highlighted in Textual’s TextArea profiling write-up.

### Targets & Budgets
- Target ~8–10 FPS perceived streaming updates; coalesce scroll and status changes into that cadence.
- Maintain baseline memory under ~200MB with long transcripts via trimming, stubbing, and lazy hydration.

### References
- Textual smooth scrolling (pixel reporting + pixel-size reporting; requires Textual ≥ 2.0 and supporting terminals such as Kitty, Ghostty).

### Implementation Pointers
- Module-level regexes and patterns: move `DETAILS_RE` and language-guess patterns to module scope for reuse.
- Append-only streaming path: avoid parsing during streaming; perform parsing/formatting in `end_stream()`.
- Cache widget references: store the first `TextualMarkdown` and any first `Expander`/fallback references; avoid `query_one` in hot loops.
- Response-thread container: add a grouped container with a “Show steps” toggle; route phased events accordingly.
- Feature detection: enable pixel-aware mouse reporting when supported to smooth deltas.

### Configurable Runtime Switches (via /debug)
- Stream throttle ms, scroll debounce ms, preview line count, linkify behavior, default reasoning/tool visibility; persist in TUI prefs.

### Nice-to-haves in Hot Paths
- Replace slow constructs in tight loops; reduce short‑lived allocations; prefer simple tuples over `NamedTuple` where applicable.

---

## Questions / Suggestions (for quick alignment)
- Visibility defaults: should `analysis` stay collapsed even in detailed view, or only in compact?
- Grouping affordance: single “Show steps” per response vs. small expanders inline per section?
- Final marker vs. event: rely solely on `response_final` events or also parse an explicit `<final>` marker as a fallback?
- Tool previews: keep a single global `tools_preview_lines`, or vary by view (compact vs detailed)?
- Adaptive throttling: acceptable FPS floor/ceiling for auto‑tuning stream cadence (e.g., 6–14 FPS window)?
- Pixel scrolling: OK to soft‑gate by capability and silently fall back to cell-based scrolling?