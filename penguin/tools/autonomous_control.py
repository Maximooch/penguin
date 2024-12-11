from typing import Dict, Any, Optional, List
import pyautogui
import logging
import time
from pathlib import Path
import json
import cv2 # type: ignore
import numpy as np # type: ignore
from dataclasses import dataclass
from enum import Enum

class InteractionState(Enum):
    IDLE = "idle"
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"
    WAITING_FOR_ELEMENT = "waiting_for_element"

@dataclass
class InteractionContext:
    task_id: str
    start_time: float
    last_action_time: float
    screenshot_dir: Path
    state: InteractionState
    error_count: int = 0
    max_retries: int = 3
    
class AutonomousController:
    def __init__(self, workspace_path: Path):
        self.logger = logging.getLogger(__name__)
        self.workspace = workspace_path
        self.context: Optional[InteractionContext] = None
        
        # Safety settings
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 1.0  # Conservative pause between actions
        
        # Initialize monitoring
        self.action_log: List[Dict[str, Any]] = []
        self.setup_monitoring()

    def setup_monitoring(self):
        """Setup monitoring and logging directories"""
        self.log_dir = self.workspace / "autonomous_logs"
        self.screenshot_dir = self.workspace / "autonomous_screenshots"
        self.log_dir.mkdir(exist_ok=True)
        self.screenshot_dir.mkdir(exist_ok=True)

    async def start_autonomous_session(self, task_id: str) -> None:
        """Start an autonomous interaction session"""
        self.context = InteractionContext(
            task_id=task_id,
            start_time=time.time(),
            last_action_time=time.time(),
            screenshot_dir=self.screenshot_dir / task_id,
            state=InteractionState.IDLE
        )
        self.context.screenshot_dir.mkdir(exist_ok=True)
        self.log_action("session_start", {"task_id": task_id})

    async def execute_interaction(self, action_plan: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Execute a series of UI interactions"""
        if not self.context:
            raise RuntimeError("No active autonomous session")
            
        results = []
        
        for action in action_plan:
            try:
                # Take safety screenshot before action
                self.take_safety_screenshot(f"pre_{action['type']}")
                
                # Execute action with retry logic
                result = await self._execute_single_action(action)
                results.append(result)
                
                # Take verification screenshot
                self.take_safety_screenshot(f"post_{action['type']}")
                
                # Update context
                self.context.last_action_time = time.time()
                
            except Exception as e:
                self.handle_interaction_error(e, action)
                break

        return {
            "status": "completed",
            "results": results,
            "duration": time.time() - self.context.start_time
        }

    async def _execute_single_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a single UI interaction with verification"""
        action_type = action["type"]
        params = action.get("params", {})
        
        if self.context.state == InteractionState.ERROR:
            raise RuntimeError("System in error state")
            
        self.context.state = InteractionState.ACTIVE
        
        try:
            if action_type == "click":
                return await self._handle_click(params)
            elif action_type == "type":
                return await self._handle_type(params)
            elif action_type == "verify_element":
                return await self._handle_verify(params)
            else:
                raise ValueError(f"Unknown action type: {action_type}")
                
        finally:
            self.context.state = InteractionState.IDLE

    def take_safety_screenshot(self, prefix: str) -> Path:
        """Take a safety screenshot for verification and debugging"""
        timestamp = int(time.time())
        filename = f"{prefix}_{timestamp}.png"
        path = self.context.screenshot_dir / filename
        screenshot = pyautogui.screenshot()
        screenshot.save(path)
        return path

    def handle_interaction_error(self, error: Exception, action: Dict[str, Any]) -> None:
        """Handle interaction errors with logging and recovery attempts"""
        self.context.error_count += 1
        self.context.state = InteractionState.ERROR
        
        error_data = {
            "error_type": type(error).__name__,
            "error_message": str(error),
            "action": action,
            "timestamp": time.time()
        }
        
        self.log_action("error", error_data)
        
        # Take error screenshot
        self.take_safety_screenshot("error")
        
        if self.context.error_count >= self.context.max_retries:
            raise RuntimeError("Max retry attempts exceeded")

    def log_action(self, action_type: str, data: Dict[str, Any]) -> None:
        """Log an action with its context and results"""
        log_entry = {
            "timestamp": time.time(),
            "action_type": action_type,
            "task_id": self.context.task_id if self.context else None,
            "state": self.context.state.value if self.context else None,
            "data": data
        }
        
        self.action_log.append(log_entry)
        
        # Write to log file
        log_file = self.log_dir / f"{self.context.task_id}.jsonl"
        with open(log_file, "a") as f:
            json.dump((log_entry) + "\n")
