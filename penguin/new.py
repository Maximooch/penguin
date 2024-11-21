#!/usr/bin/env pypy3
import asyncio
from prompt_toolkit.application import create_app_session  # type: ignore
# from prompt_toolkit.patch_stdout import patch_stdout  # type: ignore
import time
import os
import sys
import logging
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
from prompts2 import SYSTEM_PROMPT
from new_core import PenguinCore
from dotenv import load_dotenv  # type: ignore
import warnings
from agent.task_manager import TaskManager
from rich.console import Console # type: ignore

# Load environment variables first
load_dotenv()

# Basic logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('Penguin')

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
        
        # Load the configuration
        config = load_config()
        model_name = config['model']['default']
        model_specific_config = config['model_configs'].get(model_name, {})
        
        # Create model config first
        console.print("1. Creating model config...")
        model_config = ModelConfig(
            model=model_name,
            provider=config['model']['provider'],
            use_assistants_api=config['model'].get('use_assistants_api', False),
            max_tokens=model_specific_config.get('max_tokens'),
            temperature=model_specific_config.get('temperature'),
            api_base=config['api'].get('base_url'),
            supports_vision=model_specific_config.get('supports_vision', False)
        )
        
        # Create API client with model config
        console.print("2. Creating API client...")
        api_client = APIClient(model_config=model_config)
        api_client.set_system_prompt(SYSTEM_PROMPT)
        
        # Create managers
        console.print("3. Creating managers...")
        tool_manager = ToolManager(log_error)
        task_manager = TaskManager(logger)
        
        # Create core components
        console.print("4. Creating PenguinCore...")
        core = PenguinCore(
            api_client=api_client,
            tool_manager=tool_manager,
            task_manager=task_manager
        )
        core.set_system_prompt(SYSTEM_PROMPT)
        
        # Create UI and chat manager
        console.print("5. Creating ChatManager...")
        ui = PromptUI()
        chat_manager = ChatManager(core, ui)
        
        console.print("[green]Initialization complete![/green]")
        
        # Create and use session synchronously
        session = create_app_session()
        with session:  # Use regular 'with' instead of 'async with'
            await chat_manager.run_chat()
                
    except Exception as e:
        console.print(f"\n[red]Fatal error: {str(e)}[/red]")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())