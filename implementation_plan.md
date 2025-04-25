# Penguin Event System Integration Plan

## Overview

This document outlines the step-by-step plan for integrating the new event-driven task management system into Penguin. We'll use a gradual integration approach to minimize disruption while introducing the new architecture.

## Phase 1: Core Components Integration (Already Done)

1. ✅ Add `TaskState` enum to `state.py`
2. ✅ Create `events.py` with `EventBus` and `TaskEvent` classes

## Phase 2: Engine Enhancement (First Implementation)

1. Update `engine.py` to support events alongside string detection:
   - Keep existing string-based completion detection
   - Add event publishing for key task states
   - Modify `run_task` to support both mechanisms

```python
# Example addition to engine.py
async def run_task(self, task_prompt: str, max_iterations: Optional[int] = None) -> str:
    # Existing code...
    
    # Publish task start event
    event_bus = EventBus.get_instance()
    await event_bus.publish(TaskEvent.START.value, {"task_prompt": task_prompt})
    
    # Continue with existing loop...
    while self.current_iteration < max_iters:
        # Existing code...
        
        # Publish progress event
        await event_bus.publish(TaskEvent.PROGRESS.value, {
            "iteration": self.current_iteration,
            "max_iterations": max_iters,
            "progress": min(100, int(100 * self.current_iteration / max_iters))
        })
        
        # Use both string detection and events
        if TASK_COMPLETION_PHRASE in last_response:
            # Publish completion event
            await event_bus.publish(TaskEvent.COMPLETE.value, {
                "task_prompt": task_prompt,
                "response": last_response
            })
            break
            
    # Return existing result
```

## Phase 3: RunMode Integration

1. Modify `run_mode.py` to subscribe to events:
   - Keep existing execution logic
   - Add event handlers for task states
   - Start using event information for UI updates

```python
# In RunMode.__init__
self.event_bus = EventBus.get_instance()
self._setup_event_handlers()

def _setup_event_handlers(self):
    """Set up event handlers for task state changes."""
    self.event_bus.subscribe(TaskEvent.COMPLETE.value, self._on_task_completed)
    self.event_bus.subscribe(TaskEvent.PROGRESS.value, self._on_task_progress)
    self.event_bus.subscribe(TaskEvent.NEED_INPUT.value, self._on_task_needs_input)

def _on_task_completed(self, data):
    """Handle task completion event."""
    # Update UI or other state as needed
    self._display_message("Task completed based on event")
```

## Phase 4: TaskManager Enhancement

1. Integrate TaskManager with ProjectManager:
   - Add events to existing project/task operations
   - Keep existing methods for backward compatibility
   - Route task state changes through the event system

```python
# In ProjectManager method
def complete_task(self, name: str) -> Dict[str, Any]:
    """Mark a task as completed."""
    try:
        task = self._find_task_by_name(name)
        if not task:
            return {"status": "error", "result": f"No task found with name: {name}"}
            
        # Update task state directly (existing logic)
        task.status = "completed"
        
        # Also publish event
        asyncio.create_task(EventBus.get_instance().publish(
            TaskEvent.COMPLETE.value,
            {"task_id": task.id, "task_name": name}
        ))
        
        self._save_data()
        return {"status": "completed", "result": f"Task '{name}' completed successfully"}
    except Exception as e:
        return {"status": "error", "result": str(e)}
```

## Phase 5: Testing and Refinement

1. Add tests for each new component:
   - Test TaskState transitions
   - Test EventBus functionality
   - Test integrated task execution with events

2. Validate backward compatibility:
   - Ensure existing string patterns still work
   - Verify no disruption to current functionality

## Phase 6: UI Improvements

1. Enhance user interfaces to leverage event-based updates:
   - Add real-time progress indicators
   - Implement task state visualization
   - Show phase-based progress when available

## Future Considerations

1. **Advanced Progress Tracking**:
   - Implement scratchpad/phase-based progress tracking
   - Add weighted progress based on subtask complexity

2. **Multi-Processing Support**:
   - Extend EventBus to support cross-process events
   - Implement shared event queue between parent/child engines

3. **Full Event Transition**:
   - Eventually remove string detection once events are proven reliable
   - Make all components fully event-driven

## Implementation Guidelines

1. **Backward Compatibility**:
   - Keep existing functionality working alongside new events
   - Use events as an enhancement, not replacement (initially)

2. **Test-Driven Development**:
   - Add tests for each new event-related feature
   - Verify both mechanisms work correctly

3. **Documentation**:
   - Update docs to explain the dual mechanisms
   - Document the transition plan for developers 