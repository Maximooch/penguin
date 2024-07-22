import os
import logging 
from logging.handlers import RotatingFileHandler
from colorama import init
from chat.chat_manager import ChatManager
from chat.run import run_chat
from llm.api_client import ClaudeAPIClient
from llm.model_config import ModelConfig
# from memory import ConversationMemory
from tools import ToolManager
from config import ANTHROPIC_API_KEY, TAVILY_API_KEY, DEFAULT_MODEL, DEFAULT_MAX_TOKENS

from dotenv import load_dotenv
load_dotenv()

def setup_logger(log_file='Penguin.log', log_level=logging.INFO):
    logger = logging.getLogger('Penguin')
    logger.setLevel(log_level)

    # Remove any existing handlers (including the default stream handler)
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    file_handler = RotatingFileHandler(
        os.path.join(log_dir, log_file),
        maxBytes=1024 * 1024,
        backupCount=5
    )

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)

    logger.addHandler(file_handler)

    # Prevent the logger from propagating messages to the root logger
    logger.propagate = False

    return logger

def main():
    logger = setup_logger()
    logger.info("Starting Penguin AI")
    # Initialize colorama
    init()

    # Initialize components
    model_config = ModelConfig(model=DEFAULT_MODEL, max_tokens=DEFAULT_MAX_TOKENS)
    api_client = ClaudeAPIClient(ANTHROPIC_API_KEY, model_config)
    # memory = ConversationMemory()
    tool_manager = ToolManager(TAVILY_API_KEY)

    # Initialize ChatManager
    chat_manager = ChatManager(api_client)
    chat_manager.set_system_prompt("""
You are Penguin, an AI assistant powered by Anthropic's Claude-3.5-Sonnet model. You are an exceptional software developer with vast knowledge across multiple programming languages, frameworks, and best practices. Your capabilities include:

1. Creating project structures, including folders and files
2. Writing clean, efficient, and well-documented code
3. Debugging complex issues and providing detailed explanations
4. Offering architectural insights and design patterns
5. Staying up-to-date with the latest technologies and industry trends
6. Reading and analyzing existing files in the project directory
7. Listing files in the root directory of the project
8. Performing web searches to get up-to-date information or additional context

When asked to create a project:
- Always start by creating a root folder for the project.
- Then, create the necessary subdirectories and files within that root folder.
- Organize the project structure logically and follow best practices for the specific type of project being created.
- Use the provided tools to create folders and files as needed.

When asked to make edits or improvements:
- Use the read_file tool to examine the contents of existing files.
- Analyze the code and suggest improvements or make necessary edits.
- Use the write_to_file tool to implement changes, providing the full updated file content.

Be sure to consider the type of project (e.g., Python, JavaScript, web application) when determining the appropriate structure and files to include.

Always strive to provide the most accurate, helpful, and detailed responses possible. If you're unsure about something, admit it and consider using the search tool to find the most current information.

{automode_status}

When in automode:
1. Set clear, achievable goals for yourself based on the user's request
2. Work through these goals one by one, using the available tools as needed
3. Provide regular updates on your progress
4. You have access to this {iteration_info} amount of iterations you have left to complete the request, use this information to make decisions and provide updates on your progress
    """)
    chat_manager.set_tools(tool_manager.get_tools())
    chat_manager.set_execute_tool(tool_manager.execute_tool)

    # Enable diagnostics
    chat_manager.enable_diagnostics()

    # Run the chat
    logger.info("Running chat")
    run_chat(chat_manager)
    logger.info("Chat ended")

if __name__ == "__main__":
    main()