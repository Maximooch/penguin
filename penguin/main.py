#!/usr/bin/env pypy3
import asyncio
import time
import os
import sys
import logging
from config import WORKSPACE_PATH
from logging.handlers import RotatingFileHandler
from typing import Dict, Any, Optional
from chat.cli import PenguinCLI
from llm.model_config import ModelConfig
from utils.log_error import log_error
from tools import ToolManager
from llm.api_client import APIClient
from config import config
from system_prompt import SYSTEM_PROMPT
from core import PenguinCore
from dotenv import load_dotenv  # type: ignore
import warnings
from rich.console import Console # type: ignore
import subprocess
from pathlib import Path
import traceback  # Add this import
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn # type: ignore
from utils.timing import track_startup_time

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

@track_startup_time("Ollama Server")
async def init_ollama_server() -> None:
    """Initialize Ollama server in background process"""
    logger.info("Starting Ollama server...")
    try:
        # Start ollama serve in background
        process = subprocess.Popen(
            "ollama serve",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Wait for server to start (max 30 seconds)
        start_time = time.time()
        while time.time() - start_time < 30:
            try:
                # Test connection with a simple embedding
                import ollama # type: ignore
                client = ollama.Client(timeout=5.0)
                client.embeddings(model='nomic-embed-text', prompt='test')
                logger.info("Ollama server started successfully")
                return
            except Exception:
                await asyncio.sleep(1)
                continue
                
        raise TimeoutError("Ollama server failed to start within timeout")
        
    except Exception as e:
        logger.warning(f"Failed to start Ollama server: {str(e)}")
        logger.warning("Continuing without embeddings support")

@track_startup_time("Memory Search")
async def init_memory_search(tool_manager) -> None:
    await asyncio.to_thread(tool_manager.memory_search.wait_for_initialization)

@track_startup_time("Code Indexer") 
async def init_code_indexer(tool_manager) -> None:
    await asyncio.to_thread(tool_manager.code_indexer.index_directory, WORKSPACE_PATH)

async def init_components() -> PenguinCLI:
    """Initialize Penguin components with parallel loading and progress tracking"""
    start_time = time.time()
    console = Console()
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console
        ) as progress:
            # Create progress tasks
            ollama_task = progress.add_task("[yellow]Starting Ollama server...", total=None)
            memory_task = progress.add_task("[yellow]Initializing memory search...", total=None)
            indexer_task = progress.add_task("[yellow]Indexing workspace...", total=None)
            
            # Initialize core components first
            model_config = ModelConfig(
                model=config['model']['default'],
                provider=config['model']['provider'],
                api_base=config['api']['base_url'],
                use_assistants_api=config['model'].get('use_assistants_api', False)
            )
            
            api_client = APIClient(model_config=model_config)
            api_client.set_system_prompt(SYSTEM_PROMPT)
            tool_manager = ToolManager(log_error)
            
            # Start heavy initialization tasks in parallel
            init_tasks = [
                (init_ollama_server(), ollama_task),
                (init_memory_search(tool_manager), memory_task),
                (init_code_indexer(tool_manager), indexer_task)
            ]
            
            # Create core components while background tasks run
            penguin_core = PenguinCore(
                api_client=api_client,
                tool_manager=tool_manager
            )
            penguin_core.set_system_prompt(SYSTEM_PROMPT)
            cli = PenguinCLI(penguin_core)
            
            # Wait for background tasks with progress updates
            for coro, task_id in init_tasks:
                try:
                    await asyncio.wait_for(coro, timeout=10.0)
                    progress.update(task_id, description=f"[green]✓ {progress.tasks[task_id].description[8:]}")
                except asyncio.TimeoutError:
                    progress.update(task_id, description=f"[red]⨯ {progress.tasks[task_id].description[8:]} (timeout)")
                except Exception as e:
                    progress.update(task_id, description=f"[red]⨯ {progress.tasks[task_id].description[8:]} ({str(e)})")
            
            # Show final startup time
            elapsed = time.time() - start_time
            console.print(f"\n[green]Startup completed in {elapsed:.2f}s[/green]\n")
                
            return cli

    except Exception as e:
        logger.exception("Fatal initialization error")
        raise

async def main():
    total_start = time.time()
    console = Console()
    
    # Single workspace initialization message
    console.print(f"\nWorkspace path: {WORKSPACE_PATH}")
    workspace_start = time.time()
    console.print("\n=== Starting Penguin ===\n")
    workspace_end = time.time()
    console.print(f"[yellow]Workspace initialization: {workspace_end - workspace_start:.2f}s[/yellow]")
    
    try:
        # Initialize core components
        init_start = time.time()
        cli = await init_components()
        init_time = time.time() - init_start
        
        # Show detailed timing breakdown
        total_time = time.time() - total_start
        console.print(f"\n[green]Initialization time: {init_time:.2f}s[/green]")
        console.print(f"[green]Total startup time: {total_time:.2f}s[/green]\n")
        
        # Start chat loop
        await cli.chat_loop()
                
    except Exception as e:
        console.print(f"\n[red]Fatal error: {str(e)}[/red]")
        console.print("\n[red]Traceback:[/red]")
        console.print(traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())