import os
import sys 
import subprocess
import site
import logging

from logging.handlers import RotatingFileHandler
from colorama import init # type: ignore
# from chat.chat_manager import ChatManager
# from chat.run import run_chat
from chat.chat import ChatManager
from llm.model_config import ModelConfig
from utils.log_error import log_error
from tools import ToolManager
from llm.providers import get_ai_client
from config import (
    MODEL_API_KEY,
    TAVILY_API_KEY,
    DEFAULT_MODEL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_PROVIDER,
    SYSTEM_PROMPT
)
from core import PenguinCore

from dotenv import load_dotenv # type: ignore

load_dotenv()



def ensure_venv():
    venv_path = os.path.join(os.path.dirname(__file__), 'penguin_venv')
    print(f"Checking for virtual environment at: {venv_path}")
    if not os.path.exists(venv_path):
        print("Virtual environment not found. Setting up...")
        subprocess.check_call([sys.executable, 'setup_venv.py'])
    
    if sys.prefix != venv_path:
        print(f"Current sys.prefix: {sys.prefix}")
        print(f"Expected venv path: {venv_path}")
        if os.name == 'nt':  # Windows
            site_packages = os.path.join(venv_path, 'Lib', 'site-packages')
            prev_sys_path = sys.path[:]
            site.main()
            sys.path[:] = prev_sys_path
            site.addsitedir(site_packages)
        else:  # Unix-like systems
            activate_this = os.path.join(venv_path, 'bin', 'activate_this.py')
            if os.path.exists(activate_this):
                exec(open(activate_this).read(), {'__file__': activate_this})
            else:
                site_packages = os.path.join(venv_path, 'lib', 'python{}.{}'.format(*sys.version_info[:2]), 'site-packages')
                prev_sys_path = sys.path[:]
                site.main()
                sys.path[:] = prev_sys_path
                site.addsitedir(site_packages)

    print(f"Python executable: {sys.executable}")
    print(f"sys.path: {sys.path}")

    print(f"Using virtual environment: {venv_path}")

ensure_venv()

def setup_logger(log_file='Penguin.log', log_level=logging.INFO):
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
    logger = setup_logger()
    logger.info("Starting Penguin AI")
    init()

    model_config = ModelConfig(model=DEFAULT_MODEL, max_tokens=DEFAULT_MAX_TOKENS)
    try:
        api_client = get_ai_client(MODEL_API_KEY, model_config, DEFAULT_PROVIDER)  # Initialize the appropriate AI client based on the provider
        logger.info(f"Using AI provider: {DEFAULT_PROVIDER}")
    except ValueError as e:
        logger.error(f"Error initializing AI client: {str(e)}")
        sys.exit(1)
    tool_manager = ToolManager(log_error)

    penguin_core = PenguinCore(api_client, tool_manager)
    penguin_core.set_system_prompt(SYSTEM_PROMPT)

    chat_manager = ChatManager(penguin_core)

    # penguin_core.enable_diagnostics()
    # penguin_core.disable_diagnostics()

    logger.info("Running chat")
    chat_manager.run_chat()
    logger.info("Chat ended")

if __name__ == "__main__":
    ensure_venv()
    main()