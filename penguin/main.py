#!/usr/bin/env pypy3
import asyncio
from prompt_toolkit.application import create_app_session  # type: ignore
# from prompt_toolkit.patch_stdout import patch_stdout  # type: ignore
import time
import os
import sys
import logging
from config import WORKSPACE_PATH
from logging.handlers import RotatingFileHandler
from typing import Dict, Any, Optional
from chat.chat import ChatManager
from chat.prompt_ui import PromptUI
from llm.model_config import ModelConfig
from utils.log_error import log_error
from tools import ToolManager
from llm.api_client import APIClient
from config import config, load_config
# from prompts import SYSTEM_PROMPT
from system_prompt import SYSTEM_PROMPT
from core import PenguinCore
from dotenv import load_dotenv  # type: ignore
import warnings
from agent.task_manager import TaskManager
from rich.console import Console # type: ignore

# Load environment variables first
load_dotenv()

# Basic logging setup
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger('Penguin')

# Silence other chatty loggers
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('sentence_transformers').setLevel(logging.WARNING)
logging.getLogger('LiteLLM').setLevel(logging.WARNING)
logging.getLogger('tools').setLevel(logging.WARNING)
logging.getLogger('llm').setLevel(logging.WARNING)
logging.getLogger('chat').setLevel(logging.WARNING)

# Optional: If you want to keep logs in a file instead of console
if not os.path.exists('logs'):
    os.makedirs('logs')
file_handler = RotatingFileHandler(
    'logs/penguin.log',
    maxBytes=1024 * 1024,  # 1MB
    backupCount=5
)
file_handler.setLevel(logging.INFO)
logger.addHandler(file_handler)

async def init_penguin() -> ChatManager:
    """Initialize Penguin components"""
    try:
        console = Console()  # Create a rich console instance
        
        model_config = ModelConfig(
            model=config['model']['default'],
            provider=config['model']['provider'],
            api_base=config['api']['base_url'],
            use_assistants_api=config['model'].get('use_assistants_api', False)
        )
        
        api_client = APIClient(model_config=model_config)
        api_client.set_system_prompt(SYSTEM_PROMPT)
        
        tool_manager = ToolManager(log_error)
        task_manager = TaskManager(logger)
        
        await asyncio.to_thread(tool_manager.memory_search.wait_for_initialization)
        await asyncio.to_thread(tool_manager.code_indexer.index_directory, WORKSPACE_PATH)
        
        penguin_core = PenguinCore(
            api_client=api_client,
            tool_manager=tool_manager,
            task_manager=task_manager
        )
        penguin_core.set_system_prompt(SYSTEM_PROMPT)
        
        chat_manager = ChatManager(penguin_core, PromptUI())
        return chat_manager
        
    except Exception as e:
        logger.exception("Initialization error")
        raise

async def main():
    console = Console()
    console.print("\n=== Starting Penguin ===\n")
    
    try:
        chat_manager = await init_penguin()
        console.print("[green]Initialization complete![/green]\n")
        
        # Create and use session synchronously
        session = create_app_session()
        with session:
            await chat_manager.run_chat()
                
    except Exception as e:
        console.print(f"\n[red]Fatal error: {str(e)}[/red]")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())