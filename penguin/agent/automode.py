from typing import Optional, Callable, Any, Tuple
import logging
from chat.ui import print_bordered_message, process_and_display_response, get_user_input, TOOL_COLOR
from config import MAX_CONTINUATION_ITERATIONS, CONTINUATION_EXIT_PHRASE

class Automode:
    def __init__(self, logger: logging.Logger, max_iterations: int = MAX_CONTINUATION_ITERATIONS):
        self.logger = logger
        self.max_iterations = max_iterations
        self.message_count = 0
        self.continue_prompt = "Continue with the next step. Or STOP by saying 'AUTOMODE_COMPLETE' if you think you've achieved the results established in the original request."

    def start(self, user_input: str, message_count: int, chat_function: Callable) -> None:
        try:
            self.message_count = message_count
            self._parse_input(user_input)
            self._initialize_automode()
            automode_goal = self._get_automode_goal()
            self._run_automode_loop(automode_goal, chat_function)
        except KeyboardInterrupt:
            self._handle_interruption()

    def _parse_input(self, user_input: str) -> None:
        parts = user_input.split()
        if len(parts) > 1 and parts[1].isdigit():
            self.max_iterations = int(parts[1])

    def _initialize_automode(self) -> None:
        self.logger.info(f"Entering automode with {self.max_iterations} iterations")
        print_bordered_message(f"Entering automode with {self.max_iterations} iterations. Please provide the goal of the automode.", TOOL_COLOR, "system", self.message_count)
        print_bordered_message("Press Ctrl+C at any time to exit the automode loop.", TOOL_COLOR, "system", self.message_count)

    def _get_automode_goal(self) -> str:
        self.message_count += 1
        automode_goal = get_user_input(self.message_count)
        self.logger.info(f"Automode goal: {automode_goal}")
        return automode_goal

    def _run_automode_loop(self, automode_goal: str, chat_function: Callable) -> None:
        for iteration in range(self.max_iterations):
            try:
                response = chat_function(
                    automode_goal, 
                    self.message_count, 
                    current_iteration=iteration+1, 
                    max_iterations=self.max_iterations
                )
                assistant_response, exit_continuation = self._process_response(response, iteration)
                
                if exit_continuation or CONTINUATION_EXIT_PHRASE in assistant_response:
                    self._complete_automode()
                    break
                
                self.message_count += 1
                automode_goal = self.continue_prompt
                self.logger.info(f"Automode continuation prompt: {automode_goal}")
            except Exception as e:
                self._handle_error(e, iteration)

    def _process_response(self, response: Any, iteration: int) -> Tuple[str, bool]:
        if isinstance(response, tuple) and len(response) == 2:
            assistant_response, exit_continuation = response
        else:
            self.logger.error(f"Unexpected response format in iteration {iteration + 1}: {response}")
            assistant_response = str(response)
            exit_continuation = False
        
        self.logger.info(f"Automode response (iteration {iteration + 1}): {assistant_response}")
        process_and_display_response(assistant_response, self.message_count)
        return assistant_response, exit_continuation

    def _complete_automode(self) -> None:
        self.logger.info("Automode completed")
        print_bordered_message("Automode completed.", TOOL_COLOR, "system", self.message_count)

    def _handle_error(self, e: Exception, iteration: int) -> None:
        error_message = f"Error in automode iteration {iteration + 1}: {str(e)}"
        self.logger.error(error_message)
        self.logger.info(error_message)
        print_bordered_message(error_message, TOOL_COLOR, "system", self.message_count)
        print_bordered_message("Attempting to continue with the next iteration...", TOOL_COLOR, "system", self.message_count)

    def _handle_interruption(self) -> None:
        self.logger.info("Automode interrupted by user")
        print_bordered_message("\nAutomode interrupted by user. Exiting automode.", TOOL_COLOR, "system", self.message_count)