from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, WebSocket, HTTPException # type: ignore
from pydantic import BaseModel # type: ignore
from dataclasses import asdict # type: ignore
from datetime import datetime # type: ignore

from penguin.core import PenguinCore
from penguin.system.conversation import ConversationLoader, ConversationMetadata


class MessageRequest(BaseModel):
    text: str
    conversation_id: Optional[str] = None
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
    """Process a chat message, with optional conversation support."""
    # Convert the message to the format expected by core.process
    input_data = {"text": request.text}
    process_result = await core.process(
        input_data=input_data,
        context=request.context,
        conversation_id=request.conversation_id
    )
    
    # The frontend expects a "response" field, but core.process returns "assistant_response"
    # We need to rename the field to match what the frontend expects
    return {"response": process_result.get("assistant_response", "")}


@router.post("/api/v1/projects/create")
async def create_project(
    request: ProjectRequest, core: PenguinCore = Depends(get_core)
):
    """Create a new project."""
    response = core.project_manager.create_project(request.name, request.description)
    return response


@router.post("/api/v1/tasks/execute")
async def execute_task(request: TaskRequest, core: PenguinCore = Depends(get_core)):
    """Execute a task."""
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
    """Real-time chat interface."""
    await websocket.accept()
    while True:
        try:
            data = await websocket.receive_json()
            response = await core.process(data["text"])
            await websocket.send_json({"response": response})
        except Exception as e:
            await websocket.send_json({"error": str(e)})


@router.get("/api/v1/conversations")
async def list_conversations():
    """List all available conversations."""
    try:
        loader = ConversationLoader()
        conversations = loader.list_conversations()
        conv_data = [asdict(conv) for conv in conversations]
        return {"conversations": conv_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving conversations: {str(e)}")


@router.get("/api/v1/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    """Retrieve conversation details by ID."""
    try:
        loader = ConversationLoader()
        messages, metadata = loader.load_conversation(conversation_id)
        return {"metadata": asdict(metadata), "messages": messages}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error loading conversation {conversation_id}: {str(e)}",
        )


@router.post("/api/v1/conversations/create")
async def create_conversation():
    """Create a new conversation."""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        conversation_id = f"conversation_{timestamp}"
        
        # Initialize with welcome message
        messages = [{
            "role": "system",
            "content": "Welcome to Penguin AI! How can I help you today?",
            "timestamp": datetime.now().isoformat()
        }]
        
        # Create metadata
        metadata = ConversationMetadata(
            created_at=datetime.now().isoformat(),
            last_active=datetime.now().isoformat(),
            message_count=1,
            session_id=conversation_id
        )
        
        # Save initial conversation state
        loader = ConversationLoader()
        loader.save_conversation(conversation_id, messages, metadata)
        
        return {"conversation_id": conversation_id}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error creating conversation: {str(e)}"
        )
