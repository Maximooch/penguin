# Engine

The `Engine` is a high-level coordination layer introduced to manage the core reasoning and action loops within Penguin. It acts as the primary orchestrator when available, handling interactions between the `APIClient`, `ToolManager`, `ActionExecutor`, and `ConversationManager`.

## Purpose

-   **Centralized Loop Management:** Provides dedicated methods (`run_single_turn`, `run_task`) for handling both single interaction cycles and multi-step autonomous tasks.
-   **Decoupling:** Separates the core reasoning loop logic from `PenguinCore`, making the system more modular and testable.
-   **State Management:** Maintains light run-time state related to the execution loop (e.g., start time, iteration count).
-   **Extensibility:** Supports pluggable `StopCondition`s to control the termination of autonomous tasks based on various criteria (e.g., token budget, wall clock time).
-   **Streaming Support:** Offers methods (`stream`) for handling streaming responses from the LLM provider.

## Initialization

The `Engine` is typically initialized within `PenguinCore.create` and requires several key components:

-   `EngineSettings`: Configuration object defining default behaviors (retries, timeouts, etc.).
-   `ConversationManager`: For accessing and managing conversation history.
-   `APIClient`: For making calls to the language model.
-   `ToolManager`: For accessing available tools.
-   `ActionExecutor`: For executing parsed actions.
-   `stop_conditions` (Optional): A sequence of `StopCondition` objects.

If the `Engine` fails to initialize, `PenguinCore` falls back to its legacy internal processing logic.

## Key Methods

-   `async run_single_turn(prompt: str, *, tools_enabled: bool = True, streaming: Optional[bool] = None)`: Executes a single cycle: user prompt -> LLM reasoning -> optional tool execution -> response. Returns a dictionary containing the assistant's response and any action results.
-   `async run_task(task_prompt: str, max_iterations: Optional[int] = None) -> str`: Runs a multi-step reasoning/action loop. It starts with the `task_prompt` and continues iteratively until a `StopCondition` is met, the maximum iterations are reached, or a task completion phrase is detected. Returns the final assistant response.
-   `async stream(prompt: str)`: Initiates a streaming response for the given prompt, yielding chunks as they arrive.

## Stop Conditions

The `run_task` loop can be controlled by `StopCondition` objects passed during initialization or added later. Built-in conditions include:

-   `TokenBudgetStop`: Stops if the conversation context exceeds a token limit.
-   `WallClockStop`: Stops if the task runs longer than a specified duration.
-   `ExternalCallbackStop`: Stops based on the result of a custom asynchronous callback function.

## Integration with Core and RunMode

-   **PenguinCore:** When the `Engine` is initialized successfully, `PenguinCore.process` and `PenguinCore.multi_step_process` delegate their core logic to `Engine.run_single_turn` and `Engine.run_task`, respectively.
-   **RunMode:** The `RunMode._execute_task` method also utilizes `Engine.run_task` to perform autonomous task execution when the `Engine` is available, falling back to its internal loop otherwise. 