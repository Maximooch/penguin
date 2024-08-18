"""
This module contains the main entry point for running the Penguin AI chat interface.

Functions:
    run_chat(chat_manager: ChatManager):
        The main function that runs the chat loop, handling user input and displaying responses.

    handle_image_input(chat_manager: ChatManager, message_count: int, log_file: str):
        Handles user input when the user wants to send an image to the AI.

    handle_automode(chat_manager: ChatManager, user_input: str, message_count: int, log_file: str):
        Handles user input when the user wants to enter automode.

    run_automode(chat_manager: ChatManager, automode_goal: str, max_iterations: int, message_count: int, log_file: str):
        Runs the automode loop, iteratively prompting the AI and displaying responses.

    handle_automode_interruption(chat_manager: ChatManager, log_file: str, message_count: int):
        Handles the case when the user interrupts the automode loop.
"""

import os
from typing import Any
from colorama import init # type: ignore
from utils.logs import setup_logger, log_event, logger
from chat.chat_manager import ChatManager
from chat.ui import (
    print_bordered_message, process_and_display_response, print_welcome_message,
    get_user_input, get_image_path, get_image_prompt,
    TOOL_COLOR, PENGUIN_COLOR
)
from config import MAX_CONTINUATION_ITERATIONS, CONTINUATION_EXIT_PHRASE

# Constants
EXIT_COMMAND = 'exit'
IMAGE_COMMAND = 'image'
AUTOMODE_COMMAND = 'automode'
AUTOMODE_CONTINUE_PROMPT = "Continue with the next step. Or STOP by saying 'AUTOMODE_COMPLETE' if you think you've achieved the results established in the original request."

init()

def run_chat(chat_manager: ChatManager) -> None:
    log_file = setup_logger()
    log_event(log_file, "system", "Starting Penguin AI")
    print_welcome_message()
    
    message_count = 0
    
    while True:
        message_count += 1
        user_input = get_user_input(message_count)
        log_event(log_file, "user", f"User input: {user_input}")
        
        if user_input.lower() == EXIT_COMMAND:
            log_event(log_file, "system", "Exiting chat session")
            print_bordered_message("Thank you for chatting. Goodbye!", PENGUIN_COLOR, "system", message_count)
            break
        
        try:
            if user_input.lower() == IMAGE_COMMAND:
                handle_image_input(chat_manager, message_count, log_file)
            elif user_input.lower().startswith(AUTOMODE_COMMAND):
                handle_automode(chat_manager, user_input, message_count, log_file)
            else:
                response, exit_continuation = chat_manager.chat_with_penguin(user_input, message_count)
                log_event(log_file, "assistant", f"Assistant response: {response}")
                process_and_display_response(response, message_count)
        except Exception as e:
            error_message = f"An error occurred: {str(e)}"
            logger.error(error_message)
            log_event(log_file, "error", error_message)
            print_bordered_message(error_message, TOOL_COLOR, "system", message_count)
            chat_manager.reset_state()

def handle_image_input(chat_manager: ChatManager, message_count: int, log_file: str) -> None:
    image_path = get_image_path()
    if os.path.isfile(image_path):
        user_input = get_image_prompt()
        response, _ = chat_manager.chat_with_penguin(user_input, message_count, image_path)
        log_event(log_file, "assistant", f"Assistant response (with image): {response}")
        process_and_display_response(response, message_count)
    else:
        print_bordered_message("Invalid image path. Please try again.", PENGUIN_COLOR, "system", message_count)

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