#!/usr/bin/env pypy3
import time
import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from colorama import init as colorama_init
from typing import Dict, Any, Optional
from chat.chat import ChatManager
from llm.model_config import ModelConfig
from utils.log_error import log_error
from tools import ToolManager
from llm.api_client import APIClient
from config import (
    config,  # Import the entire config dictionary
    DEFAULT_MODEL,
    DEFAULT_PROVIDER
)
from prompts import SYSTEM_PROMPT
from core import PenguinCore
from dotenv import load_dotenv  # type: ignore

"""
This module serves as the main entry point for the Penguin AI assistant.
It handles initialization of core components, logging setup, and manages the chat interface.

The module performs the following key tasks:
1. Sets up logging
2. Initializes the AI model and API client
3. Sets up the tool manager and memory search
4. Initializes the PenguinCore and ChatManager
5. Runs the chat interface

It also includes timing information for various initialization steps to help with performance analysis.
"""

# Load environment variables from .env file
load_dotenv()

# Get the start time of the application, either from environment variable or current time
start_time: float = float(os.environ.get('PENGUIN_START_TIME', str(time.time())))

def log_time(description: str, start: float) -> float:
    """
    Calculate and return the time elapsed for a specific operation.

    Args:
        description (str): A description of the operation being timed.
        start (float): The start time of the operation.

    Returns:
        float: The time elapsed for the operation in seconds.
    """
    end = time.time()
    return end - start

def setup_logger(log_file: str = 'Penguin.log', log_level: int = logging.INFO) -> logging.Logger:
    """
    Set up and configure the logger for the application.

    This function creates a logger with both console and file handlers. The file handler
    uses a RotatingFileHandler to manage log file sizes.

    Args:
        log_file (str): Name of the log file. Defaults to 'Penguin.log'.
        log_level (int): Logging level. Defaults to logging.INFO.

    Returns:
        logging.Logger: Configured logger object.
    """
    print("Setting up logger")  # Debug print
    logger = logging.getLogger('Penguin')
    logger.setLevel(log_level)

    # Remove any existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Create logs directory if it doesn't exist
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # Set up file handler with rotation
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, log_file),
        maxBytes=1024 * 1024,  # 1 MB
        backupCount=5
    )

    # Define log format
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)

    # Add the file handler to the logger
    logger.addHandler(file_handler)
    logger.propagate = False  # Prevent log messages from being passed to the root logger

    return logger

def init() -> ChatManager:
    """
    Initialize all components required for the Penguin AI assistant.

    This function performs the following steps:
    1. Sets up logging
    2. Initializes colorama for colored console output
    3. Configures the AI model
    4. Sets up the API client
    5. Initializes the tool manager and memory search
    6. Creates the PenguinCore instance
    7. Sets up the ChatManager

    It also tracks the time taken for each initialization step and prints a summary.

    Returns:
        ChatManager: An instance of ChatManager ready to run the chat interface.
    """
    global penguin_core, chat_manager

    timing_info: Dict[str, float] = {}

    # Set up logger
    timing_info['logger_setup'] = log_time("Logger setup", time.time())
    logger = setup_logger()
    colorama_init()  # Initialize colorama for colored console output

    # Configure AI model
    timing_info['model_config'] = log_time("Model config setup", time.time())
    model_config = ModelConfig(
        model=config['model']['default'],
        provider=config['model']['provider'],
        api_base=config['api']['base_url']
    )

    # Set up API client
    api_client_start = time.time()
    try:
        api_client = APIClient(model_config=model_config)
        api_client.set_system_prompt(SYSTEM_PROMPT)
        logger.info(f"Using AI model: {model_config.model}")
    except Exception as e:
        error_message = f"Unexpected error: {str(e)}"
        logger.error(error_message)
        print(error_message)
        sys.exit(1)
    timing_info['api_client'] = log_time("API client setup", api_client_start)

    # Initialize tool manager
    timing_info['tool_manager'] = log_time("Tool manager setup", time.time())
    tool_manager = ToolManager(log_error)

    # Initialize memory search
    timing_info['memory_search'] = log_time("Memory search initialization", time.time())
    tool_manager.memory_search.wait_for_initialization()

    # Set up PenguinCore
    timing_info['penguin_core'] = log_time("Penguin core setup", time.time())
    penguin_core = PenguinCore(api_client, tool_manager)
    penguin_core.set_system_prompt(SYSTEM_PROMPT)

    # Set up ChatManager
    timing_info['chat_manager'] = log_time("Chat manager setup", time.time())
    chat_manager = ChatManager(penguin_core)

    # Calculate and print timing information
    end_time = time.time()
    total_bootup_duration = end_time - start_time

    print("\nTiming Information:")
    print(f"{'Component':<20} {'Time (seconds)':<15}")
    print("-" * 35)
    for component, time_taken in timing_info.items():
        print(f"{component.replace('_', ' ').capitalize():<20} {time_taken:.2f}")
    print("-" * 35)
    print(f"{'Total bootup time':<20} {total_bootup_duration:.2f}")

    logger.info(f"Total bootup process completed in {total_bootup_duration:.2f} seconds")

    return chat_manager

def run_chat() -> None:
    """
    Start the chat interface using the initialized ChatManager.

    This function is responsible for running the main chat loop where the user
    can interact with the Penguin AI assistant.
    """
    chat_manager.run_chat()

def main() -> None:
    """
    Main entry point of the application.

    This function calls the init() function to set up all necessary components
    and then starts the chat interface by calling run_chat().
    """
    init()
    run_chat()

if __name__ == "__main__":
    main()
