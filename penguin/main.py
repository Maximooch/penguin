import time
import os
import sys

# Get the start time from the environment variable set by the wrapper script, or use current time if not set
start_time = float(os.environ.get('PENGUIN_START_TIME', time.time()))

def log_time(description, start):
    end = time.time()
    return end - start

import_start = time.time()

# Rest of the imports
import subprocess
import site
import logging
from logging.handlers import RotatingFileHandler
from colorama import init # type: ignore
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
from dotenv import load_dotenv # type: ignore

import_time = log_time("Import time", import_start)

load_dotenv()

def setup_logger(log_file='Penguin.log', log_level=logging.INFO):
    print("Setting up logger")  # Debug print
    logger = logging.getLogger('Penguin')
    logger.setLevel(log_level)

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
    logger.propagate = False

    return logger

def main():
    global start_time

    timing_info = {}

    timing_info['logger_setup'] = log_time("Logger setup", time.time())
    logger = setup_logger()
    init()

    timing_info['model_config'] = log_time("Model config setup", time.time())
    model_config = ModelConfig(
        model=config['model']['default'],
        provider=config['model']['provider'],
        api_base=config['api']['base_url']
    )

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

    timing_info['tool_manager'] = log_time("Tool manager setup", time.time())
    tool_manager = ToolManager(log_error)

    timing_info['penguin_core'] = log_time("Penguin core setup", time.time())
    penguin_core = PenguinCore(api_client, tool_manager)
    penguin_core.set_system_prompt(SYSTEM_PROMPT)

    timing_info['chat_manager'] = log_time("Chat manager setup", time.time())
    chat_manager = ChatManager(penguin_core)

    end_time = time.time()
    total_bootup_duration = end_time - start_time

    print("\nTiming Information:")
    print(f"{'Component':<20} {'Time (seconds)':<15}")
    print("-" * 35)
    print(f"{'Import time':<20} {import_time:.2f}")
    for component, time_taken in timing_info.items():
        print(f"{component.replace('_', ' ').capitalize():<20} {time_taken:.2f}")
    print("-" * 35)
    print(f"{'Total bootup time':<20} {total_bootup_duration:.2f}")

    logger.info(f"Total bootup process completed in {total_bootup_duration:.2f} seconds")

    chat_manager.run_chat()

if __name__ == "__main__":
    main()