# Penguin CLI Refactor Plan

## Current Issues

1. **Duplicate UI elements** - Multiple status panels appear during RunMode
2. **Message flow inconsistency** - Some messages bypass the main flow and appear directly
3. **Live display conflicts** - Multiple Live displays can cause rendering issues
4. **Streaming coordination issues** - Core, Interface, and CLIRenderer all try to manage streaming independently
5. **Unclear component responsibilities** - Overlap between Core, Interface, and CLIRenderer
6. **Limited CLI arguments** - Current CLI lacks non-interactive modes and advanced controls found in tools like Claude Code.

## Architectural Goals

1. **Single source of truth** - ConversationManager should be the only message store
2. **Unidirectional message flow** - All message paths should follow the same route
3. **Clear component responsibilities**:
   - Core: Backend processing, state management, and event emission
   - Interface: Thin adapter between Core and CLI, no state management
   - CLIRenderer: UI rendering only, subscribes to Core events
4. **Comprehensive CLI Interface**: Provide a rich set of command-line arguments for both interactive and non-interactive use, inspired by Claude Code.

## Desired CLI Features & Arguments (Inspired by Claude Code)

This section outlines new CLI arguments and behaviors to be implemented.

### Non-Interactive Mode:
*   `penguin --prompt "Your query here"` (or `penguin -p "Your query here"`)
    *   Runs a single query and prints the result to stdout then exits.
    *   Equivalent to Claude Code's `-p` / `--print` mode.
*   Input via stdin: `echo "Explain this code" | penguin -p`
    *   Content from stdin will be treated as part of the prompt or context.

### Output Formatting:
*   `penguin --prompt "..." --output-format [text|json|stream-json]`
    *   `text`: (Default) Plain text output.
    *   `json`: Structured JSON output including metadata (cost, duration, session_id, result text).
        *   Schema to be defined, similar to Claude Code's `result` message type.
    *   `stream-json`: Stream individual JSON messages as they arrive (for events, thoughts, final result).
        *   Schema to include message types like `user`, `assistant`, `tool_call`, `tool_result`, `system_init`, `result_final`.

### Session Management:
*   `penguin --continue` (or `penguin -c`)
    *   Continues the most recent interactive conversation.
*   `penguin --continue "Further instructions"`
    *   Continues the most recent conversation with a new prompt.
*   `penguin --resume SESSION_ID`
    *   Resumes a specific conversation by its session ID.
*   `penguin --resume SESSION_ID -p "Update the tests"`
    *   Resumes a specific conversation in non-interactive mode with a new prompt.

### System Prompt Customization:
*   `penguin -p "..." --custom-prompt "Custom instructions for this run."`
    *   Allows providing custom instructions that are appended to a designated user-modifiable section of the base `SYSTEM_PROMPT` or augment it for the current non-interactive execution. The exact augmentation strategy (e.g., append to a specific placeholder, structured merge) needs definition. Advanced users can directly modify `system_prompt.py` for more fundamental changes.
*   `penguin -p "..." --append-system-prompt "Additional behaviors for this run."`
    *   Appends instructions to the very end of the *entire* effective system prompt for the current non-interactive execution. This is for adding overriding behaviors or post-script instructions.

### RunMode & Project/Task Management (CLI Initiated):
*   `penguin run --task <task_name_or_id> [--description "New task description"] [--continuous] [--time-limit <minutes>] [--custom-prompt "Task-specific context to append"]`
    *   Runs a specified task. If the task doesn't exist and a description is provided, it could offer to create it.
    *   `--continuous`: Runs the task in a loop or until explicitly stopped or a defined completion condition is met (simpler than full server mode for now).
    *   `--time-limit`: Sets a maximum duration for the run.
    *   Note: Detailed project/task-specific configuration files (e.g., for default models, tools per task) are a future enhancement for the project management system.
*   `penguin run --project <project_name_or_id> [--continuous] [--time-limit <minutes>] [--custom-prompt "Project-specific context to append"]`
    *   Runs a specified project, potentially executing its defined sequence of tasks.
*   `penguin status [--task <task_name_or_id> | --project <project_name_or_id>]`
    *   Checks the status of ongoing or background Penguin tasks/projects.
*   `penguin stop [--task <task_name_or_id> | --project <project_name_or_id>]`
    *   Attempts to gracefully stop a running task or project.

### Context Management (CLI):
* `penguin context list`
    * Lists files currently configured for persistent context loading (from `penguin_workspace/context/context_config.yml`).
* `penguin context add <file_path_or_glob>`
    * Adds a file or glob pattern to `context_config.yml` for persistent loading.
* `penguin context remove <file_path_or_glob>`
    * Removes a file or glob pattern from `context_config.yml`.
* `penguin context load <file_path_or_glob>`
    * Loads a specific file or files matching a glob into the current session's context (one-time load, doesn't modify `context_config.yml`).

### Tool Control:
*   `penguin --allowed-tools "web_search,file_read"`
    *   Comma-separated list of tools that Penguin is allowed to use.
*   `penguin --disallowed-tools "execute_code"`
    *   Comma-separated list of tools that Penguin is explicitly forbidden from using.
*   **Multi-Agent Systems**: Explore CLI and core support for coordinating multiple Penguin agents or integrating with other specialized agents for complex task decomposition and execution. (Future Consideration, dependent on core multi-agent capabilities).
*   **Penguin Server Mode**: (Future Consideration) Implement a `penguin server --config <server_config.yml>` command to start Penguin in a robust, long-running daemon mode. This server could manage multiple continuous tasks/projects, operate on a schedule (e.g., "9-5 simulated work"), handle advanced logging, and potentially offer a remote management API. This is a more advanced version of the simple `--continuous` flag for `run` commands.

### General Options:
*   `penguin --verbose`
    *   Enable verbose logging for debugging.
*   `penguin --max-turns N`
    *   Limits the number of agentic turns in non-interactive/RunMode.
*   `penguin --model MODEL_ID` (Already partially supported via `typer.Option`)
    *   Specify the model to use (e.g., `anthropic/claude-3-5-sonnet-20240620`).
*   `penguin --workspace PATH` (Already partially supported)
    *   Specify the workspace directory.
*   `penguin --config`
    *   Opens the `config.yml` file in the default system text editor. Future enhancement: an interactive CLI-based configuration editor.

### Future Considerations (from Claude Code, may or may not apply directly):
*   MCP Configuration (`--mcp-config`, `--permission-prompt-tool`): For extending with external tools/servers. Penguin has its own tool system, but the concept of explicitly allowing/managing external tool sources is relevant.

## Message Flow Architecture

### Original Approach:
```
User/Engine Input → Core → ConversationManager → Interface → CLIRenderer
```

### Simplified Event-Based Approach:
```
┌────────────┐  Commands   ┌──────────┐  Core API   ┌──────────┐
│    CLI     │────────────▶│Interface │────────────▶│   Core   │
│ (UI Layer) │            │(Adapter) │            │(Engine)  │
└────────────┘            └──────────┘            └──────────┘
      ▲                                                  │
      │                                                  │
      └──────────────────────────────────────────────────┘
                          Events
```

In this design:
- Core emits events directly to registered UI components
- Interface becomes purely an adapter/translator, not a state manager
- CLIRenderer subscribes to Core events for UI updates
- All message types follow the same path

## Implementation Plan

### 1. Core Refactoring

- Make `PenguinCore` the central event emitter
- Add direct UI subscription capability to Core
- Ensure all RunMode messages are added to ConversationManager
- Implement proper finalization of streaming messages
- Add detection for empty responses and error handling

```python
# Example Core event emission implementation
class PenguinCore:
    def __init__(self):
        self.ui_subscribers = []
    
    def register_ui(self, ui_component):
        self.ui_subscribers.append(ui_component)
    
    def emit_ui_event(self, event_type, data):
        for ui in self.ui_subscribers:
            ui.handle_event(event_type, data)
```

### 2. Interface Refactoring

- Refocus Interface as a thin adapter layer
- Remove all state management from Interface
- Provide command translation between CLI and Core
- Eliminate UI-specific callbacks in Interface

### 3. CLIRenderer Refactoring

- Register directly with Core for events
- Implement `handle_event(event_type, data)` method
- Eliminate all state management from CLIRenderer
- Always render directly from ConversationManager via Core
- Use a single Live display context for all rendering

### 4. Command Handling with Typer

- Use Typer for all command structure and help text
- Implement a simple command registry for extensibility
- Each command maps to Core functionality via Interface
- **Update `main` entry point in `cli.py` to handle new global options like `--prompt`, `--output-format`, etc., before dispatching to subcommands or interactive mode.**

```python
# Example Typer command structure (conceptual)
# main_app = typer.Typer(add_completion=False) # Main app for global options

# @main_app.callback(invoke_without_command=True)
# def main_penguin_entry(
#     ctx: typer.Context,
#     prompt: Optional[str] = typer.Option(None, "-p", "--prompt", help="Run in non-interactive mode with a single prompt."),
#     output_format: Optional[str] = typer.Option("text", "--output-format", help="Output format (text, json, stream-json)"),
#     # ... other global options ...
# ):
#     if prompt:
#         # Handle non-interactive mode
#         run_non_interactive(prompt, output_format, ...)
#     elif ctx.invoked_subcommand is None:
#         # Default to interactive chat
#         run_interactive_chat(...)
#     # Else: a subcommand was invoked, Typer handles it

# chat_app = typer.Typer(name="chat", help="Manage conversations.")
# main_app.add_typer(chat_app)

# @chat_app.command("list")
# def list_chats():
#    ...
```

## Rich Library Guidelines

If continuing with Rich:

1. **Single Live Context Rule**: Use only one `Live` display per screen
2. **Controlled Refresh Rate**: Cap at 4-5 FPS (reduce from default 10)
3. **Avoid Nesting**: Don't put Live displays inside other Live contexts 
4. **Layout-Based Rendering**: Use Layout API instead of ad-hoc panels
5. **Limit screen=True**: Only use for the main interactive session

```python
# Example of proper Rich usage
with Live(layout, refresh_per_second=4, screen=True) as live:
    # Handle all UI updates through this single Live context
    def update_ui():
        live.update(layout)  # Update the entire layout at once
```

## Alternative UI Approaches

1. **Textual**: For more complex, interactive TUI with widgets
   - Pros: Rich widget library, event-driven, mouse support
   - Cons: May be overkill, potential Typer integration challenges

2. **prompt_toolkit**: For focused input handling and simple output
   - Pros: Great for REPL-style interfaces, integrates with asyncio
   - Cons: Less rich output formatting than Rich

3. **Plain terminal**: Minimal approach with print statements
   - Pros: Maximum simplicity and portability
   - Cons: Limited formatting options, manual cursor control

## Testing Strategy

1. Test each component independently
2. Test the integration between components
3. Implement specific tests for RunMode scenarios
4. Test streaming behavior extensively

## Migration Strategy

1. Update Core to implement the event emission capability
2. Create minimal Interface that merely translates between CLI and Core
3. Update CLIRenderer to subscribe directly to Core events
4. Integrate the changes into the Typer CLI commands

## Phase 1: Foundation, Event System & Initial Typer Integration

**Objectives:**

* **Event System**: Implement Core event emission system
* **Unified Message Path**: Implement the direct event subscription architecture
* **`Typer` Command Structure**: Complete the Typer command structure for all operations
* **Minimal Rich UI**: Simple but reliable Rich UI for core functionality
* **Basic RunMode Integration**: Ensure RunMode events follow proper flow

## Phase 2: Full UI Implementation & Command Refinement

**Objectives:**

* **Complete UI Implementation**: Finish UI components with proper event handling
* **Robust Error Handling**: Graceful recovery from all error conditions
* **Enhanced RunMode Integration**: Seamless RunMode status display and control
* **Command System Completion**: All commands implemented with Typer
* **Token Usage Display**: Real-time token usage stats with categorical breakdown

## Phase 3: Polish, Performance & Extensions

**Objectives:**

* **Performance Optimization**: Reduce UI rendering overhead
* **Keyboard Shortcuts**: Add keyboard shortcuts for common operations
* **Configuration Interface**: CLI interface for managing configuration
* **Theme Support**: User-customizable colors/styles
* **Model Management**: Enhanced model switching and validation
* **First-Time Setup**: Wizard for initial configuration

## Future Considerations

*   Plugin System: Allow third-party commands to be registered
*   Headless Mode: API-only mode for scripting and automation
*   Language Server: Protocol for IDE integration
*   Remote Control: API for remote control of Penguin instances
*   **UI Toolkit Migration**: If needed, replace Rich with alternative
*   **Learn from other AI Agents**: Continuously evaluate features and architectural patterns from other successful coding agents (e.g., OpenAI Codex, GitHub Copilot CLI) to inform Penguin's evolution. This includes CLI interaction models, agentic behavior configuration, and performance optimization techniques (potentially drawing inspiration from native components seen in tools like Codex).
*   **Advanced Agentic Behavior Configuration**: As Penguin's agentic capabilities grow, consider CLI flags to fine-tune its autonomous behavior (e.g., planning strategy, self-correction depth, confirmation requirements for risky actions).
*   **Multi-Agent Systems**: Explore CLI and core support for coordinating multiple Penguin agents or integrating with other specialized agents for complex task decomposition and execution.

## Development Practices

*   Incremental Changes: Commit small, testable changes frequently
*   Prototyping: Test UI approaches in isolation before integration
*   Code Reviews & Documentation: Maintain clear documentation
*   Focused Testing: Specifically test event flow and RunMode scenarios
*   **Robust CLI Development Workflow**: Adopt practices for CLI development such as those outlined by mature projects (e.g., automated testing, linting, and potentially pre-commit/pre-push hooks as seen in the Codex repository) to ensure CLI reliability and maintainability.

## Implementation Progress

### Successfully Tested Features:
- ✅ Non-interactive mode with `-p`/`--prompt` (tested with direct prompts)
- ✅ Continue last conversation with `-c`/`--continue` (works both with and without additional prompts)
- ✅ Continuous mode with `--247`/`--continuous` and `--description` (successfully activates RunMode)
- ✅ Interactive setup wizard with questionary (integrated and working)
- ✅ Configuration management commands (setup, edit, check)
- ✅ Lightweight config commands (no longer require full core initialization)

### Recently Fixed Issues:
- ✅ **Workspace Path Configuration**: Fixed hardcoded paths in config.py to respect config.yml settings
- ✅ **Context Window Options**: Updated to include 1M tokens, renamed from "context length" to "context window"
- ✅ **Config Command Performance**: Config commands now bypass core initialization for faster execution
- ✅ **Tool Permission Documentation**: Created roadmap document noting current limitations

### Pending Testing:
- ⬜ Session resumption with `--resume SESSION_ID`
- ⬜ Task execution with `--run TASK_NAME`
- ⬜ Tool control flags
- ⬜ Custom prompt flags
- ⬜ Context management commands

## Recent Improvements (January 2025)

### Context Window & Model Selection
1. **Enhanced Model Selection**: Updated setup wizard to include 1M token context windows
2. **Improved Terminology**: Changed "context length" to "context window" throughout the interface
3. **Better Defaults**: Set 32K tokens as the default instead of 16K for better project handling

### Configuration System Fixes
1. **Dynamic Workspace Paths**: Fixed hardcoded workspace paths in config.py to properly respect config.yml settings
2. **Lightweight Commands**: Config commands (`penguin config edit/setup/check`) now run without initializing the full core
3. **First-run Detection**: Improved setup completion tracking and config validation

### Documentation & Planning
1. **Roadmap Creation**: Added comprehensive penguin_roadmap.md with detailed feature planning
2. **Tool Permission System**: Documented current limitations and future implementation plans
3. **Technical Debt Tracking**: Identified and planned fixes for configuration system issues

## Takeaways from CLI Implementation

1. **Import Consistency**: Maintaining consistent naming for imports is critical (e.g., the `Console` vs `RichConsole` issue caused continuation mode failures).

2. **Async/Sync Boundaries**: Managing the transition between Typer's synchronous callback interface and Penguin's async core requires careful handling with proper wrappers around async code.

3. **Config Format Compatibility**: The diverse ways config data may be accessed (attribute access vs dictionary access) requires flexible handlers that can work with both styles.

4. **Event-Based Architecture**: The event-based architecture for UI updates has proven effective, allowing Core to directly notify UI components about state changes without relying on polling.

5. **Streaming Management**: Properly tracking and finalizing streaming content is complex but essential for a good user experience, especially when handling partial responses and error cases.

6. **Error Handling Strategy**: A multi-layered approach to error handling (with graceful fallbacks) enables the CLI to be resilient even when underlying components fail.

7. **Testing Priority**: Testing interactive features requires direct human validation, which should be prioritized for critical user flows (like conversation continuation).

## Next Steps

1. ✅ **Implement non-interactive mode (`-p`/`--prompt`) and output formatting (`--output-format`) as a priority.** (Output schema definition to follow documentation update by user).
2. ✅ **Integrate session management flags (`--continue`, `--resume`).**
3. ✅ **Add basic run mode flags (`--run`, `--247`/`--continuous`, `--time-limit`, `--description`) for task execution.**
4. ⬜ Add custom prompt flags (`--custom-prompt`, `--append-system-prompt`).
5. ⬜ Implement basic `penguin context` commands (`list`, `add`, `remove`, `load`).
6. ⬜ Implement tool control flags (`--allowed-tools`, `--disallowed-tools`).
7. ⬜ Complete the migration from old CLI to new Typer-based CLI.
8. ⬜ Add comprehensive tests for new CLI arguments, event flow, and UI rendering.
9. ⬜ Implement remaining configuration management features.
10. ⬜ Optimize rendering performance.
11. ⬜ Document the new CLI architecture and usage.
12. ✅ Extract and integrate setup wizard as described above.
13. ⬜ Implement `/model select` command with dropdown, including fallback paths.
14. ⬜ Update documentation (`README` & `docs/cli.md`) with new config & model management features.
15. ⬜ **Automatic Model Spec Fetching**: Enhance setup wizard to automatically fetch model capabilities (context windows, vision support, etc.) and skip manual context window selection.
16. ⬜ **Implement Tool Permission System**: Create the actual permission enforcement that the setup wizard currently only collects preferences for.
17. ⬜ **Provider-specific Setup Flows**: Create tailored setup experiences for different providers (OpenRouter, Anthropic, OpenAI, etc.).

### Setup Wizard & Model Dropdown Integration (2025-05-22)

The interactive Questionary-based setup wizard prototype has been **accepted** by Maximus.  It will be reused in three areas:

1. **First-run configuration**  (`penguin config --setup` or automatic on missing `config.yml`).
2. **`penguin config` command** – allow re-running the wizard at any time to update settings.
3. **`/model` command & related Typer flags** – reuse the model-list/autocomplete logic for in-session model changes.

#### Implementation checklist

| # | Task | Owner | Notes |
|---|------|-------|-------|
| 1 | Extract wizard code into `penguin/setup/wizard.py` with sync & async helpers | core | Move logic, retain STYLE/theme helper. |
| 2 | Add Typer sub-command `penguin config setup` that calls the wizard (auto-run on fresh install) | cli | Should call async wrapper via `asyncio.run`. |
| 3 | Add `penguin config edit` to open the YAML directly (reuse existing util) | cli | Use cross-platform open logic from wizard. |
| 4 | Merge `fetch_models_from_openrouter`, cache utils, and `prepare_model_choices` into `penguin/llm/model_utils.py` | llm | Ensure no CLI-level deps. |
| 5 | `/model list` → print table; `/model select` (or `/model set`) → invoke Questionary dropdown inside chat loop | interface | Pause prompt_toolkit session, run Questionary, resume. |
| 6 | Add non-interactive flags: `--model list`, `--model set <id>` for scripting | cli | falls back to plain text I/O. |
| 7 | Unit tests for wizard path, config save/load, dropdown selection paths | tests | Use `pexpect` or `prompt_toolkit` stubs. |

#### Dropdown menu considerations & mitigations

Potential issue | Mitigation
--------------- | ----------
`prompt_toolkit` re-entrancy – the CLI chat loop already owns a `PromptSession`; spawning another Questionary prompt can clash. | Before launching Questionary: `self.session.app.exit()` (or suspend redraw), then run Questionary synchronously; resume main loop afterwards. Alternatively, implement dropdown with native `prompt_toolkit.completion.FuzzyCompleter` to avoid dual sessions.
Large model list (>300) causes sluggish rendering & scroll lag. | 1) Fetch in background & cache; show spinner. 2) Group choices by provider and collapse into sub-menus. 3) Provide type-ahead fuzzy search (Questionary `match_middle=True`).
Remote fetch latency / offline mode. | Use cached list (`~/.config/penguin/models_cache.json`) first. If offline & cache missing, fall back to hard-coded defaults.
Non-TTY / output-redirected sessions. | Detect `isatty`; if false, skip dropdown and require `--model <id>` or plain text prompt.
Windows terminal compatibility (colors, special keys). | Keep STYLE palette minimal; rely on Questionary defaults which handle Windows via `prompt_toolkit`.
Dependency bloat / version skew between `questionary`, `prompt_toolkit`, and Rich. | Pin compatible versions in `pyproject.toml`; run CI matrix tests. Consider offering a pure `prompt_toolkit` fallback.

#### Updated Next Steps

Add to the **Next Steps** list:

12. Extract and integrate setup wizard as described above.
13. Implement `/model select` command with dropdown, including fallback paths.
14. Update documentation (`README` & `docs/cli.md`) with new config & model management features.
