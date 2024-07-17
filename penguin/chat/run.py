import os
from colorama import init, Style
from chat.chat_manager import ChatManager
from chat.ui import (
    print_colored, process_and_display_response, print_welcome_message,
    get_user_input, get_image_path, get_image_prompt,
    TOOL_COLOR, CLAUDE_COLOR
)
from config import MAX_CONTINUATION_ITERATIONS, CONTINUATION_EXIT_PHRASE
# Initialize colorama
init()

def run_chat(chat_manager: ChatManager):
    print_welcome_message()
    
    while True:
        user_input = get_user_input()
        
        if user_input.lower() == 'exit':
            print_colored("Thank you for chatting. Goodbye!", CLAUDE_COLOR)
            break
        
        if user_input.lower() == 'image':
            image_path = get_image_path()
            
            if os.path.isfile(image_path):
                user_input = get_image_prompt()
                response, _ = chat_manager.chat_with_claude(user_input, image_path)
                process_and_display_response(response)
            else:
                print_colored("Invalid image path. Please try again.", CLAUDE_COLOR)
                continue
        elif user_input.lower().startswith('automode'):
            try:
                parts = user_input.split()
                if len(parts) > 1 and parts[1].isdigit():
                    max_iterations = int(parts[1])
                else:
                    max_iterations = MAX_CONTINUATION_ITERATIONS
                
                chat_manager.automode = True
                print_colored(f"Entering automode with {max_iterations} iterations. Press Ctrl+C to exit automode at any time.", TOOL_COLOR)
                user_input = get_user_input()
                
                iteration_count = 0
                try:
                    while chat_manager.automode and iteration_count < max_iterations:
                        response, exit_continuation = chat_manager.chat_with_claude(user_input, current_iteration=iteration_count+1, max_iterations=max_iterations)
                        process_and_display_response(response)
                        
                        if exit_continuation or CONTINUATION_EXIT_PHRASE in response:
                            print_colored("Automode completed.", TOOL_COLOR)
                            chat_manager.automode = False
                        else:
                            print_colored(f"Continuation iteration {iteration_count + 1} completed.", TOOL_COLOR)
                            user_input = "Continue with the next step."
                        
                        iteration_count += 1
                        
                        if iteration_count >= max_iterations:
                            print_colored("Max iterations reached. Exiting automode.", TOOL_COLOR)
                            chat_manager.automode = False
                except KeyboardInterrupt:
                    print_colored("\nAutomode interrupted by user. Exiting automode.", TOOL_COLOR)
                    chat_manager.automode = False
                    chat_manager.memory.add_assistant_message("Automode interrupted. How can I assist you further?")
            except KeyboardInterrupt:
                print_colored("\nAutomode interrupted by user. Exiting automode.", TOOL_COLOR)
                chat_manager.automode = False
                chat_manager.memory.add_assistant_message("Automode interrupted. How can I assist you further?")
            
            print_colored("Exited automode. Returning to regular chat.", TOOL_COLOR)
        else:
            response, _ = chat_manager.chat_with_claude(user_input)
            process_and_display_response(response)