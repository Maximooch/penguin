# CLI Prototype Mock

A mock CLI interface for testing Penguin's CLI rendering without requiring LLM API calls.

## Overview

The CLI prototype (`cli_prototype_mock.py`) mimics the real Penguin CLI but replaces LLM interactions with pre-defined demo responses. This allows you to:

- Test CLI rendering and display logic
- Demonstrate CLI features without API costs
- Debug UI issues in isolation
- Develop and iterate on CLI improvements quickly

## Usage

### Running the Prototype

```bash
# Run as a module
python -m penguin.cli.cli_prototype_mock

# Or run directly
python penguin/cli/cli_prototype_mock.py

# With debug logging
python -m penguin.cli.cli_prototype_mock --debug
```

### Available Commands

#### Demo Commands (single letter)
- `d` - Demo assistant message with collapsible steps and code blocks
- `s` - Streaming response simulation with markdown
- `a` - Action request/result simulation
- `t` - Tool call/result simulation
- `e` - Error message simulation
- `g` - Response thread demo (final + expandable steps/tools)
- `k` - 4-message thread demo (reasoning, code, notes, final)

#### Slash Commands
- `/demo sample` - Collapsible reasoning demo
- `/help` - Show available commands
- `/tokens` - Display token usage stats
- `/exit` - Quit the prototype

#### Regular Input
Any other input will be echoed back with a simple mock response.

## Features

### Mock Components

1. **MockCore** - Simulates `PenguinCore` without LLM calls
   - Manages conversation state
   - Tracks token usage
   - Emits UI events

2. **MockConversationManager** - Simulates conversation management
   - Stores messages
   - Provides token usage data
   - Compatible with real `Message` objects

3. **Real CLIRenderer** - Uses the actual CLI renderer
   - Tests real rendering logic
   - Displays with Rich Live updates
   - Supports streaming, panels, markdown, code highlighting

### Event System

The prototype includes a mock EventBus that disables the real event system to avoid conflicts. This allows the CLI renderer to work without the full Penguin infrastructure.

## Development

### Adding New Demo Scenarios

To add a new demo command:

1. Add a new method in `PrototypeCLI`:
   ```python
   async def my_new_demo(self):
       """Description of the demo"""
       content = "Demo content here..."

       # Add to message history
       msg = MockMessage(
           role="assistant",
           content=content,
           category=MessageCategory.DIALOG
       )
       self.core.conversation_manager.conversation.session.messages.append(msg)

       # Emit UI event
       await self.core.emit_ui_event("message", {
           "role": "assistant",
           "content": content,
           "category": MessageCategory.DIALOG
       })

       # Update tokens
       self.core.update_token_usage(100)
       await self.core.emit_ui_event("token_update", self.core.get_token_usage())
   ```

2. Add a command handler in `handle_input()`:
   ```python
   elif cmd == "n":  # or "/my-command"
       await self.my_new_demo()
   ```

3. Update the help message and docstring

### Testing Specific Features

#### Markdown Rendering
Use the `s` (stream) or `d` (demo) commands to test markdown, code blocks, and tables.

#### Streaming
Use the `s` command to see real-time streaming with the Penguin cursor (🐧).

#### Collapsible Content
Use the `g`, `k`, or `/demo sample` commands to test `<details>` rendering.

#### Error Display
Use the `e` command to test error message styling.

#### Token Display
Use the `/tokens` command to verify token usage display logic.

## Comparison with TUI Prototype

The CLI prototype is simpler than the TUI prototype:

| Feature | TUI Prototype | CLI Prototype |
|---------|---------------|---------------|
| Framework | Textual (reactive) | Rich Live (simple) |
| Input | Key bindings | Text input prompts |
| Layout | Complex widgets | Scrolling panels |
| Interactivity | Mouse + keyboard | Keyboard only |
| Use Case | Full TUI development | CLI rendering tests |

## Files

- `cli_prototype_mock.py` - Main prototype implementation
- `cli.py` - Real CLI implementation (for reference)
- `ui.py` - CLI renderer (used by both)
- `tui_prototype_mock.py` - TUI prototype (alternative)

## Troubleshooting

### "Welcome to Penguin" repeating
This usually means the EventBus is causing multiple initializations. The prototype should automatically disable the EventBus. Check that `disable_event_bus()` is being called before creating the `CLIRenderer`.

### Unicode errors on Windows
The prototype uses UTF-8 characters. If you see encoding errors, ensure your terminal supports UTF-8 or run through a tool that does (like Windows Terminal).

### Import errors
Make sure you're running from the project root and the `penguin` package is in your Python path.

## See Also

- `tui_prototype_mock.py` - Full Textual-based TUI prototype
- `cli.py` - Real CLI implementation
- `ui.py` - Shared rendering logic
