# Engine

The `Engine` is the coordination layer for Penguin's reasoning and action loops. `PenguinCore` constructs and references it, but the Engine owns the loop-level behavior: model calls, tool/action execution, stop conditions, task execution, streaming callbacks, and MessageBus routing.

## Purpose

-   **Centralized Loop Management:** Provides dedicated methods (`run_single_turn`, `run_task`) for handling both single interaction cycles and multi-step autonomous tasks.
-   **Decoupling:** Separates the core reasoning loop logic from `PenguinCore`, making the system more modular and testable.
-   **State Management:** Maintains light run-time state related to the execution loop (e.g., start time, iteration count).
-   **Extensibility:** Supports pluggable `StopCondition`s to control the termination of autonomous tasks based on various criteria (e.g., token budget, wall clock time).
-   **Streaming Support:** Offers methods (`stream`) for handling streaming responses from the LLM provider.

## Initialization

The `Engine` is initialized during `PenguinCore` startup and requires several key components:

-   `EngineSettings`: Configuration object defining default behaviors (retries, timeouts, etc.).
-   `ConversationManager`: For accessing and managing conversation history.
-   `APIClient`: For making calls to the language model.
-   `ToolManager`: For accessing available tools.
-   `ActionExecutor`: For executing parsed actions.
-   `stop_conditions` (Optional): A sequence of `StopCondition` objects.

If Engine initialization fails, higher-level execution paths should fail clearly rather than hiding the problem behind a second loop implementation.

## Key Methods

- `async run_single_turn(prompt: str, *, tools_enabled: bool = True, streaming: Optional[bool] = None)`
  Executes a single cycle: user prompt → LLM reasoning → optional tool execution → response. Returns a dictionary containing the assistant's response and any action results.
- `async run_response(prompt: str, *, image_path: Optional[str] = None, max_iterations: Optional[int] = None, streaming: Optional[bool] = None, stream_callback: Optional[Callable[[str], None]] = None) -> Dict[str, Any]`
  Conversational helper that loops until the model stops taking actions. Useful for natural chat flows where each iteration is saved as a separate message.
- `async run_task(task_prompt: str, *, image_path: Optional[str] = None, max_iterations: Optional[int] = None, task_context: Optional[Dict[str, Any]] = None, task_id: Optional[str] = None, task_name: Optional[str] = None, completion_phrases: Optional[List[str]] = None, on_completion: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None, enable_events: bool = True, message_callback: Optional[Callable[[str, str], Awaitable[None]]] = None) -> Dict[str, Any]`
  Runs a multi-step reasoning/action loop with optional EventBus integration. The loop stops when a `StopCondition` triggers, `completion_phrases` are detected, or an explicitly configured maximum-iteration limit is reached. Omitting `max_iterations` does not add a Penguin-local limit.
- `async stream(prompt: str)`
  Initiates a streaming response for the given prompt, yielding chunks as they arrive.
- `async spawn_child(purpose: str = "child", inherit_tools: bool = False, shared_conversation: bool = False) -> Engine`
  Spawns a child engine (currently runs in-process) with optional tool and conversation sharing.

## Stop Conditions

The `run_task` loop can be controlled by `StopCondition` objects passed during initialization or added later. Built-in conditions include:

-   `TokenBudgetStop`: Stops if the conversation context exceeds a token limit.
-   `WallClockStop`: Stops if the task runs longer than a specified duration.
-   `ExternalCallbackStop`: Stops based on the result of a custom asynchronous callback function.

## Events and Callbacks

`run_task` publishes progress via an optional EventBus. Callbacks (`message_callback`, `on_completion`) allow real‑time streaming of tool output and custom handling of task completion.

## Integration with Core and RunMode

-   **PenguinCore:** `PenguinCore.process` is a compatibility entrypoint backed by `penguin.core_runtime.process_runtime`; execution delegates to Engine-backed runtime flows.
-   **RunMode:** `RunMode._execute_task` delegates autonomous task execution to `Engine.run_task` and returns explicit errors if Engine is unavailable.
