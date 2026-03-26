# Penguin Python CLI Track - Refactoring Plan

**Objective:** Improve Python CLI presentation layer using Kimi-CLI rendering patterns

**Duration:** 3-4 hours of focused improvements

**Context:** This is Track 1 of a parallel implementation experiment. Track 2 is refactoring the TypeScript CLI with Gemini patterns. We'll compare both approaches to make a data-driven decision.

**IMPORTANT:** The CLI is ~10% of the Penguin codebase (in code size and importance). It's a **thin presentation layer** that renders events from the engine. Most features already exist in the system layer.

**Current State:** Penguin has an existing Python CLI at `penguin/cli/cli.py` using typer, rich, and prompt_toolkit.

**Reference Documents:**
- [Kimi-CLI Analysis](./penguin-cli/docs/reference-analysis-kimi-cli.md)
- [Reference Comparison](./penguin-cli/docs/reference-comparison.md)
- Current code: `penguin/cli/cli.py`, `penguin/cli/interface.py`, `penguin/cli/ui.py`, `penguin/core.py`, `penguin/engine.py`

---

## Success Criteria

By the end of this refactoring, we should have:

✅ **Improved Python CLI** with:
- Better event rendering (smooth streaming like Kimi)
- Improved integration with existing CheckpointManager (UI for /checkpoint, /rollback, /branch, /checkpoints)
- Better display of context window usage (using existing ContextWindowManager for /tokens, /truncations)
- Cleaner code organization (decompose cli.py if needed)
- Improved input handling (better prompt_toolkit usage)
- Performance optimizations (rendering, not system features)

✅ **Evaluation Document** (`evaluation_python.md`) with:
- Before/after rendering comparison
- Kimi patterns that helped for CLI
- Performance improvements
- Development velocity notes
- Subjective "feel" assessment

✅ **Comparison-ready** codebase:
- Clean git history (atomic commits)
- Performance benchmarks
- Documented improvements

---

## Current State Analysis

### Existing Architecture

```
penguin/cli/                        # ~10% of codebase - PRESENTATION LAYER
├── cli.py (3,780+ lines)           # Main CLI with PenguinCLI class
│   ├── Typer commands
│   ├── PenguinCLI class (interactive session)
│   └── Rich-based rendering
├── interface.py                     # PenguinInterface (business logic layer)
├── ui.py                           # UI components
├── renderer.py                     # UnifiedRenderer
└── commands.py                     # CommandRegistry

penguin/system/                     # ~50% of codebase - SYSTEM LAYER (ALREADY EXISTS!)
├── conversation_manager.py         # ✅ Session persistence (conversation.json)
├── context_window.py              # ✅ Token budgeting, trimming, truncation tracking
├── checkpoint_manager.py          # ✅ Checkpoint/rollback/branching system
├── session_manager.py             # ✅ Session management
├── snapshot_manager.py            # ✅ Time-travel debugging
└── state.py                       # ✅ Message, Session, MessageCategory

penguin/
├── core.py                        # PenguinCore (main engine)
├── engine.py                      # Core engine logic
└── [tools, providers, etc]        # ~40% of codebase
```

### Current Features (Already Exist in System Layer!)

✅ **Session Persistence:** conversation.json files (SessionManager)
✅ **Checkpoint System:** Full checkpoint/rollback/branching (CheckpointManager)
✅ **Context Window Management:** Token budgeting, trimming, truncation tracking (ContextWindowManager)
✅ **Multi-agent Support:** Agent isolation, sub-agents (ConversationManager)
✅ **Snapshot/Branching:** Time-travel debugging (SnapshotManager)

### Current CLI Features (Presentation Layer)

✅ **CLI Framework:** typer
✅ **TUI Input:** prompt_toolkit (multi-line, keybindings)
✅ **Output:** Rich (markdown, syntax highlighting, panels)
✅ **Streaming:** Event-driven streaming from Core
✅ **Tools:** ToolManager with many tools
✅ **Commands:** CommandRegistry system

### What Needs Improvement (CLI-Specific)

- ⚠️ **Event Rendering:** Could be smoother (Kimi's clean streaming output)
- ⚠️ **Checkpoint UI:** CLI commands for existing CheckpointManager (expose /checkpoint, /rollback, /branch, /checkpoints)
- ⚠️ **Context Window Display:** Show token usage and truncation events (/tokens, /truncations)
- ⚠️ **Architecture:** cli.py is 3,780+ lines (could decompose)
- ⚠️ **Input Handling:** Could improve prompt_toolkit integration
- ❌ **Tool Approval Flow:** This is a larger system feature, not just CLI

---

## Phase 1: Setup & Analysis (20-30 min)

### 1. Create Evaluation Document

Create `evaluation_python.md`:

```markdown
# Python CLI Track - Evaluation Log

## Initial Assessment

### Current State
- File: penguin/cli/cli.py (3,780+ lines)
- Architecture: Typer + Rich + prompt_toolkit
- Features: Interactive chat, streaming, tools, commands
- System Layer: ConversationManager, CheckpointManager, ContextWindowManager (ALREADY EXIST!)

### Current Issues (CLI-Specific)
- cli.py is very large (3,780+ lines)
- Event rendering could be smoother
- No CLI commands for existing CheckpointManager
- Not displaying truncation events from TruncationTracker
- [Other issues discovered during analysis]

### Planned Improvements (CLI ONLY)
- Improve event rendering (Kimi patterns)
- Add /checkpoint, /revert commands (integrate with existing CheckpointManager)
- Display context window stats (integrate with existing ContextWindowManager)
- Better code organization (decompose cli.py)
- [Others as discovered]

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
- cli.py: 3,780+ lines
- [Other measurements]

**After:**
- cli.py: X lines
- [Other measurements]

### Performance
**Before:**
- Startup time: ? ms
- Memory usage: ? MB

**After:**
- Startup time: X ms
- Memory usage: X MB

### Development Velocity
- Time to add JSONL history: X hours
- Time to add checkpoints: X hours
- Time to implement wire protocol: X hours
- Total time: X hours

### Subjective Assessment (1-5)
- Refactoring experience: ?/5
- Kimi patterns helpfulness: ?/5
- Code organization improvement: ?/5
- Python ecosystem: ?/5
- Overall satisfaction: ?/5

### Key Insights
1.
2.
3.

### Recommendation
- [ ] Continue with Python track
- [ ] Switch to TypeScript track
- [ ] Keep both
```

### 2. Understand Current Architecture

**Read and document:**

```bash
# Read key files to understand current architecture
# - penguin/cli/cli.py (main CLI)
# - penguin/cli/interface.py (business logic)
# - penguin/system/conversation_manager.py (session persistence)
# - penguin/system/checkpoint_manager.py (checkpoint system)
# - penguin/system/context_window.py (token management, truncation)
```

**Document in evaluation:**
- How does CLI currently render events?
- How do events flow from Core → CLI?
- What's the current event system structure?
- Is CheckpointManager exposed in CLI commands?
- Is TruncationTracker data displayed to user?

### 3. Create Feature Branch

```bash
cd penguin
git checkout -b refactor/kimi-patterns
```

### 4. Benchmark Current Performance

```bash
# Startup time
time penguin --version

# Memory usage during chat
# TODO: Add memory profiling

# Document in evaluation_python.md
```

---

## Phase 2: Integrate CheckpointManager UI (45-60 min)

### Goal: Add CLI commands to expose existing CheckpointManager functionality

### 1. Understand CheckpointManager

**Read:**
- `penguin/system/checkpoint_manager.py`
- How ConversationManager.create_manual_checkpoint() works
- How ConversationManager.rollback_to_checkpoint() works
- How ConversationManager.list_checkpoints() works

**Document:**
- CheckpointManager is already implemented! ✅
- Checkpoint types: MANUAL, AUTO, BRANCH
- All functionality exists, just needs CLI commands

### 2. Add Checkpoint Commands

**Modify:** `penguin/cli/commands.py` or CommandRegistry

```python
# Add checkpoint commands that integrate with existing CheckpointManager

@command_registry.command("/checkpoint")
async def checkpoint_command(name: str = None, description: str = None):
    """Create a manual checkpoint"""
    try:
        checkpoint_id = await conversation_manager.create_manual_checkpoint(
            name=name,
            description=description
        )
        console.print(f"[green]✓ Checkpoint created: {checkpoint_id}[/green]")
        if name:
            console.print(f"  Name: {name}")
    except Exception as e:
        console.print(f"[red]✗ Failed to create checkpoint: {e}[/red]")

@command_registry.command("/rollback")
async def rollback_command(checkpoint_id: str):
    """Rollback to a specific checkpoint"""
    try:
        success = await conversation_manager.rollback_to_checkpoint(checkpoint_id)
        if success:
            console.print(f"[green]✓ Rolled back to checkpoint: {checkpoint_id}[/green]")
        else:
            console.print(f"[red]✗ Rollback failed[/red]")
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")

@command_registry.command("/checkpoints")
async def list_checkpoints_command(limit: int = 20):
    """List available checkpoints"""
    try:
        checkpoints = conversation_manager.list_checkpoints(limit=limit)

        if not checkpoints:
            console.print("[yellow]No checkpoints found[/yellow]")
            return

        from rich.table import Table
        table = Table(title=f"Checkpoints ({len(checkpoints)})")
        table.add_column("ID", style="cyan")
        table.add_column("Type", style="blue")
        table.add_column("Name", style="green")
        table.add_column("Timestamp", style="yellow")

        for cp in checkpoints:
            table.add_row(
                cp.get("id", "?"),
                cp.get("checkpoint_type", "?"),
                cp.get("name", "-"),
                cp.get("timestamp", "?")
            )

        console.print(table)
    except Exception as e:
        console.print(f"[red]✗ Error listing checkpoints: {e}[/red]")

@command_registry.command("/branch")
async def branch_command(checkpoint_id: str, name: str = None, description: str = None):
    """Create a new branch from a checkpoint"""
    try:
        branch_id = await conversation_manager.branch_from_checkpoint(
            checkpoint_id=checkpoint_id,
            name=name,
            description=description
        )
        if branch_id:
            console.print(f"[green]✓ Branch created: {branch_id}[/green]")
        else:
            console.print(f"[red]✗ Branch creation failed[/red]")
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
```

### 3. Test Checkpoint Integration

```bash
# Start chat
`penguin`

# Send message "List files in src/"
# Create checkpoint: /checkpoint "before file ops"
# Send message "Create test.py"
# List checkpoints: /checkpoints
# Rollback: /rollback <checkpoint_id>
# Verify conversation rolled back correctly
```

**Update evaluation_python.md:**
- Was CheckpointManager easy to integrate?
- Does the CLI feel natural?
- User experience of /checkpoint commands?

---

## Phase 3: Display Context Window Stats (30-45 min)

### Goal: Show context window usage and truncation events using existing ContextWindowManager

### 1. Understand ContextWindowManager

**Read:**
- `penguin/system/context_window.py`
- TruncationTracker class (records truncation events)
- ConversationManager.get_token_usage() method

**Document:**
- ContextWindowManager already tracks everything! ✅
- TruncationTracker records when messages are removed
- Token usage available per category (SYSTEM, CONTEXT, DIALOG, etc.)

### 2. Add Context Window Display Command

**Modify:** `penguin/cli/commands.py` or CommandRegistry

```python
# Add command to display context window usage

@command_registry.command("/tokens")
async def tokens_command():
    """Display token usage and context window stats"""
    try:
        usage = conversation_manager.get_token_usage()

        from rich.table import Table
        from rich.panel import Panel

        # Create main stats table
        table = Table(title="Context Window Usage")
        table.add_column("Category", style="cyan")
        table.add_column("Current", style="green", justify="right")
        table.add_column("Max", style="blue", justify="right")
        table.add_column("Usage", style="yellow", justify="right")

        categories = usage.get("categories", {})
        for category_name, tokens in categories.items():
            max_tokens = usage.get("max_tokens", 0)  # Get from budget
            percentage = (tokens / max_tokens * 100) if max_tokens > 0 else 0

            table.add_row(
                category_name,
                f"{tokens:,}",
                f"{max_tokens:,}",
                f"{percentage:.1f}%"
            )

        # Add total row
        total = usage.get("current_total_tokens", 0)
        max_total = usage.get("max_tokens", 0)
        pct = usage.get("percentage", 0)

        table.add_row(
            "TOTAL",
            f"{total:,}",
            f"{max_total:,}",
            f"{pct:.1f}%",
            style="bold"
        )

        console.print(table)

        # Show truncation stats if any
        truncations = usage.get("truncations", {})
        if truncations and truncations.get("total_truncations", 0) > 0:
            trunc_panel = Panel(
                f"Messages removed: {truncations['messages_removed']}\n"
                f"Tokens freed: {truncations['tokens_freed']:,}\n"
                f"Truncation events: {truncations['total_truncations']}",
                title="[yellow]Context Trimming Active[/yellow]",
                border_style="yellow"
            )
            console.print(trunc_panel)

    except Exception as e:
        console.print(f"[red]✗ Error getting token usage: {e}[/red]")

@command_registry.command("/truncations")
async def truncations_command(limit: int = 10):
    """Display recent truncation events"""
    try:
        usage = conversation_manager.get_token_usage()
        truncations = usage.get("truncations", {})
        recent_events = truncations.get("recent_events", [])

        if not recent_events:
            console.print("[green]No truncation events yet[/green]")
            return

        from rich.table import Table
        table = Table(title=f"Recent Truncation Events ({len(recent_events)})")
        table.add_column("Category", style="cyan")
        table.add_column("Messages Removed", style="red", justify="right")
        table.add_column("Tokens Freed", style="green", justify="right")
        table.add_column("Timestamp", style="yellow")

        for event in recent_events[:limit]:
            table.add_row(
                event.get("category", "?"),
                str(event.get("messages_removed", 0)),
                f"{event.get('tokens_freed', 0):,}",
                event.get("timestamp", "?")
            )

        console.print(table)

    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
```

### 3. Test Context Window Display

```bash
# Start chat
penguin

# Check token usage: /tokens
# Have a long conversation
# Check again: /tokens (should show higher usage)
# Check truncations: /truncations
```

**Update evaluation_python.md:**
- Easy to integrate with existing ContextWindowManager?
- Are the stats useful to users?

---

## Phase 4: Improve Event Rendering (60-75 min)

### Goal: Smoother streaming output inspired by Kimi-CLI

### 1. Analyze Current Rendering

**Document:**
- How does CLI currently display streaming tokens?
- Is there flickering or excessive redraws?
- How are tool calls displayed?
- How are status updates shown?

**Look at:**
- `penguin/cli/renderer.py` - UnifiedRenderer
- `penguin/cli/ui.py` - UI components
- How Rich.Live is used (if at all)

### 2. Implement Live Streaming Display

**Kimi pattern:** Use Rich.Live for smooth streaming without flickering

**Create/Modify:** `penguin/cli/streaming_display.py`

```python
"""
Smooth streaming display inspired by Kimi-CLI.
Uses Rich.Live for flicker-free updates.
"""

from rich.live import Live
from rich.console import Console, Group
from rich.panel import Panel
from rich.markdown import Markdown
from rich.spinner import Spinner
from rich.text import Text
from typing import Optional

class StreamingDisplay:
    """Manages live streaming display"""

    def __init__(self):
        self.console = Console()
        self.live: Optional[Live] = None
        self.current_message = []
        self.current_tool: Optional[str] = None
        self.status: Optional[str] = None

    def start_message(self):
        """Start displaying a new message"""
        self.current_message = []
        self.current_tool = None
        self.live = Live(self._build_display(), console=self.console, refresh_per_second=10)
        self.live.start()

    def append_text(self, text: str):
        """Append text to current message"""
        self.current_message.append(text)
        if self.live:
            self.live.update(self._build_display())

    def set_tool(self, tool_name: str):
        """Set current tool being executed"""
        self.current_tool = tool_name
        if self.live:
            self.live.update(self._build_display())

    def clear_tool(self):
        """Clear tool display"""
        self.current_tool = None
        if self.live:
            self.live.update(self._build_display())

    def set_status(self, status: str):
        """Set status message"""
        self.status = status
        if self.live:
            self.live.update(self._build_display())

    def stop(self):
        """Stop live display"""
        if self.live:
            self.live.stop()
            self.live = None

    def _build_display(self):
        """Build the current display"""
        parts = []

        # Add status spinner if present
        if self.status:
            parts.append(Panel(
                Group(
                    Spinner("dots"),
                    Text(self.status, style="yellow")
                ),
                border_style="yellow"
            ))

        # Add tool execution indicator
        if self.current_tool:
            parts.append(Panel(
                f"🔧 Executing: {self.current_tool}",
                border_style="blue"
            ))

        # Add streaming message
        if self.current_message:
            message_text = "".join(self.current_message)
            # Render as markdown for better formatting
            parts.append(Markdown(message_text))

        return Group(*parts) if parts else Text("...")
```

### 3. Integrate Streaming Display

**Modify:** `penguin/cli/cli.py` - PenguinCLI event handlers

```python
from penguin.cli.streaming_display import StreamingDisplay

class PenguinCLI:
    def __init__(self, ...):
        # ... existing code
        self.streaming_display = StreamingDisplay()

    async def handle_assistant_message_stream(self):
        """Handle streaming assistant response"""
        self.streaming_display.start_message()

        try:
            async for event in core.stream_response():
                if event.type == "text":
                    self.streaming_display.append_text(event.data)

                elif event.type == "tool_call":
                    self.streaming_display.set_tool(event.tool_name)

                elif event.type == "tool_result":
                    self.streaming_display.clear_tool()

                elif event.type == "status":
                    self.streaming_display.set_status(event.message)

        finally:
            self.streaming_display.stop()
```

### 4. Test Streaming Display

```bash
# Start chat
penguin

# Send a message that requires multiple streaming chunks
# Observe smooth rendering without flickering
# Execute a tool - verify tool indicator appears
# Check for any UI glitches
```

**Update evaluation_python.md:**
- Is streaming smoother than before?
- Any flickering issues?
- User experience improvements?
- Performance impact?

---

## Phase 5: Code Organization (45-60 min)

### Goal: Decompose cli.py if needed

### 1. Analyze cli.py Structure

```bash
# Count lines
wc -l penguin/cli/cli.py

# Find class/function boundaries
grep -n "^class\|^def\|^async def" penguin/cli/cli.py
```

**Document:**
- How big is PenguinCLI class?
- What are its responsibilities?
- Can it be split without breaking functionality?

### 2. Extract Components (if worthwhile)

**Only if cli.py is hard to navigate, consider extracting:**

**Create:** `penguin/cli/interactive_session.py`

```python
"""Interactive chat session manager"""

class InteractiveSession:
    """Manages interactive chat loop"""

    def __init__(self, core: PenguinCore):
        self.core = core
        self.streaming_display = StreamingDisplay()

    async def chat_loop(self):
        """Main chat loop"""
        # Move chat loop logic here
        pass
```

**Create:** `penguin/cli/input_handler.py`

```python
"""Input handling with prompt_toolkit"""

from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings


class InputHandler:
    """Handle user input"""

    def __init__(self):
        self.session = self._create_session()

    def _create_session(self) -> PromptSession:
        kb = KeyBindings()

        @kb.add("c-j")  # Ctrl-J for newline
        def _(event):
            event.current_buffer.insert_text("\n")

        @kb.add("escape", "enter")  # Alt-Enter to submit
        def _(event):
            event.current_buffer.validate_and_handle()

        return PromptSession(
            multiline=True,
            key_bindings=kb,
            prompt_continuation="... "
        )

    async def get_input(self) -> str:
        return await self.session.prompt_async(">>> ")
```

### 3. Update cli.py (if extracted)

**Simplify:** `penguin/cli/cli.py`

```python
# After extraction
from penguin.cli.interactive_session import InteractiveSession
from penguin.cli.input_handler import InputHandler
from penguin.cli.streaming_display import StreamingDisplay

# Smaller, cleaner PenguinCLI
```

**Update evaluation_python.md:**
- Lines reduced from cli.py?
- Is code more maintainable?
- Time spent refactoring vs benefit?
- Should we even bother splitting? (Might not be worth it!)

---

## Phase 6: Testing & Benchmarking (30-45 min)

### 1. Test All Changes

```bash
# Basic chat
penguin
# Send messages
# Verify smooth streaming
# Test /checkpoint and /rollback commands
# Test /tokens and /truncations commands

# Performance test
time penguin --version
# Compare to baseline

# Memory test during streaming
# (Use memory_profiler or similar if available)
```

### 2. Compare Before/After

**Update evaluation_python.md:**

```markdown
## Before vs After

### Code Metrics
Before: cli.py 3,780+ lines
After:  cli.py X lines
        streaming_display.py X lines
        (Other new files)
Total:  X lines (Y% change)

### CLI Features Added
- ✅ Checkpoint UI (/checkpoint, /rollback, /branch, /checkpoints)
- ✅ Context window display (/tokens, /truncations)
- ✅ Smooth streaming display (Rich.Live)

### Architecture
Before:
- Basic event rendering
- No checkpoint commands
- No context window visibility

After:
- Smooth streaming with Rich.Live
- Full checkpoint UI (integrates with CheckpointManager)
- Token usage visibility (integrates with ContextWindowManager)
- Better organized CLI code

### Performance
Before:
- Startup: ?ms
- Memory: ?MB
- Streaming: ?

After:
- Startup: Xms (+/- Y%)
- Memory: XMB (+/- Y%)
- Streaming: Smooth / Flickering?
```

### 3. Document Workflow

**Create example showing:**
- Chat with smooth streaming
- Checkpoint creation before risky operation
- Token usage monitoring
- Rollback if needed

---

## Phase 7: Evaluation & Documentation (20-30 min)

### 1. Complete evaluation_python.md

Fill in all sections:
- Final metrics
- Subjective assessments
- Key insights
- Comparison points for TypeScript track

### 2. Write Summary Notes

**Create:** `CLI_IMPROVEMENTS_SUMMARY.md`

```markdown
# Python CLI Improvements Summary

## Changes Made (CLI Layer Only)

### Checkpoint UI
- **Before:** CheckpointManager existed but no CLI commands
- **After:** Full checkpoint UI (/checkpoint, /rollback, /branch, /checkpoints)
- **Benefits:** Users can now use time-travel debugging from CLI

### Context Window Visibility
- **Before:** ContextWindowManager tracked everything internally
- **After:** User-visible commands (/tokens, /truncations) and automatic warnings
- **Benefits:** Users aware of context window usage and trimming

### Streaming Display
- **Before:** Basic text rendering
- **After:** Rich.Live smooth streaming with tool indicators
- **Benefits:** Better UX, less flickering

## Breaking Changes
- [Any breaking changes]

## Performance Impact
- Startup: [faster/slower by X%]
- Memory: [more/less by X%]
- Streaming: [smoother/same]
```

### 3. Commit Changes

```bash
git add .
git commit -m "CLI: Improve Python CLI presentation layer

- Add checkpoint UI commands (integrate with CheckpointManager)
- Add context window visibility (/tokens, /truncations)
- Improve streaming display with Rich.Live
- Better code organization
- Kimi-inspired rendering improvements"
```

---

## Deliverables Checklist

At the end, you should have:

- [ ] Checkpoint UI commands functional (/checkpoint, /rollback, /branch, /checkpoints)
- [ ] Context window display commands (/tokens, /truncations)
- [ ] Smooth streaming display (Rich.Live integration)
- [ ] Code organization improved (if worthwhile)
- [ ] evaluation_python.md completed with:
  - [ ] Before/after CLI metrics
  - [ ] Performance benchmarks (rendering focus)
  - [ ] Kimi rendering patterns assessment
  - [ ] Comparison points ready for TypeScript track
- [ ] Tests passing
- [ ] Documentation updated
- [ ] Clean git history

---

## Troubleshooting Guide

### Issue: Checkpoint commands not working
**Solution:**
- Verify ConversationManager.checkpoint_manager is not None
- Check CheckpointConfig is enabled
- Verify checkpoint directory exists and is writable
- CheckpointManager is already implemented - just integrate with CLI!

### Issue: Token stats showing zeros
**Solution:**
- Verify ContextWindowManager is initialized
- Check if session has messages
- Verify token counter is working
- ContextWindowManager already exists - just display the data!

### Issue: Streaming display flickering
**Solution:**
- Reduce Rich.Live refresh_per_second
- Check if multiple Live instances running simultaneously
- Verify Rich version is recent

### Issue: Performance degraded
**Solution:**
- Profile rendering code
- Check Rich.Live update frequency
- Verify token calculations not running in tight loop

---

## Notes for Autonomous Execution

**If you're a Claude instance executing this plan:**

1. **CRITICAL: CLI is ~10% of codebase** - Focus on presentation, not system features
2. **Don't reimplement system features** - CheckpointManager, ContextWindowManager, SessionManager already exist!
3. **Create evaluation_python.md FIRST** and update as you go
4. **Test incrementally** - Don't refactor everything then test
5. **Document current state** before changing anything
6. **Commit frequently** - Atomic commits per feature
7. **Compare to Kimi CLI rendering** - Reference analysis doc for UI patterns
8. **Be honest about challenges** - Document what was hard

**Success = Working CLI improvements + Honest evaluation**

Not: Reimplemented system features + Perfect architecture

---

## Kimi CLI Patterns Reference (CLI-Specific)

Quick reference from analysis - **ONLY THE CLI/RENDERING PARTS:**

1. **Rich.Live Streaming** - Smooth updates without flickering
2. **Clear Event Display** - Tool indicators, status updates, progress
3. **User Commands** - /checkpoint, /tokens, etc. expose system features
4. **Context Awareness** - Show users what's happening (token usage, truncation)
5. **Clean Output** - Markdown rendering, syntax highlighting
6. **Minimal UI Noise** - Only show what matters

**NOT applicable (these are system features):**
- ❌ JSONL history (SessionManager handles this)
- ❌ Wire protocol (event system exists)
- ❌ Checkpoint implementation (CheckpointManager exists)
- ❌ Context trimming (ContextWindowManager exists)
- ❌ Tool approval policy (system feature, not CLI)

---

## Final Notes

This is a **CLI improvement experiment** comparing Python (Kimi rendering patterns) vs TypeScript (Gemini patterns).

**Remember: CLI is ~10% of Penguin!**

Focus on:
✅ Better rendering (smooth streaming)
✅ Exposing existing system features (checkpoints, token stats)
✅ Improving user experience
✅ Honest evaluation

Don't waste time on:
❌ Reimplementing system features that already exist
❌ Perfect architecture
❌ Complete feature parity with Kimi-CLI
❌ Every single pattern

**Time budget: 3-4 hours max**

If something takes >30 min with no progress, document as challenge and move on.

Good luck! 🐧🐍
