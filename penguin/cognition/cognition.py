"""
CognitionSystem acts as the brain of Penguin, handling all response generation and enhancement.

This system is responsible for:
1. Core response generation through LLM
2. Response enhancement through various cognitive modules
3. Action parsing and validation
4. Diagnostic tracking
5. Future cognitive architectures (PID loops, Entropix, etc.)

The system maintains a modular structure to allow easy addition of new
cognitive enhancement layers while keeping the core response logic clean.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from penguin.config import TASK_COMPLETION_PHRASE
from penguin.utils.parser import parse_action

logger = logging.getLogger(__name__)

# TODO: Implement cognitive enhancers in future iterations
# class CognitiveEnhancer:
#     """Base class for cognitive enhancement modules."""
#     async def process(self, response: str) -> str:
#         """Process and enhance a response."""
#         return response


class ResponseProcessor:
    """Handles response parsing and formatting."""

    def __init__(self):
        # self.enhancers: List[CognitiveEnhancer] = []
        pass

    # def add_enhancer(self, enhancer: CognitiveEnhancer) -> None:
    #     """Add a cognitive enhancement module."""
    #     self.enhancers.append(enhancer)

    async def process_response(self, raw_response: Any) -> Tuple[str, List[Dict]]:
        """Process raw API response into structured format."""
        # Handle different response formats
        if isinstance(raw_response, dict):
            assistant_response = raw_response.get("assistant_response", "") or str(
                raw_response
            )
        elif hasattr(raw_response, "choices") and raw_response.choices:
            assistant_response = raw_response.choices[0].message.content
        else:
            assistant_response = str(raw_response)

        # TODO: Apply cognitive enhancements in future iterations
        # enhanced_response = assistant_response
        # for enhancer in self.enhancers:
        #     enhanced_response = await enhancer.process(enhanced_response)

        # Parse actions
        actions = parse_action(assistant_response)

        return assistant_response, actions


class CognitionSystem:
    """Main cognitive processing system."""

    def __init__(self, api_client, diagnostics):
        """Initialize the cognition system with required components."""
        self.api_client = api_client
        self.diagnostics = diagnostics
        self.processor = ResponseProcessor()

    async def get_response(
        self,
        conversation_history: list,
        current_iteration: Optional[int] = None,
        max_iterations: Optional[int] = None,
    ) -> Tuple[Dict[str, Any], bool]:
        """
        Generate and process a response through the LLM.

        Args:
            conversation_history: List of conversation messages
            current_iteration: Current iteration count for multi-step tasks
            max_iterations: Maximum allowed iterations

        Returns:
            Tuple[Dict[str, Any], bool]: Response data and continuation flag
        """
        try:
            # Check if the last message contains an image
            last_message = conversation_history[-1]
            if isinstance(last_message["content"], list):
                for content_item in last_message["content"]:
                    if content_item["type"] == "image_url":
                        # If an image is found, add the 'vision' parameter
                        vision = True
                        break
                else:
                    vision = False
            else:
                vision = False

            # Get raw response from API
            raw_response = self.api_client.create_message(
                messages=conversation_history,
                max_tokens=None,
                temperature=None,
                vision=vision,
            )

            # Process and enhance response
            assistant_response, actions = await self.processor.process_response(
                raw_response
            )

            # Check for task completion
            exit_continuation = TASK_COMPLETION_PHRASE in str(assistant_response)

            # Log response details
            logger.debug(f"Processed response: {assistant_response}")
            logger.debug(f"Parsed actions: {actions}")
            logger.debug(f"Exit continuation: {exit_continuation}")

            # Track response tokens
            response_tokens = self.diagnostics.count_tokens(assistant_response)
            self.diagnostics.update_tokens("assistant_response", 0, response_tokens)

            # Construct response dictionary
            response_dict = {
                "assistant_response": assistant_response,
                "actions": actions,
                "metadata": {
                    "iteration": current_iteration,
                    "max_iterations": max_iterations,
                },
            }

            return response_dict, exit_continuation

        except Exception as e:
            logger.error(f"Error in cognitive processing: {str(e)}")
            return {
                "error": f"Cognitive processing error: {str(e)}",
                "assistant_response": "I encountered an error while processing your request.",
                "actions": [],
            }, False

    # TODO: Implement cognitive enhancer functionality in future iterations

    # def add_cognitive_enhancer(self, enhancer: CognitiveEnhancer) -> None:
    #     """Add a new cognitive enhancement module."""
    #     self.processor.add_enhancer(enhancer)
