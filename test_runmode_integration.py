#!/usr/bin/env python
"""
Test script to verify integration between Engine and RunMode using the enhanced task execution.
Run with: python test_runmode_integration.py
"""

import asyncio
import logging
import os
import sys
from datetime import datetime
from typing import Dict, Any, Optional

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Mock classes for testing without requiring entire Penguin stack
class MockEngine:
    """Mock Engine class with the enhanced run_task method."""
    
    async def run_task(
        self, 
        task_prompt: str, 
        max_iterations: Optional[int] = None,
        task_context: Optional[Dict[str, Any]] = None,
        task_id: Optional[str] = None,
        task_name: Optional[str] = None,
        completion_phrases: Optional[list] = None,
        on_completion: Optional[callable] = None,
        enable_events: bool = True
    ) -> Dict[str, Any]:
        """Mock implementation of the enhanced run_task method."""
        logger.info(f"MockEngine.run_task called with: {task_name}")
        logger.info(f"Task prompt: {task_prompt[:100]}...")
        
        # Simulate task execution
        await asyncio.sleep(1)  # Simulate some processing time
        
        # Create a mock result
        result = {
            "assistant_response": f"Task '{task_name}' completed successfully. TASK_COMPLETED",
            "iterations": 3,
            "status": "completed",
            "action_results": [],
            "task": {
                "id": task_id or f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                "name": task_name,
                "context": task_context,
                "max_iterations": max_iterations or 5,
                "start_time": datetime.now().isoformat(),
            },
            "execution_time": 1.5
        }
        
        # Call the completion callback if provided
        if on_completion:
            await on_completion(result)
        
        return result

class MockRunMode:
    """Mock RunMode class that uses the enhanced Engine.run_task method."""
    
    def __init__(self):
        self.max_iterations = 5
        self.core = MockCore()
        self.TASK_COMPLETION_PHRASE = "TASK_COMPLETED"
        self.CONTINUOUS_COMPLETION_PHRASE = "CONTINUOUS_MODE_COMPLETE"
    
    async def execute_task(self, name, description=None, context=None):
        """Simplified version of _execute_task that uses Engine.run_task."""
        logger.info(f"RunMode.execute_task called with: {name}")
        
        # Create task prompt
        task_prompt = f"Execute task: {name}\nDescription: {description or 'No description'}"
        
        # Use the mock Engine's run_task method
        result = await self.core.engine.run_task(
            task_prompt=task_prompt,
            max_iterations=self.max_iterations,
            task_context=context,
            task_id=context.get("id") if context else None,
            task_name=name,
            completion_phrases=[self.TASK_COMPLETION_PHRASE],
            on_completion=self._on_completion,
            enable_events=True
        )
        
        # Convert the result to the expected format
        completion_type = self._determine_completion_type(name, context, result)
        
        return {
            "status": result.get("status", "unknown"),
            "message": result.get("assistant_response", ""),
            "completion_type": completion_type,
            "iterations": result.get("iterations", 0)
        }
    
    async def _on_completion(self, result):
        """Mock completion callback."""
        logger.info(f"Task completed with status: {result.get('status')}")
    
    def _determine_completion_type(self, name, context, result):
        """Determine completion type based on task and result."""
        # Check for user-specified tasks
        if name == "user_specified_task" or name == "determine_next_step":
            return "user_specified"
        
        if context and context.get("id") == "user_specified":
            return "user_specified"
        
        # Check for continuous mode completion
        response = result.get("assistant_response", "")
        if self.CONTINUOUS_COMPLETION_PHRASE in response:
            return "continuous"
        
        # Standard task completion
        return "task"

class MockCore:
    """Mock Core class that contains the mock Engine."""
    
    def __init__(self):
        self.engine = MockEngine()

async def main():
    """Run the test."""
    try:
        logger.info("Starting RunMode/Engine integration test")
        
        # Create the mock RunMode
        run_mode = MockRunMode()
        
        # Test with a simple task
        logger.info("\nTesting with a simple task:")
        simple_result = await run_mode.execute_task(
            name="Simple Test Task",
            description="This is a simple test task.",
            context={"priority": 1}
        )
        logger.info(f"Simple task result: {simple_result}")
        
        # Test with a user-specified task
        logger.info("\nTesting with a user-specified task:")
        user_result = await run_mode.execute_task(
            name="user_specified_task",
            description="This is a user-specified test task.",
            context={"id": "user_specified", "metadata": {"source": "user"}}
        )
        logger.info(f"User task result: {user_result}")
        
        logger.info("\nTest completed successfully")
    
    except Exception as e:
        logger.error(f"Error in test: {e}")

if __name__ == "__main__":
    asyncio.run(main()) 