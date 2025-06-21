"""Basic concrete implementation of BaseAgent for development and testing.

This provides a simple working implementation that can be used as a reference
and for testing purposes.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from penguin.agent.base import BaseAgent

logger = logging.getLogger(__name__)


class BasicPenguinAgent(BaseAgent):
    """Simple concrete implementation of BaseAgent that delegates to the core Engine."""

    async def run(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute the agent using the core conversation system."""
        try:
            logger.debug(f"BasicPenguinAgent executing prompt: {prompt[:100]}...")
            
            # Use the conversation manager to process the prompt
            # This mirrors how PenguinCore processes messages
            result = await self.conversation_manager.process_message(prompt)
            
            return {
                "status": "completed",
                "assistant_response": result.get("assistant_response", ""),
                "action_results": result.get("action_results", []),
                "agent_type": "BasicPenguinAgent"
            }
            
        except Exception as e:
            logger.exception(f"Error in BasicPenguinAgent.run: {e}")
            return {
                "status": "error", 
                "error": str(e),
                "agent_type": "BasicPenguinAgent"
            }

    # Backward compatibility implementations for deprecated methods
    async def plan(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Backward compatibility wrapper for run()."""
        return await self.run(prompt, context)

    async def act(self, action_data: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Placeholder implementation for deprecated act method."""
        logger.warning("BasicPenguinAgent.act() is deprecated and not implemented")
        return {"status": "not_implemented", "message": "act() method is deprecated"}

    async def observe(self, results: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Placeholder implementation for deprecated observe method."""
        logger.warning("BasicPenguinAgent.observe() is deprecated and not implemented")
        return {"status": "not_implemented", "message": "observe() method is deprecated"} 