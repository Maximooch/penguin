"""
Example demonstrating the integration of TaskState and EventBus in Penguin.

This file shows how the new event-driven approach would work for task management
rather than the string-based completion detection currently used.
"""

import asyncio
import logging
from typing import Dict, Any, Optional

# Import our new components
from penguin.penguin.system.state import TaskState
from penguin.penguin.utils.events import EventBus, EventPriority, TaskEvent

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TaskData:
    """Data structure representing a task."""
    
    def __init__(self, task_id: str, title: str, description: str, **kwargs):
        self.id = task_id
        self.title = title
        self.description = description
        self.state = TaskState.PENDING
        self.progress = 0
        self.metadata = kwargs
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')
        self.project_id = kwargs.get('project_id')
        self.priority = kwargs.get('priority', 1)
    
    def transition_to(self, new_state: TaskState) -> bool:
        """
        Transition the task to a new state with validation.
        
        Returns:
            bool: Whether the transition was successful
        """
        valid_transitions = TaskState.get_valid_transitions(self.state)
        
        if new_state in valid_transitions:
            old_state = self.state
            self.state = new_state
            logger.info(f"Task {self.id} transitioned from {old_state.value} to {new_state.value}")
            return True
        
        logger.warning(f"Invalid state transition for task {self.id}: {self.state.value} -> {new_state.value}")
        return False


class TaskManager:
    """Example task manager using EventBus for state changes."""
    
    def __init__(self):
        self.tasks: Dict[str, TaskData] = {}
        self.event_bus = EventBus.get_instance()
        
        # Register event handlers
        self._setup_event_handlers()
    
    def _setup_event_handlers(self):
        """Set up handlers for task-related events."""
        # High priority handlers for state transitions
        self.event_bus.subscribe(
            TaskEvent.STARTED.value,
            self._handle_task_started,
            EventPriority.HIGH
        )
        self.event_bus.subscribe(
            TaskEvent.COMPLETED.value,
            self._handle_task_completed,
            EventPriority.HIGH
        )
        self.event_bus.subscribe(
            TaskEvent.FAILED.value,
            self._handle_task_failed,
            EventPriority.HIGH
        )
        self.event_bus.subscribe(
            TaskEvent.PAUSED.value,
            self._handle_task_paused,
            EventPriority.HIGH
        )
        self.event_bus.subscribe(
            TaskEvent.RESUMED.value,
            self._handle_task_resumed,
            EventPriority.HIGH
        )
        
        # Normal priority handlers for other task events
        self.event_bus.subscribe(
            TaskEvent.PROGRESSED.value,
            self._handle_task_progress,
            EventPriority.NORMAL
        )
        self.event_bus.subscribe(
            TaskEvent.CREATED.value,
            self._handle_task_created,
            EventPriority.NORMAL
        )
    
    def _handle_task_started(self, data: Dict[str, Any]):
        """Handle task started event."""
        task_id = data.get('task_id')
        if task_id in self.tasks:
            self.tasks[task_id].transition_to(TaskState.ACTIVE)
    
    def _handle_task_completed(self, data: Dict[str, Any]):
        """Handle task completed event."""
        task_id = data.get('task_id')
        if task_id in self.tasks:
            self.tasks[task_id].transition_to(TaskState.COMPLETED)
            # Perform any other completion actions
            logger.info(f"Task {task_id} completed successfully")
    
    def _handle_task_failed(self, data: Dict[str, Any]):
        """Handle task failed event."""
        task_id = data.get('task_id')
        error = data.get('error', 'Unknown error')
        if task_id in self.tasks:
            self.tasks[task_id].transition_to(TaskState.FAILED)
            self.tasks[task_id].metadata['error'] = error
            logger.error(f"Task {task_id} failed: {error}")
    
    def _handle_task_paused(self, data: Dict[str, Any]):
        """Handle task paused event."""
        task_id = data.get('task_id')
        if task_id in self.tasks:
            self.tasks[task_id].transition_to(TaskState.PAUSED)
    
    def _handle_task_resumed(self, data: Dict[str, Any]):
        """Handle task resumed event."""
        task_id = data.get('task_id')
        if task_id in self.tasks:
            self.tasks[task_id].transition_to(TaskState.ACTIVE)
    
    def _handle_task_progress(self, data: Dict[str, Any]):
        """Handle task progress event."""
        task_id = data.get('task_id')
        progress = data.get('progress', 0)
        if task_id in self.tasks:
            self.tasks[task_id].progress = progress
            logger.info(f"Task {task_id} progress: {progress}%")
    
    def _handle_task_created(self, data: Dict[str, Any]):
        """Handle task created event."""
        task_id = data.get('task_id')
        task = TaskData(
            task_id=task_id,
            title=data.get('title', 'Untitled Task'),
            description=data.get('description', ''),
            **data.get('metadata', {})
        )
        self.tasks[task_id] = task
        logger.info(f"Task {task_id} created: {task.title}")
    
    async def create_task(self, title: str, description: str, **kwargs) -> str:
        """Create a new task and publish event."""
        task_id = f"task_{len(self.tasks) + 1}"
        
        # Publish event instead of directly manipulating state
        await self.event_bus.publish(
            TaskEvent.CREATED.value,
            {
                'task_id': task_id,
                'title': title,
                'description': description,
                'metadata': kwargs
            }
        )
        return task_id
    
    async def start_task(self, task_id: str) -> bool:
        """Start a task execution."""
        if task_id not in self.tasks:
            logger.error(f"Cannot start unknown task: {task_id}")
            return False
            
        await self.event_bus.publish(
            TaskEvent.STARTED.value,
            {'task_id': task_id}
        )
        return True
    
    async def complete_task(self, task_id: str) -> bool:
        """Mark a task as completed."""
        if task_id not in self.tasks:
            logger.error(f"Cannot complete unknown task: {task_id}")
            return False
            
        await self.event_bus.publish(
            TaskEvent.COMPLETED.value,
            {'task_id': task_id}
        )
        return True
    
    async def fail_task(self, task_id: str, error: str) -> bool:
        """Mark a task as failed."""
        if task_id not in self.tasks:
            logger.error(f"Cannot fail unknown task: {task_id}")
            return False
            
        await self.event_bus.publish(
            TaskEvent.FAILED.value,
            {'task_id': task_id, 'error': error}
        )
        return True
    
    async def update_progress(self, task_id: str, progress: int) -> bool:
        """Update task progress."""
        if task_id not in self.tasks:
            logger.error(f"Cannot update progress for unknown task: {task_id}")
            return False
            
        await self.event_bus.publish(
            TaskEvent.PROGRESSED.value,
            {'task_id': task_id, 'progress': progress}
        )
        return True
    
    def get_task(self, task_id: str) -> Optional[TaskData]:
        """Get task data by ID."""
        return self.tasks.get(task_id)


# Example RunMode integration with event-based task execution
class EnhancedRunMode:
    """Example of how RunMode would use the event-based system."""
    
    def __init__(self, task_manager: TaskManager):
        self.task_manager = task_manager
        self.event_bus = EventBus.get_instance()
        self.current_task_id = None
        
        # Register for events we care about
        self._setup_event_handlers()
    
    def _setup_event_handlers(self):
        """Set up event handlers for RunMode."""
        # Subscribe to completion events to update UI
        self.event_bus.subscribe(
            TaskEvent.COMPLETED.value,
            self._on_task_completed
        )
        self.event_bus.subscribe(
            TaskEvent.FAILED.value,
            self._on_task_failed
        )
        self.event_bus.subscribe(
            TaskEvent.PROGRESSED.value,
            self._on_task_progress
        )
        self.event_bus.subscribe(
            TaskEvent.NEEDS_INPUT.value,
            self._on_task_needs_input
        )
    
    def _on_task_completed(self, data: Dict[str, Any]):
        """Handle task completion by updating UI."""
        task_id = data.get('task_id')
        if task_id == self.current_task_id:
            task = self.task_manager.get_task(task_id)
            if task:
                # Instead of checking for a TASK_COMPLETED string
                # we're responding to an event
                logger.info(f"✅ Task completed: {task.title}")
                self.current_task_id = None
    
    def _on_task_failed(self, data: Dict[str, Any]):
        """Handle task failure by updating UI."""
        task_id = data.get('task_id')
        error = data.get('error', 'Unknown error')
        if task_id == self.current_task_id:
            task = self.task_manager.get_task(task_id)
            if task:
                logger.error(f"❌ Task failed: {task.title} - {error}")
                self.current_task_id = None
    
    def _on_task_progress(self, data: Dict[str, Any]):
        """Handle task progress by updating UI."""
        task_id = data.get('task_id')
        progress = data.get('progress', 0)
        if task_id == self.current_task_id:
            task = self.task_manager.get_task(task_id)
            if task:
                # Update progress display
                logger.info(f"Task progress: {progress}% - {task.title}")
    
    def _on_task_needs_input(self, data: Dict[str, Any]):
        """Handle when a task needs user input."""
        task_id = data.get('task_id')
        prompt = data.get('prompt', 'Input needed')
        if task_id == self.current_task_id:
            # Instead of checking for a NEEDS_USER_INPUT string
            # we respond to an event
            logger.info(f"❓ Task needs input: {prompt}")
            # Here we would prompt the user and then resume the task
    
    async def execute_task(self, task_id: str) -> Dict[str, Any]:
        """Execute a task."""
        task = self.task_manager.get_task(task_id)
        if not task:
            return {"status": "error", "message": f"Task not found: {task_id}"}
        
        # Set as current task
        self.current_task_id = task_id
        
        # Start the task
        await self.task_manager.start_task(task_id)
        
        # Here, instead of running our own execution loop, we would
        # call engine.run_task which would emit events as it progresses
        
        # For this example, we'll simulate engine execution
        await self._simulate_engine_execution(task_id)
        
        # Wait for task to complete or fail
        # In a real implementation, the event handlers would signal completion
        while self.current_task_id == task_id:
            await asyncio.sleep(0.1)
        
        # Return result based on final task state
        task = self.task_manager.get_task(task_id)
        if task.state == TaskState.COMPLETED:
            return {"status": "completed", "message": f"Task '{task.title}' completed successfully"}
        elif task.state == TaskState.FAILED:
            return {"status": "error", "message": f"Task failed: {task.metadata.get('error', 'Unknown error')}"}
        else:
            return {"status": "interrupted", "message": "Task execution was interrupted"}
    
    async def _simulate_engine_execution(self, task_id: str):
        """Simulate engine execution for the example."""
        # This simulates what engine.run_task would do
        task = self.task_manager.get_task(task_id)
        
        # Simulate progress
        for progress in range(0, 101, 20):
            if self.current_task_id != task_id:
                break  # Execution interrupted
                
            await self.task_manager.update_progress(task_id, progress)
            await asyncio.sleep(0.5)  # Simulate work
        
        # Complete the task (assuming success)
        if self.current_task_id == task_id:
            await self.task_manager.complete_task(task_id)


# Example Engine enhancement with EventBus integration
class EnhancedEngine:
    """Example of how Engine would use the event-based system."""
    
    def __init__(self, task_manager: TaskManager):
        self.task_manager = task_manager
        self.event_bus = EventBus.get_instance()
    
    async def run_task(self, task_id: str, max_iterations: int = 10) -> Dict[str, Any]:
        """
        Enhanced run_task that uses event system instead of string detection.
        
        This replaces the current engine.run_task that checks for 
        TASK_COMPLETION_PHRASE in the response.
        """
        task = self.task_manager.get_task(task_id)
        if not task:
            return {"status": "error", "message": f"Task not found: {task_id}"}
        
        # Start the task
        await self.task_manager.start_task(task_id)
        
        # Perform task execution
        result = await self._execute_task_loop(task_id, max_iterations)

        # Let's keep string detection for now, or maybe it could be an action tag
        
        # Return result data
        return result
    
    async def _execute_task_loop(self, task_id: str, max_iterations: int) -> Dict[str, Any]:
        """Main task execution loop."""
        iteration = 0
        last_response = ""
        
        while iteration < max_iterations:
            iteration += 1
            
            # So I think tracking progress should be relative to the phases/sub-phases given in a scratchpad. 
            # Doing it by iteration is not a good idea because there isn't always an easy linear progression, especially by iteration count.

            # Update progress (0-100 based on iteration/max)
            progress = int(100 * iteration / max_iterations)
            await self.task_manager.update_progress(task_id, progress)
            
            # Get LLM response (simulated here)
            response = await self._get_llm_response(task_id, iteration, max_iterations)
            last_response = response
            
            # Check if task needs human input
            if "I need more information" in response:
                # Instead of checking for NEED_USER_CLARIFICATION_PHRASE, emit an event
                await self.event_bus.publish(
                    TaskEvent.NEEDS_INPUT.value,
                    {'task_id': task_id, 'prompt': response}
                )
                # In a real implementation, we would pause here and wait for input
                # For this example, we'll just continue
            
            # Execute any actions in the response
            actions_executed = await self._execute_actions(task_id, response)
            
            # Check for completion conditions
            # Instead of checking for TASK_COMPLETION_PHRASE, use task state
            task = self.task_manager.get_task(task_id)
            
            # API or engine might have detected completion
            if task.state == TaskState.COMPLETED:
                break
                
            # If no actions and we've made progress, consider it done
            if not actions_executed and iteration >= 2:
                await self.task_manager.complete_task(task_id)
                break
        
        # If we hit max iterations without completion, complete the task anyway
        if iteration >= max_iterations:
            await self.task_manager.complete_task(task_id)
        
        # Return the final result
        return {
            "status": "completed",
            "message": f"Task execution completed after {iteration} iterations",
            "last_response": last_response
        }
    
    async def _get_llm_response(self, task_id: str, iteration: int, max_iterations: int) -> str:
        """Simulate getting a response from the LLM."""
        # This would call api_client.get_response in a real implementation
        task = self.task_manager.get_task(task_id)
        
        # Simulate different responses based on iteration
        if iteration == 1:
            return f"I'll start working on task '{task.title}'. First, I need to analyze what needs to be done."
        elif iteration == 2:
            return "I'm making progress on the task. Let me execute an action to help solve this."
        elif iteration == max_iterations - 1:
            return "I've almost completed the task. Just one last step."
        else:
            # Last iteration - simulate task completion
            return "I've completed the task successfully. TASK_COMPLETED"
    
    async def _execute_actions(self, task_id: str, response: str) -> bool:
        """Execute any actions in the response."""
        # Simulate action execution
        # In a real implementation, this would use ActionExecutor
        return "execute an action" in response.lower()


# Example usage
async def main():
    """Run an example of the event-based task system."""
    # Create the TaskManager
    task_manager = TaskManager()
    
    # Create the enhanced RunMode and Engine
    run_mode = EnhancedRunMode(task_manager)
    engine = EnhancedEngine(task_manager)
    
    logger.info("Creating a task...")
    task_id = await task_manager.create_task(
        "Example Task",
        "This is an example task to demonstrate the event system."
    )
    
    logger.info("Executing the task through RunMode...")
    result = await run_mode.execute_task(task_id)
    
    logger.info(f"Task execution result: {result}")
    
    # Create and execute another task using the Engine directly
    logger.info("\nCreating a second task for Engine execution...")
    task_id2 = await task_manager.create_task(
        "Engine Task",
        "This task will be executed directly by the enhanced Engine."
    )
    
    logger.info("Executing the task through Engine...")
    result = await engine.run_task(task_id2, max_iterations=5)
    
    logger.info(f"Engine execution result: {result}")
    

if __name__ == "__main__":
    asyncio.run(main()) 