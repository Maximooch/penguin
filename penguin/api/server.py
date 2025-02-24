from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from penguin.config import config

# Use absolute imports
from penguin.core import PenguinCore
from penguin.llm.api_client import APIClient
from penguin.llm.model_config import ModelConfig
from penguin.system_prompt import SYSTEM_PROMPT
from penguin.tools import ToolManager
from penguin.utils.log_error import log_error

from .routes import router


# Initialize core components
def init_core():
    model_config = ModelConfig(
        model=config["model"]["default"],
        provider=config["model"]["provider"],
        api_base=config["api"]["base_url"],
    )

    api_client = APIClient(model_config=model_config)
    api_client.set_system_prompt(SYSTEM_PROMPT)
    tool_manager = ToolManager(log_error)

    return PenguinCore(api_client=api_client, tool_manager=tool_manager)


def create_app():
    app = FastAPI(title="Penguin AI")

    # Initialize core and attach to router
    core = init_core()
    router.core = core

    # Include routes
    app.include_router(router)

    # Mount static files
    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/")
    async def read_root():
        return FileResponse(str(static_dir / "index.html"))

    return app


def main():
    """Entry point for the web server"""
    app = create_app()
    print("\n\033[96m=== Penguin AI Server ===\033[0m")
    print("\033[96mVisit http://localhost:8000 to start using Penguin!\033[0m\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
