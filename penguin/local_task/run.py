from typing import Dict, List, Optional, Any
import asyncio
from datetime import datetime
import logging
from enum import Enum

from config import (
    TASK_COMPLETION_PHRASE, 
    TASK_BLOCKED_PHRASE,
    TASK_ERROR_PHRASE,
    MAX_TASK_ITERATIONS
)
from utils.diagnostics import diagnostics

logger = logging.getLogger(__name__)

class RunState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"
    COMPLETED = "completed"
    BLOCKED = "blocked"

class RunSession:
    """Manages a single autonomous run session"""
    def __init__(self, task_name: str, core_instance):
        self.task_name = task_name
        self.core = core_instance
        self.state = RunState.IDLE
        self.start_time = None
        self.iteration = 0
        self.results = []
        self.error = None
        self.block_reason = None
        
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_name": self.task_name,
            "state": self.state.value,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "iteration": self.iteration,
            "error": str(self.error) if self.error else None,
            "block_reason": self.block_reason,
            "results_count": len(self.results)
        }

class RunManager:
    """Handles autonomous execution of tasks"""
    
    def __init__(self, core_instance):
        self.core = core_instance
        self.active_session = None
        self.max_iterations = MAX_TASK_ITERATIONS
        
    async def run_task(self, task_name: str) -> Dict[str, Any]:
        """Run a task autonomously until completion or failure"""
        task = self.core.project_manager.get_task_by_name(task_name)
        if not task:
            return {
                "status": RunState.ERROR.value,
                "error": f"Task not found: {task_name}"
            }
        
        self.active_session = RunSession(task_name, self.core)
        self.active_session.start_time = datetime.now()
        self.active_session.state = RunState.RUNNING
        
        try:
            # Add task context
            self.core.conversation.add_message("system", 
                f"Task: {task_name}\nDescription: {task.description}\nStatus: {task.status}")
            
            # Add initial execution message
            self.core.conversation.add_message("system",
                f"Execute task: {task_name}\n" +
                "1. Break down the task into concrete steps\n" +
                "2. Execute each step using available tools\n" +
                "3. Report progress after each step\n" +
                "4. Mark task as complete when finished")
            
            while (self.active_session.iteration < self.max_iterations and 
                   self.active_session.state == RunState.RUNNING):
                
                self.active_session.iteration += 1
                
                # Get next action
                response_data, continuation = await self.core.get_response(
                    current_iteration=self.active_session.iteration,
                    max_iterations=self.max_iterations,
                    autonomous_mode=True
                )
                
                # Store results
                if response_data:
                    self.active_session.results.append(response_data)
                
                # Check completion status
                if self._check_completion(response_data):
                    self.active_session.state = RunState.COMPLETED
                    break
                    
                # Check for blocking issues
                if self._check_blocked(response_data):
                    self.active_session.state = RunState.BLOCKED
                    self.active_session.block_reason = self._extract_block_reason(response_data)
                    break
                    
                # Check for errors
                if self._check_error(response_data):
                    self.active_session.state = RunState.ERROR
                    self.active_session.error = self._extract_error_message(response_data)
                    break
                    
                # Break if continuation is False
                if not continuation:
                    break
                    
            # Handle max iterations
            if (self.active_session.iteration >= self.max_iterations and 
                self.active_session.state == RunState.RUNNING):
                self.active_session.state = RunState.ERROR
                self.active_session.error = f"Max iterations ({self.max_iterations}) reached"
            
            return self._prepare_result()
            
        except Exception as e:
            self.active_session.state = RunState.ERROR
            self.active_session.error = str(e)
            logger.error(f"Error in run_task: {str(e)}")
            return self._prepare_result()
        finally:
            self.core.conversation.exit_run_mode()
            
    def _check_completion(self, response_data: Dict[str, Any]) -> bool:
        """Check if task is completed based on response"""
        # Check action results for completion status
        for result in response_data.get("action_results", []):
            if result.get("status") == "completed" and "COMPLETED" in str(result.get("result", "")):
                return True
        return False
        
    def _check_blocked(self, response_data: Dict[str, Any]) -> bool:
        """Check if task is blocked based on response"""
        # Check action results for blocked status
        for result in response_data.get("action_results", []):
            if result.get("status") == "blocked" or "BLOCKED:" in str(result.get("result", "")):
                return True
        return False
        
    def _check_error(self, response_data: Dict[str, Any]) -> bool:
        """Check if task encountered an error"""
        # Check action results for error status
        for result in response_data.get("action_results", []):
            if result.get("status") == "error" or "ERROR:" in str(result.get("result", "")):
                return True
        return False
        
    def _extract_block_reason(self, response_data: Dict[str, Any]) -> Optional[str]:
        """Extract blocking reason from response"""
        response_text = str(response_data.get("assistant_response", ""))
        if "BLOCKED:" in response_text:
            return response_text.split("BLOCKED:", 1)[1].strip()
        return "Task blocked without specific reason"
        
    def _extract_error_message(self, response_data: Dict[str, Any]) -> Optional[str]:
        """Extract error message from response"""
        response_text = str(response_data.get("assistant_response", ""))
        if "ERROR:" in response_text:
            return response_text.split("ERROR:", 1)[1].strip()
        if "CRITICAL ERROR:" in response_text:
            return response_text.split("CRITICAL ERROR:", 1)[1].strip()
        return "Task failed without specific error message"
        
    def _prepare_result(self) -> Dict[str, Any]:
        """Prepare final result dictionary"""
        if not self.active_session:
            return {"status": "error", "error": "No active session"}
            
        return {
            "status": self.active_session.state.value,
            "task_name": self.active_session.task_name,
            "iterations": self.active_session.iteration,
            "results": self.active_session.results,
            "error": str(self.active_session.error) if self.active_session.error else None,
            "block_reason": self.active_session.block_reason,
            "duration": (datetime.now() - self.active_session.start_time).total_seconds()
        }