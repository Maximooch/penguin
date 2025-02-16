import logging
from typing import Any, Dict, Optional

from config import Config
from core import PenguinCore
from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from llm import APIClient
from pydantic import BaseModel
from tools import ToolManager

app = FastAPI(title="Penguin AI Web API")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize core components
config = Config.load_config()
api_client = APIClient()
tool_manager = ToolManager()
penguin = PenguinCore(config=config, api_client=api_client, tool_manager=tool_manager)


class Message(BaseModel):
    content: str
    context: Optional[Dict[str, Any]] = None


@app.post("/chat")
async def chat(message: Message):
    """Process a chat message and return the response"""
    try:
        response = await penguin.process_message(
            message=message.content, context=message.context
        )
        return {"response": response}
    except Exception as e:
        logging.error(f"Error processing message: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Handle real-time chat via WebSocket"""
    await websocket.accept()
    try:
        while True:
            # Receive message
            data = await websocket.receive_json()

            # Process message
            response = await penguin.process_message(
                message=data["content"], context=data.get("context")
            )

            # Send response
            await websocket.send_json({"response": response})

    except Exception as e:
        logging.error(f"WebSocket error: {str(e)}")
        await websocket.close()


@app.post("/task/create")
async def create_task(name: str, description: str):
    """Create a new task"""
    try:
        result = await penguin.create_task(name, description)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/projects")
async def list_projects():
    """List all projects"""
    try:
        output = await penguin.display_all()
        return {"projects": output}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
