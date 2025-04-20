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
import websockets

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
async def handle_chat_message(
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
    """Stream chat responses in real-time using a queue."""
    await websocket.accept()
    response_queue = asyncio.Queue()
    sender_task = None

    # Task to send messages from the queue to the client
    async def sender(queue: asyncio.Queue):
        nonlocal sender_task
        send_buffer = ""
        BUFFER_SEND_SIZE = 5 # Send after accumulating this many chars
        BUFFER_TIMEOUT = 0.1 # Or send after this many seconds of inactivity

        while True:
            token = None
            try:
                # Wait for a token with a timeout
                token = await asyncio.wait_for(queue.get(), timeout=BUFFER_TIMEOUT)

                if token is None: # Sentinel value to stop
                    logger.debug("[Sender Task] Received stop signal.")
                    # Send any remaining buffer before stopping
                    if send_buffer:
                        logger.debug(f"[Sender Task] Sending final buffer: '{send_buffer}'")
                        await websocket.send_json({"event": "token", "data": {"token": send_buffer}})
                        send_buffer = ""
                    queue.task_done()
                    break

                # Add token to buffer
                send_buffer += token
                queue.task_done()
                logger.debug(f"[Sender Task] Added to buffer: '{token}'. Buffer size: {len(send_buffer)}")

                # Send buffer if it reaches size threshold
                if len(send_buffer) >= BUFFER_SEND_SIZE:
                    logger.debug(f"[Sender Task] Buffer reached size {BUFFER_SEND_SIZE}. Sending: '{send_buffer}'")
                    await websocket.send_json({"event": "token", "data": {"token": send_buffer}})
                    send_buffer = "" # Reset buffer

            except asyncio.TimeoutError:
                # Timeout occurred - send buffer if it has content
                if send_buffer:
                    logger.debug(f"[Sender Task] Timeout reached. Sending buffer: '{send_buffer}'")
                    await websocket.send_json({"event": "token", "data": {"token": send_buffer}})
                    send_buffer = ""
                # Continue waiting for next token or stop signal
                continue

            except websockets.exceptions.ConnectionClosed:
                logger.warning("[Sender Task] WebSocket closed while sending/waiting.")
                break # Exit if connection is closed
            except Exception as e:
                logger.error(f"[Sender Task] Error: {e}", exc_info=True)
                break

        logger.info("[Sender Task] Exiting.")

    # Define callback for streaming tokens - this will ONLY put tokens on the queue
    async def stream_callback(token: str):
        try:
            logger.debug(f"[stream_callback] Putting token on queue: '{token}'")
            await response_queue.put(token)
        except Exception as e:
            # Log error putting onto queue, but don't stop the main process
            logger.error(f"[stream_callback] Error putting token on queue: {e}", exc_info=True)

    try:
        # Start the sender task
        sender_task = asyncio.create_task(sender(response_queue))
        logger.info("Sender task started.")

        while True: # Keep handling incoming client messages
            data = await websocket.receive_json() # Wait for a request from client
            logger.info(f"Received request from client: {data.get('text', '')[:50]}...")

            # Extract parameters
            text = data.get("text", "")
            conversation_id = data.get("conversation_id")
            context_files = data.get("context_files")
            context = data.get("context")
            max_iterations = data.get("max_iterations", 5)
            image_path = data.get("image_path")

            input_data = {"text": text}
            if image_path:
                input_data["image_path"] = image_path

            # Progress callback setup (no changes needed here)
            progress_callback_task = None
            async def progress_callback(iteration, max_iter, message=None):
                nonlocal progress_callback_task
                progress_callback_task = asyncio.create_task(
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
                    await progress_callback_task
                except asyncio.CancelledError:
                    logger.debug("Progress callback task cancelled")
                except Exception as e:
                    logger.error(f"Error sending progress update: {e}")

            process_task = None
            try:
                if hasattr(core, "register_progress_callback"):
                    core.register_progress_callback(progress_callback)

                await websocket.send_json({"event": "start", "data": {}}) # Signal start to client
                logger.info("Sent 'start' event to client.")

                # Run core.process as a task - NOTE: We don't await the *result* here immediately
                # The stream_callback puts tokens on the queue for the sender_task
                logger.info("Starting core.process...")
                process_task = asyncio.create_task(core.process(
                    input_data=input_data,
                    conversation_id=conversation_id,
                    max_iterations=max_iterations,
                    context_files=context_files,
                    context=context,
                    streaming=True,
                    stream_callback=stream_callback
                ))

                # Wait for the core process to finish
                process_result = await process_task
                logger.info(f"core.process finished. Result keys: {list(process_result.keys())}")

                # Signal sender task to finish *after* core.process is done
                logger.debug("Putting stop signal (None) on queue for sender task.")
                await response_queue.put(None)

                # Wait for sender task to process remaining items and finish
                # Add a timeout to prevent hanging indefinitely
                try:
                    logger.debug("Waiting for sender task to finish...")
                    await asyncio.wait_for(sender_task, timeout=10.0) # Wait max 10s for sender
                    logger.info("Sender task finished cleanly.")
                except asyncio.TimeoutError:
                    logger.warning("Sender task timed out after core.process completed. Cancelling.")
                    if sender_task and not sender_task.done():
                        sender_task.cancel()
                except Exception as e:
                    logger.error(f"Error waiting for sender task: {e}", exc_info=True)
                    if sender_task and not sender_task.done():
                        sender_task.cancel()

                # Send final complete message AFTER sender is done
                logger.info("Sending 'complete' event to client.")
                await websocket.send_json({
                    "event": "complete",
                    "data": {
                        "response": process_result.get("assistant_response", ""),
                        "action_results": process_result.get("action_results", [])
                    }
                })
                logger.info("Sent 'complete' event to client.")

            except Exception as process_err:
                logger.error(f"Error during message processing: {process_err}", exc_info=True)
                # Try to send error to client if possible
                if websocket.client_state == websocket.client_state.CONNECTED:
                    await websocket.send_json({"event": "error", "data": {"message": str(process_err)}})
                # Ensure tasks are cancelled on error
                if process_task and not process_task.done(): process_task.cancel()
                if sender_task and not sender_task.done(): sender_task.cancel()
                break # Exit loop on processing error
            finally:
                # Clean up progress callback
                if hasattr(core, "progress_callbacks") and progress_callback in core.progress_callbacks:
                    core.progress_callbacks.remove(progress_callback)
                # Ensure tasks are awaited/cancelled if they are still running (e.g., due to early exit)
                if process_task and not process_task.done(): process_task.cancel()
                if sender_task and not sender_task.done(): sender_task.cancel()
                # Wait briefly for tasks to cancel
                await asyncio.sleep(0.1)

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"Unhandled error in websocket handler: {str(e)}", exc_info=True)
    finally:
        logger.info("Cleaning up stream_chat handler.")
        # Ensure sender task is cancelled if connection closes unexpectedly
        if sender_task and not sender_task.done():
            logger.info("Cancelling sender task due to handler exit.")
            sender_task.cancel()
            try:
                await sender_task # Allow cancellation to propagate
            except asyncio.CancelledError:
                logger.debug("Sender task cancellation confirmed.")
            except Exception as final_cancel_err:
                logger.error(f"Error during final sender task cancellation: {final_cancel_err}")


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
        core.start_run_mode, # This now accepts the callback
        name=request.name,
        description=request.description,
        continuous=request.continuous,
        time_limit=request.time_limit,
        stream_event_callback=None # Pass None for the non-streaming endpoint
    )
    return {"status": "started"}


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
        # Use the ConversationManager directly
        if hasattr(core, "conversation_manager"):
            success = core.conversation_manager.load_context_file(request.file_path)
        # Removed the fallback check for core.conversation_system
        else:
            raise HTTPException(
                status_code=500,
                detail="Conversation manager not found in core. Initialization might have failed."
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


# --- New WebSocket Endpoint for Run Mode Streaming ---
@router.websocket("/api/v1/tasks/stream")
async def stream_task(
    websocket: WebSocket,
    core: PenguinCore = Depends(get_core)
):
    """Stream run mode task execution events in real-time."""
    await websocket.accept()
    task_execution = None
    run_mode_callback_task = None

    # Define the callback function to send events over WebSocket
    async def run_mode_event_callback(event_type: str, data: Dict[str, Any]):
        nonlocal run_mode_callback_task
        # Ensure this runs as a task to avoid blocking RunMode
        run_mode_callback_task = asyncio.create_task(
            websocket.send_json({"event": event_type, "data": data})
        )
        try:
            await run_mode_callback_task
        except asyncio.CancelledError:
            logger.debug(f"Run mode callback send task cancelled for event: {event_type}")
        except Exception as e:
            logger.error(f"Error sending run mode event '{event_type}' via WebSocket: {e}")
            # Optionally try to close WebSocket on send error
            # await websocket.close(code=1011) # Internal error

    try:
        while True: # Keep connection open to handle potential multiple task requests?
            # Or expect one task request per connection?
            # Let's assume one task per connection for simplicity now.
            data = await websocket.receive_json()
            logger.info(f"Received run mode request: {data}")

            # Extract task parameters from the received data
            name = data.get("name")
            description = data.get("description")
            continuous = data.get("continuous", False)
            time_limit = data.get("time_limit")
            context = data.get("context") # Allow passing context

            if not name:
                await websocket.send_json({"event": "error", "data": {"message": "Task name is required."}})
                await websocket.close(code=1008) # Policy violation
                return # Exit after closing

            # Start the run mode task in the background using core.start_run_mode
            # Pass the WebSocket callback function
            logger.info(f"Starting streaming run mode for task: {name}")
            task_execution = asyncio.create_task(
                core.start_run_mode(
                    name=name,
                    description=description,
                    continuous=continuous,
                    time_limit=time_limit,
                    context=context,
                    stream_event_callback=run_mode_event_callback
                )
            )

            # Wait for the task execution to complete or error out
            try:
                await task_execution
                logger.info(f"Run mode task '{name}' execution finished.")
                # The 'complete' or 'error' event should be sent by RunMode itself
                # via the callback before the task finishes.
            except Exception as task_err:
                logger.error(f"Error during run mode task '{name}' execution: {task_err}", exc_info=True)
                # Send error via websocket if possible
                if websocket.client_state == websocket.client_state.CONNECTED:
                     await websocket.send_json({"event": "error", "data": {"message": f"Task execution failed: {task_err}"}})

            # Once the task is done (completed, errored, interrupted), we can break the loop
            # Assuming one task per connection.
            break

    except WebSocketDisconnect:
        logger.info("Run mode WebSocket client disconnected")
        # If client disconnects, we should try to interrupt the running task
        if task_execution and not task_execution.done():
            logger.warning(f"Client disconnected, attempting to interrupt task execution...")
            # Need a way to signal interruption to RunMode/Core gracefully.
            # For now, just cancel the asyncio task.
            task_execution.cancel()
    except Exception as e:
        logger.error(f"Unhandled error in stream_task handler: {e}", exc_info=True)
        # Try to send error to client if connection is still open
        if websocket.client_state == websocket.client_state.CONNECTED:
            try:
                await websocket.send_json({"event": "error", "data": {"message": f"Server error: {e}"}})
            except Exception as send_err:
                logger.error(f"Failed to send final error to client: {send_err}")
    finally:
        logger.info("Cleaning up stream_task handler.")
        # Ensure the task is cancelled if the handler exits unexpectedly
        if task_execution and not task_execution.done():
            logger.info("Cancelling run mode task due to handler exit.")
            task_execution.cancel()
            try:
                await task_execution # Allow cancellation to propagate
            except asyncio.CancelledError:
                logger.debug("Run mode task cancellation confirmed.")
            except Exception as final_cancel_err:
                logger.error(f"Error during final task cancellation: {final_cancel_err}")
        # Close WebSocket connection if it's still open
        if websocket.client_state == websocket.client_state.CONNECTED:
             await websocket.close()

# --- End New WebSocket Endpoint ---
