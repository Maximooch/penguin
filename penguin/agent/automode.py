import os
from typing import Any
from utils.logs import log_event, logger
from chat.chat_manager import ChatManager
from chat.ui import (
    print_bordered_message, process_and_display_response,
    get_user_input, TOOL_COLOR
)
from config import MAX_CONTINUATION_ITERATIONS, CONTINUATION_EXIT_PHRASE

AUTOMODE_CONTINUE_PROMPT = "Continue with the next step. Or STOP by saying 'AUTOMODE_COMPLETE' if you think you've achieved the results established in the original request."

def handle_automode(chat_manager: ChatManager, user_input: str, message_count: int, log_file: str) -> None:
    try:
        parts = user_input.split()
        max_iterations = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else MAX_CONTINUATION_ITERATIONS
        
        chat_manager.automode = True
        log_event(log_file, "system", f"Entering automode with {max_iterations} iterations")
        print_bordered_message(f"Entering automode with {max_iterations} iterations. Please provide the goal of the automode.", TOOL_COLOR, "system", message_count)
        print_bordered_message("Press Ctrl+C at any time to exit the automode loop.", TOOL_COLOR, "system", message_count)
        
        message_count += 1
        automode_goal = get_user_input(message_count)
        log_event(log_file, "user", f"Automode goal: {automode_goal}")
        
        run_automode(chat_manager, automode_goal, max_iterations, message_count, log_file)
    except KeyboardInterrupt:
        handle_automode_interruption(chat_manager, log_file, message_count)
    finally:
        chat_manager.reset_state()

def run_automode(chat_manager: ChatManager, automode_goal: str, max_iterations: int, message_count: int, log_file: str) -> None:
    for iteration in range(max_iterations):
        try:
            response, exit_continuation = chat_manager.chat_with_penguin(automode_goal, message_count, current_iteration=iteration+1, max_iterations=max_iterations)
            log_event(log_file, "assistant", f"Automode response (iteration {iteration + 1}): {response}")
            process_and_display_response(response, message_count)
            
            if exit_continuation or CONTINUATION_EXIT_PHRASE in response:
                log_event(log_file, "system", "Automode completed")
                print_bordered_message("Automode completed.", TOOL_COLOR, "system", message_count)
                break
            
            message_count += 1
            automode_goal = AUTOMODE_CONTINUE_PROMPT
            log_event(log_file, "user", f"Automode continuation prompt: {automode_goal}")
        except Exception as e:
            error_message = f"Error in automode iteration {iteration + 1}: {str(e)}"
            logger.error(error_message)
            log_event(log_file, "error", error_message)
            print_bordered_message(error_message, TOOL_COLOR, "system", message_count)
            break

def handle_automode_interruption(chat_manager: ChatManager, log_file: str, message_count: int) -> None:
    log_event(log_file, "system", "Automode interrupted by user")
    print_bordered_message("\nAutomode interrupted by user. Exiting automode.", TOOL_COLOR, "system", message_count)
    chat_manager.automode = False
    chat_manager.add_message("assistant", "Automode interrupted. How can I assist you further?")