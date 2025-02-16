#!/usr/bin/env python3

import asyncio
import logging
from pathlib import Path

import uvicorn
from config import WORKSPACE_PATH
from interfaces.web import WebInterface

# Import core components
from main import init_components

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PenguinWeb")


async def setup():
    """Initialize Penguin components and workspace"""
    try:
        # Initialize core components
        cli = await init_components()

        # Ensure workspace directories exist
        workspace = Path(WORKSPACE_PATH)
        conversations_dir = workspace / "conversations"
        conversations_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Workspace initialized at: {workspace}")
        return cli

    except Exception as e:
        logger.error(f"Setup failed: {str(e)}")
        raise


def main():
    try:
        # Get the CLI instance using asyncio
        cli = asyncio.run(setup())

        # Pass the CLI instance to WebInterface
        interface = WebInterface(cli)

        # Configure and run uvicorn
        config = uvicorn.Config(
            interface.app, host="0.0.0.0", port=8000, log_level="info", reload=True
        )

        server = uvicorn.Server(config)
        server.run()

    except Exception as e:
        logger.error(f"Server failed to start: {str(e)}")
        raise


if __name__ == "__main__":
    main()
