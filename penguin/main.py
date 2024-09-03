import os
import sys 
import subprocess
import site
import logging
import time

from logging.handlers import RotatingFileHandler
from colorama import init # type: ignore
from chat.chat import ChatManager
from llm.model_config import ModelConfig
from utils.log_error import log_error
from tools import ToolManager
from llm.api_client import APIClient
from config import (
    GROQ_API_KEY, 
    # Remove or comment out the following lines:
    # DEFAULT_MODEL,
    # DEFAULT_MAX_TOKENS,
    # DEFAULT_TEMPERATURE,
    # DEFAULT_PROVIDER,
    SYSTEM_PROMPT
)
from core import PenguinCore

from dotenv import load_dotenv # type: ignore

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
    start_time = time.time()
    
    logger = setup_logger()
    init()

    model_config = ModelConfig()

    try:
        api_client = APIClient(api_key=GROQ_API_KEY, model_config=model_config)
        logger.info(f"Using AI model: {model_config.model}")
    except Exception as e:
        error_message = f"Unexpected error: {str(e)}"
        logger.error(error_message)
        print(error_message)
        sys.exit(1)

    tool_manager = ToolManager(log_error)

    penguin_core = PenguinCore(api_client, tool_manager)
    penguin_core.set_system_prompt(SYSTEM_PROMPT)

    chat_manager = ChatManager(penguin_core)

    end_time = time.time()
    bootup_duration = end_time - start_time
    print(f"Bootup process completed in {bootup_duration:.2f} seconds")
    logger.info(f"Bootup process completed in {bootup_duration:.2f} seconds")

    chat_manager.run_chat()

if __name__ == "__main__":
    main()