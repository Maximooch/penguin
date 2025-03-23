from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks # type: ignore
from pydantic import BaseModel # type: ignore
from dataclasses import asdict # type: ignore
from datetime import datetime # type: ignore
import asyncio
import logging

from penguin.core import PenguinCore
from penguin.system.conversation import ConversationLoader, ConversationMetadata

logger = logging.getLogger(__name__)

class MessageRequest(BaseModel):
    text: str
    conversation_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    context_files: Optional[List[str]] = None
    streaming: Optional[bool] = None
    max_iterations: Optional[int] = 5

class StreamResponse(BaseModel):
    id: str
    event: str
    data: Dict[str, Any]

class ProjectRequest(BaseModel):
    name: str
    description: Optional[str] = None


class TaskRequest(BaseModel):
    name: str
    description: Optional[str] = None
    continuous: bool = False
    time_limit: Optional[int] = None


class ContextFileRequest(BaseModel):
    file_path: str


router = APIRouter()


async def get_core():
    return router.core


@router.post("/api/v1/chat/message")
async def process_message(
    request: MessageRequest, core: PenguinCore = Depends(get_core)
):
    """Process a chat message, with optional conversation support."""
    try:
        # Create input data dictionary from request
        input_data = {"text": request.text}
        
        # Process the message with all available options
        process_result = await core.process(
            input_data=input_data,
            context=request.context,
            conversation_id=request.conversation_id,
            max_iterations=request.max_iterations or 5,
            context_files=request.context_files,
            streaming=request.streaming
        )
        
        # The frontend expects a "response" field
        return {"response": process_result.get("assistant_response", ""), 
                "action_results": process_result.get("action_results", [])}
    except Exception as e:
        logger.error(f"Error processing message: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/api/v1/chat/stream")
async def stream_chat(
    websocket: WebSocket, core: PenguinCore = Depends(get_core)
):
    """Stream chat responses in real-time."""
    await websocket.accept()
    
    # Define callback for streaming tokens
    async def stream_callback(token: str):
        await websocket.send_json({"event": "token", "data": {"token": token}})
    
    # Define callback for token usage updates
    async def token_callback(usage: Dict[str, int]):
        await websocket.send_json({"event": "tokens", "data": {"usage": usage}})
    
    try:
        # Register callbacks
        core.register_token_callback(token_callback)
        
        while True:
            data = await websocket.receive_json()
            
            # Extract parameters from websocket message
            text = data.get("text", "")
            conversation_id = data.get("conversation_id")
            context_files = data.get("context_files")
            max_iterations = data.get("max_iterations", 5)
            
            # Enable streaming for this particular request
            if hasattr(core, "model_config"):
                original_streaming = getattr(core.model_config, "streaming_enabled", False)
                core.model_config.streaming_enabled = True
            
            # Set stream callback temporarily
            stream_cb_attr = None
            if hasattr(core, "api_client") and hasattr(core.api_client, "stream_callback"):
                stream_cb_attr = "api_client.stream_callback"
                original_callback = core.api_client.stream_callback
                core.api_client.stream_callback = stream_callback
            
            try:
                # Process with streaming enabled
                input_data = {"text": text}
                await websocket.send_json({"event": "start", "data": {}})
                
                process_result = await core.process(
                    input_data=input_data,
                    conversation_id=conversation_id,
                    max_iterations=max_iterations,
                    context_files=context_files,
                    streaming=True
                )
                
                # Send final complete response
                await websocket.send_json({
                    "event": "complete", 
                    "data": {
                        "response": process_result.get("assistant_response", ""),
                        "action_results": process_result.get("action_results", [])
                    }
                })
                
            finally:
                # Restore original streaming setting
                if hasattr(core, "model_config"):
                    core.model_config.streaming_enabled = original_streaming
                
                # Restore original callback if modified
                if stream_cb_attr and hasattr(core, "api_client"):
                    core.api_client.stream_callback = original_callback
                    
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"Error in websocket: {str(e)}")
        await websocket.send_json({"event": "error", "data": {"message": str(e)}})


@router.post("/api/v1/projects/create")
async def create_project(
    request: ProjectRequest, core: PenguinCore = Depends(get_core)
):
    """Create a new project."""
    response = core.project_manager.create_project(request.name, request.description)
    return response


@router.post("/api/v1/tasks/execute")
async def execute_task(
    request: TaskRequest, 
    background_tasks: BackgroundTasks,
    core: PenguinCore = Depends(get_core)
):
    """Execute a task in the background."""
    # Use background tasks to execute long-running tasks
    background_tasks.add_task(
        core.start_run_mode,
        name=request.name,
        description=request.description,
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


@router.get("/api/v1/token-usage")
async def get_token_usage(core: PenguinCore = Depends(get_core)):
    """Get current token usage statistics."""
    return {"usage": core.get_token_usage()}


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


@router.get("/api/v1/context-files")
async def list_context_files(core: PenguinCore = Depends(get_core)):
    """List all available context files."""
    try:
        files = core.list_context_files()
        return {"files": files}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error listing context files: {str(e)}"
        )


@router.post("/api/v1/context-files/load")
async def load_context_file(
    request: ContextFileRequest, 
    core: PenguinCore = Depends(get_core)
):
    """Load a context file into the current conversation."""
    try:
        success = core.conversation_system.load_context_file(request.file_path)
        return {"success": success, "file_path": request.file_path}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error loading context file: {str(e)}"
        )
