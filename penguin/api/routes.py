from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks, UploadFile, File, Form # type: ignore
from pydantic import BaseModel # type: ignore
from dataclasses import asdict # type: ignore
from datetime import datetime # type: ignore
import asyncio
import logging
import os
from pathlib import Path
import shutil
import uuid

from penguin.config import WORKSPACE_PATH
from penguin.core import PenguinCore

logger = logging.getLogger(__name__)

class MessageRequest(BaseModel):
    text: str
    conversation_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    context_files: Optional[List[str]] = None
    streaming: Optional[bool] = True
    max_iterations: Optional[int] = 5
    image_path: Optional[str] = None

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
        input_data = {
            "text": request.text
        }
        
        # Add image path if provided
        if request.image_path:
            input_data["image_path"] = request.image_path
        
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
        token_callbacks = getattr(core, "token_callbacks", [])
        if hasattr(core, "token_callbacks") and stream_callback not in token_callbacks:
            core.token_callbacks.append(token_callback)
        
        while True:
            data = await websocket.receive_json()
            
            # Extract parameters from websocket message
            text = data.get("text", "")
            conversation_id = data.get("conversation_id")
            context_files = data.get("context_files")
            context = data.get("context")
            max_iterations = data.get("max_iterations", 5)
            image_path = data.get("image_path")
            
            # Prepare input data
            input_data = {"text": text}
            if image_path:
                input_data["image_path"] = image_path
            
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
            
            # Register progress callback for multi-step processing
            def progress_callback(iteration, max_iter, message=None):
                asyncio.create_task(
                    websocket.send_json({
                        "event": "progress", 
                        "data": {
                            "iteration": iteration,
                            "max_iterations": max_iter,
                            "message": message
                        }
                    })
                )
            
            try:
                # Register progress callback if core supports it
                if hasattr(core, "register_progress_callback"):
                    core.register_progress_callback(progress_callback)
                
                # Process with streaming enabled
                await websocket.send_json({"event": "start", "data": {}})
                
                process_result = await core.process(
                    input_data=input_data,
                    conversation_id=conversation_id,
                    max_iterations=max_iterations,
                    context_files=context_files,
                    context=context,
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
                    
                # Remove progress callback
                if hasattr(core, "progress_callbacks"):
                    if progress_callback in core.progress_callbacks:
                        core.progress_callbacks.remove(progress_callback)
                    
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
async def list_conversations(core: PenguinCore = Depends(get_core)):
    """List all available conversations."""
    try:
        conversations = core.list_conversations()
        return {"conversations": conversations}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving conversations: {str(e)}")


@router.get("/api/v1/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, core: PenguinCore = Depends(get_core)):
    """Retrieve conversation details by ID."""
    try:
        conversation = core.get_conversation(conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail=f"Conversation {conversation_id} not found")
        return conversation
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error loading conversation {conversation_id}: {str(e)}",
        )


@router.post("/api/v1/conversations/create")
async def create_conversation(core: PenguinCore = Depends(get_core)):
    """Create a new conversation."""
    try:
        conversation_id = core.create_conversation()
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
        # Check if core has conversation_manager attribute (new style)
        if hasattr(core, "conversation_manager"):
            success = core.conversation_manager.load_context_file(request.file_path)
        # Check if core has conversation_system attribute (old style)
        elif hasattr(core, "conversation_system"):
            success = core.conversation_system.load_context_file(request.file_path)
        else:
            raise HTTPException(
                status_code=500, 
                detail="No conversation manager found in core"
            )
            
        return {"success": success, "file_path": request.file_path}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error loading context file: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error loading context file: {str(e)}"
        )


@router.post("/api/v1/upload")
async def upload_file(
    file: UploadFile = File(...),
    core: PenguinCore = Depends(get_core)
):
    """Upload a file (primarily images) to be used in conversations."""
    try:
        # Create uploads directory if it doesn't exist
        uploads_dir = Path(WORKSPACE_PATH) / "uploads"
        uploads_dir.mkdir(exist_ok=True)
        
        # Generate a unique filename
        file_extension = file.filename.split('.')[-1] if '.' in file.filename else ''
        unique_filename = f"{uuid.uuid4()}.{file_extension}"
        file_path = uploads_dir / unique_filename
        
        # Save the file
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Return the path that can be referenced in future requests
        return {
            "path": str(file_path),
            "filename": file.filename,
            "content_type": file.content_type
        }
    except Exception as e:
        logger.error(f"Error uploading file: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error uploading file: {str(e)}")


@router.get("/api/v1/capabilities")
async def get_capabilities(core: PenguinCore = Depends(get_core)):
    """Get model capabilities like vision support."""
    try:
        capabilities = {
            "vision_enabled": False,
            "streaming_enabled": True
        }
        
        # Check if the model supports vision
        if hasattr(core, "model_config") and hasattr(core.model_config, "vision_enabled"):
            capabilities["vision_enabled"] = core.model_config.vision_enabled
            
        # Check streaming support
        if hasattr(core, "model_config") and hasattr(core.model_config, "streaming_enabled"):
            capabilities["streaming_enabled"] = core.model_config.streaming_enabled
            
        return capabilities
    except Exception as e:
        logger.error(f"Error getting capabilities: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
