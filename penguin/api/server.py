from pathlib import Path
import os
import logging

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from penguin.config import config, Config

# Use absolute imports
from penguin.core import PenguinCore
from penguin.llm.api_client import APIClient
from penguin.llm.model_config import ModelConfig
from penguin.system_prompt import SYSTEM_PROMPT
from penguin.tools import ToolManager
from penguin.utils.log_error import log_error

from .routes import router

logger = logging.getLogger(__name__)

# Initialize core components
def init_core():
    try:
        # Create a proper Config object instead of using the raw dictionary
        config_obj = Config.load_config()
        model_config = config_obj.model_config

        api_client = APIClient(model_config=model_config)
        api_client.set_system_prompt(SYSTEM_PROMPT)
        # Use a dict derived from the live Config object
        config_dict = config_obj.to_dict() if hasattr(config_obj, 'to_dict') else {}
        tool_manager = ToolManager(config_dict, log_error)

        # Pass the proper Config object, not the raw dictionary
        core = PenguinCore(
            config=config_obj,
            api_client=api_client, 
            tool_manager=tool_manager, 
            model_config=model_config
        )
        
        # Initialize core systems
        return core
        
    except Exception as e:
        logger.error(f"Failed to initialize core: {str(e)}")
        raise


def create_app():
    app = FastAPI(title="Penguin AI", docs_url="/api/docs", redoc_url="/api/redoc")

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Allows all origins
        allow_credentials=True,
        allow_methods=["*"],  # Allows all methods
        allow_headers=["*"],  # Allows all headers
    )

    # Initialize core and attach to router
    core = init_core()
    router.core = core

    # Include routes
    app.include_router(router)

    # Mount static files if they exist
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
        
        @app.get("/")
        async def read_root():
            index_path = static_dir / "index.html"
            if index_path.exists():
                return FileResponse(str(index_path))
            return {"message": "Penguin API is running. Web UI not found."}
    else:
        @app.get("/")
        async def api_root():
            return {
                "name": "Penguin AI API",
                "version": "0.1.0",
                "status": "running",
                "endpoints": {
                    "docs": "/api/docs",
                    "chat": "/api/v1/chat/message",
                    "conversations": "/api/v1/conversations",
                }
            }

    return app


def main():
    """Entry point for the web server"""
    app = create_app()
    print("\n\033[96m=== Penguin AI Server ===\033[0m")
    print("\033[96mVisit http://localhost:8000 to start using Penguin!\033[0m")
    print("\033[96mAPI documentation: http://localhost:8000/api/docs\033[0m\n")
    
    # Get port from environment or use default
    port = int(os.environ.get("PORT", 8000))
    
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
