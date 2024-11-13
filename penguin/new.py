#!/usr/bin/env pypy3
import asyncio
from prompt_toolkit.application import create_app_session  # type: ignore
from prompt_toolkit.patch_stdout import patch_stdout  # type: ignore
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
from config import config
from prompts import SYSTEM_PROMPT
from new_core import PenguinCore
from dotenv import load_dotenv  # type: ignore
import warnings
from agent.task_manager import TaskManager
from rich.console import Console

# Load environment variables first
load_dotenv()

# Basic logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('Penguin')

async def init_penguin() -> ChatManager:
    """Initialize Penguin components"""
    try:
        console = Console()  # Create a rich console instance
        console.print("\nInitializing components...", style="bold green")
        
        console.print("1. Creating API client...", style="bold green")
        model_config = ModelConfig(
            model=config['model']['default'],
            provider=config['model']['provider'],
            api_base=config['api']['base_url'],
            use_assistants_api=config['model'].get('use_assistants_api', False)
        )
        api_client = APIClient(model_config=model_config)
        api_client.set_system_prompt(SYSTEM_PROMPT)
        
        console.print("2. Creating managers...", style="bold green")
        tool_manager = ToolManager(log_error)
        task_manager = TaskManager(logger)
        
        console.print("3. Waiting for memory search initialization...", style="bold green")
        await asyncio.to_thread(tool_manager.memory_search.wait_for_initialization)
        
        console.print("4. Creating PenguinCore...", style="bold green")
        penguin_core = PenguinCore(
            api_client=api_client,
            tool_manager=tool_manager,
            task_manager=task_manager
        )
        penguin_core.set_system_prompt(SYSTEM_PROMPT)
        
        console.print("5. Creating ChatManager...", style="bold green")
        chat_manager = ChatManager(penguin_core, PromptUI())
        console.print("Initialization complete!", style="bold green")
        return chat_manager
        
    except Exception as e:
        console.print(f"\nInitialization error: {str(e)}", style="bold red")
        logger.exception("Initialization error")
        raise

async def main():
    """Main entry point"""
    try:
        console = Console()
        console.print("\n=== Starting Penguin AI ===", style="bold green")
        logger.debug("Starting main application...")
        
        chat_manager = await init_penguin()
        
        console.print("\nInitialization complete, starting chat interface...", style="bold green")
        try:
            console.print("Entering chat loop...", style="bold green")
            logger.debug("About to enter create_app_session")
            print("About to enter create_app_session")
            
            with create_app_session():
                logger.debug("Inside create_app_session")
                print("Inside create_app_session")
                await chat_manager.run_chat()
                
        except Exception as e:
            logger.error(f"Error in create_app_session: {str(e)}")
            logger.error(f"Error type: {type(e)}")
            logger.error(f"Error dir: {dir(e)}")
            print(f"Error in create_app_session: {str(e)}")
            print(f"Error type: {type(e)}")
            raise
        console.print("Chat manager completed", style="bold green")
                
    except KeyboardInterrupt:
        console.print("\nShutting down gracefully...", style="bold yellow")
    except Exception as e:
        console.print(f"\nFatal error: {str(e)}", style="bold red")
        logger.exception(f"Fatal error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())