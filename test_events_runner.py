#!/usr/bin/env python
"""
Simple script to test the event system.
Run with: python test_events_runner.py
"""

import asyncio
import logging
import sys
import traceback

# Configure logging first
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]  # Force output to stdout
)
logger = logging.getLogger(__name__)

# Try/except block for imports
try:
    # Try both import paths to handle different run locations
    try:
        from penguin.utils.events import EventBus, EventPriority, TaskEvent
        from penguin.system.state import TaskState
        logger.info("Imported from penguin.* package paths")
    except ImportError:
        from penguin.penguin.utils.events import EventBus, EventPriority, TaskEvent
        from penguin.penguin.system.state import TaskState
        logger.info("Imported from penguin.penguin.* package paths")
        
    logger.info("Successfully imported EventBus and TaskState")
except ImportError as e:
    logger.error(f"Import error: {e}")
    logger.error("Make sure you're running this script from the correct directory")
    logger.error("Try: cd penguin && python test_events_runner.py")
    sys.exit(1)

# Example event handler
async def task_started_handler(data):
    print(f"[HANDLER] Task started: {data}")  # Direct print in case logging isn't working
    logger.info(f"Task started: {data}")

async def task_progress_handler(data):
    print(f"[HANDLER] Task progress: {data.get('progress', 0)}%")  # Direct print
    logger.info(f"Task progress: {data.get('progress', 0)}%")

async def task_completed_handler(data):
    print(f"[HANDLER] Task completed: {data}")  # Direct print
    logger.info(f"Task completed: {data}")

async def main():
    """Run a simple test of the event system."""
    try:
        logger.info("Starting event system test")
        
        # Get the event bus
        event_bus = EventBus.get_instance()
        logger.info("Got EventBus instance")
        event_bus.clear_all_handlers()
        
        # Subscribe to events
        event_bus.subscribe(TaskEvent.STARTED.value, task_started_handler)
        event_bus.subscribe(TaskEvent.PROGRESSED.value, task_progress_handler)
        event_bus.subscribe(TaskEvent.COMPLETED.value, task_completed_handler)
        logger.info("Subscribed to events")
        
        # Create a sample task
        task_id = "test-123"
        logger.info(f"Testing transitions for task {task_id}")
        
        # Publish a series of events
        logger.info("Publishing STARTED event")
        await event_bus.publish(TaskEvent.STARTED.value, {
            "task_id": task_id, 
            "task_prompt": "Test task",
            "max_iterations": 5
        })
        
        # Simulate task progress
        for i in range(1, 6):
            logger.info(f"Publishing PROGRESSED event {i}/5")
            await event_bus.publish(TaskEvent.PROGRESSED.value, {
                "task_id": task_id,
                "iteration": i,
                "max_iterations": 5,
                "progress": i * 20
            })
            await asyncio.sleep(0.5)  # Small delay for demonstration
        
        # Complete the task
        logger.info("Publishing COMPLETED event")
        await event_bus.publish(TaskEvent.COMPLETED.value, {
            "task_id": task_id,
            "iteration": 5,
            "max_iterations": 5
        })
        
        # Test state transitions
        logger.info("\nTesting TaskState transitions:")
        
        # Valid transitions
        current_state = TaskState.PENDING
        next_state = TaskState.ACTIVE
        valid = next_state in TaskState.get_valid_transitions(current_state)
        logger.info(f"{current_state.value} -> {next_state.value}: {'Valid' if valid else 'Invalid'}")
        
        # Invalid transition
        current_state = TaskState.PENDING
        next_state = TaskState.COMPLETED
        valid = next_state in TaskState.get_valid_transitions(current_state)
        logger.info(f"{current_state.value} -> {next_state.value}: {'Valid' if valid else 'Invalid'}")
        
        # Check if handlers are registered properly
        started_count = event_bus.get_subscriber_count(TaskEvent.STARTED.value)
        progressed_count = event_bus.get_subscriber_count(TaskEvent.PROGRESSED.value)
        completed_count = event_bus.get_subscriber_count(TaskEvent.COMPLETED.value)
        
        print(f"Subscriber counts: STARTED={started_count}, PROGRESSED={progressed_count}, COMPLETED={completed_count}")
        logger.info(f"Subscriber counts: STARTED={started_count}, PROGRESSED={progressed_count}, COMPLETED={completed_count}")
        
        if started_count == 0 or progressed_count == 0 or completed_count == 0:
            print("WARNING: Some event types have no subscribers!")
            logger.warning("Some event types have no subscribers!")

        logger.info("Event system test completed successfully")
    except Exception as e:
        logger.error(f"Error in main function: {e}")
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    print("Starting test_events_runner.py")
    try:
        asyncio.run(main())
        print("Test completed successfully")
    except Exception as e:
        print(f"Error running main: {e}")
        traceback.print_exc() 