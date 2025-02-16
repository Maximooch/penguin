from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, WebSocket  # type: ignore
from pydantic import BaseModel

from penguin.core import PenguinCore


class MessageRequest(BaseModel):
    text: str
    context: Optional[Dict[str, Any]] = None


class ProjectRequest(BaseModel):
    name: str
    description: Optional[str] = None


class TaskRequest(BaseModel):
    name: str
    description: Optional[str] = None
    continuous: bool = False
    time_limit: Optional[int] = None


router = APIRouter()


async def get_core():
    return router.core


@router.post("/api/v1/chat/message")
async def process_message(
    request: MessageRequest, core: PenguinCore = Depends(get_core)
):
    """Process a chat message"""
    response = await core.process(request.text, request.context)
    return {"response": response}


@router.post("/api/v1/projects/create")
async def create_project(
    request: ProjectRequest, core: PenguinCore = Depends(get_core)
):
    """Create a new project"""
    response = core.project_manager.create_project(request.name, request.description)
    return response


@router.post("/api/v1/tasks/execute")
async def execute_task(request: TaskRequest, core: PenguinCore = Depends(get_core)):
    """Execute a task"""
    await core.start_run_mode(
        request.name,
        request.description,
        continuous=request.continuous,
        time_limit=request.time_limit,
    )
    return {"status": "started"}


@router.websocket("/ws/chat")
async def websocket_endpoint(
    websocket: WebSocket, core: PenguinCore = Depends(get_core)
):
    """Real-time chat interface"""
    await websocket.accept()
    while True:
        try:
            data = await websocket.receive_json()
            response = await core.process(data["text"])
            await websocket.send_json({"response": response})
        except Exception as e:
            await websocket.send_json({"error": str(e)})
