import os
from chat.logs import setup_logger, log_event, logger
from colorama import init
from chat.chat_manager import ChatManager
from chat.ui import (
    print_bordered_message, process_and_display_response, print_welcome_message,
    get_user_input, get_image_path, get_image_prompt,
    TOOL_COLOR, PENGUIN_COLOR
)
from config import MAX_CONTINUATION_ITERATIONS, CONTINUATION_EXIT_PHRASE

# Initialize colorama
init()

def run_chat(chat_manager: ChatManager):
    log_file = setup_logger()
    log_event(log_file, "system", "Starting Penguin AI")
    print_welcome_message()
    
    message_count = 0
    
    while True:
        message_count += 1
        user_input = get_user_input(message_count)
        log_event(log_file, "user", f"User input: {user_input}")        
        
        if user_input.lower() == 'exit':
            log_event(log_file, "system", "Exiting chat session")
            print_bordered_message("Thank you for chatting. Goodbye!", PENGUIN_COLOR, "system", message_count)
            break
        
        if user_input.lower() == 'image':
            image_path = get_image_path()
            
            if os.path.isfile(image_path):
                user_input = get_image_prompt()
                response, _ = chat_manager.chat_with_claude(user_input, image_path)
                log_event(log_file, "assistant", f"Assistant response (with image): {response}")
                message_count += 1
                process_and_display_response(response, message_count)
            else:
                print_bordered_message("Invalid image path. Please try again.", PENGUIN_COLOR, "system", message_count)
                continue
        elif user_input.lower().startswith('automode'):
            try:
                parts = user_input.split()
                if len(parts) > 1 and parts[1].isdigit():
                    max_iterations = int(parts[1])
                else:
                    max_iterations = MAX_CONTINUATION_ITERATIONS
                
                chat_manager.automode = True
                print_bordered_message(f"Entering automode with {max_iterations} iterations. Press Ctrl+C to exit automode at any time.", TOOL_COLOR, "system", message_count)
                message_count += 1
                user_input = get_user_input(message_count)
                
                iteration_count = 0
                try:
                    while chat_manager.automode and iteration_count < max_iterations:
                        response, exit_continuation = chat_manager.chat_with_claude(user_input, current_iteration=iteration_count+1, max_iterations=max_iterations)
                        message_count += 1
                        process_and_display_response(response, message_count)
                        
                        if exit_continuation or CONTINUATION_EXIT_PHRASE in response:
                            print_bordered_message("Automode completed.", TOOL_COLOR, "system", message_count)
                            chat_manager.automode = False
                        else:
                            print_bordered_message(f"Continuation iteration {iteration_count + 1} completed.", TOOL_COLOR, "system", message_count)
                            user_input = "Continue with the next step."
                        
                        iteration_count += 1
                        
                        if iteration_count >= max_iterations:
                            print_bordered_message("Max iterations reached. Exiting automode.", TOOL_COLOR, "system", message_count)
                            chat_manager.automode = False
                except KeyboardInterrupt:
                    print_bordered_message("\nAutomode interrupted by user. Exiting automode.", TOOL_COLOR, "system", message_count)
                    chat_manager.automode = False
                    chat_manager.memory.add_assistant_message("Automode interrupted. How can I assist you further?")
            except KeyboardInterrupt:
                print_bordered_message("\nAutomode interrupted by user. Exiting automode.", TOOL_COLOR, "system", message_count)
                chat_manager.automode = False
                chat_manager.memory.add_assistant_message("Automode interrupted. How can I assist you further?")
            
            print_bordered_message("Exited automode. Returning to regular chat.", TOOL_COLOR, "system", message_count)
        else:
            response, _ = chat_manager.chat_with_claude(user_input)
            log_event(log_file, "assistant", f"Assistant response: {response}")
            message_count += 1
            process_and_display_response(response, message_count)