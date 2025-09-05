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
import httpx

from penguin.config import WORKSPACE_PATH
from penguin.core import PenguinCore
from penguin.utils.events import EventBus

logger = logging.getLogger(__name__)

class MessageRequest(BaseModel):
    text: str
    conversation_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    context_files: Optional[List[str]] = None
    streaming: Optional[bool] = True
    max_iterations: Optional[int] = 5
    image_path: Optional[str] = None
    include_reasoning: Optional[bool] = False

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


# New models for checkpoint management
class CheckpointCreateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class CheckpointBranchRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


# New models for model management
class ModelLoadRequest(BaseModel):
    model_id: str


# Memory API models
class MemoryStoreRequest(BaseModel):
    content: str
    metadata: Optional[Dict[str, Any]] = None
    categories: Optional[List[str]] = None

class MemorySearchRequest(BaseModel):
    query: str
    max_results: Optional[int] = 5
    memory_type: Optional[str] = None
    categories: Optional[List[str]] = None


router = APIRouter()


async def get_core():
    return router.core

def _get_coordinator(core: PenguinCore):
    try:
        return core.get_coordinator()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Coordinator not available: {e}")

def _validate_agent_id(agent_id: str) -> None:
    if not agent_id or len(agent_id) > 32:
        raise HTTPException(status_code=400, detail="agent_id must be 1-32 chars")
    import re
    if not re.fullmatch(r"[A-Za-z0-9_-]+", agent_id):
        raise HTTPException(status_code=400, detail="agent_id must be alphanumeric, dash or underscore")

class AgentCreate(BaseModel):
    agent_id: str
    role: str
    system_prompt: Optional[str] = None
    model_max_tokens: Optional[int] = None
    activate: bool = False

class AgentRegister(BaseModel):
    role: str

class ToAgentRequest(BaseModel):
    agent_id: str
    content: Any
    message_type: Optional[str] = "message"
    metadata: Optional[Dict[str, Any]] = None

class ToHumanRequest(BaseModel):
    content: Any
    message_type: Optional[str] = "status"
    metadata: Optional[Dict[str, Any]] = None

class HumanReplyRequest(BaseModel):
    agent_id: str
    content: Any
    message_type: Optional[str] = "message"

class CoordRoleSend(BaseModel):
    role: str
    content: Any
    message_type: Optional[str] = "message"

class CoordBroadcast(BaseModel):
    roles: List[str]
    content: Any
    message_type: Optional[str] = "message"

class CoordRRWorkflow(BaseModel):
    role: str
    prompts: List[str]

class CoordRoleChain(BaseModel):
    roles: List[str]
    content: Any

@router.websocket("/api/v1/events/ws")
async def events_ws(websocket: WebSocket, core: PenguinCore = Depends(get_core)):
    """WebSocket stream forwarding bus.message and UI message events with filters.

    Query params:
      - agent_id: filter by agent id (optional)
      - message_type: filter by message_type (message|action|status)
      - include_ui: 'true'|'false' (default 'true')
      - include_bus: 'true'|'false' (default 'true')
    """
    await websocket.accept()
    params = websocket.query_params
    agent_filter = params.get("agent_id")
    type_filter = params.get("message_type")
    include_ui = (params.get("include_ui", "true").lower() != "false")
    include_bus = (params.get("include_bus", "true").lower() != "false")

    event_bus = EventBus.get_instance()
    handlers = []

    async def _send(event: str, payload: Dict[str, Any]):
        try:
            a_id = payload.get("agent_id") or payload.get("sender")
            m_type = payload.get("message_type") or payload.get("type")
            if agent_filter and a_id != agent_filter:
                return
            if type_filter and m_type != type_filter:
                return
            await websocket.send_json({"event": event, "data": payload})
        except Exception as e:
            # Client closed or other transient error
            return

    # EventBus: bus.message
    async def _on_bus_message(data):
        if not include_bus:
            return
        try:
            if isinstance(data, dict):
                payload = dict(data)
                if "agent_id" not in payload and "sender" in payload:
                    payload["agent_id"] = payload.get("sender")
                await _send("bus.message", payload)
        except Exception:
            pass

    event_bus.subscribe("bus.message", _on_bus_message)
    handlers.append(("bus.message", _on_bus_message))

    # Core UI events
    async def _on_ui_event(event_type: str, data: Dict[str, Any]):
        if not include_ui:
            return
        try:
            if event_type in {"message", "stream_chunk", "human_message"}:
                payload = dict(data or {})
                payload.setdefault("agent_id", getattr(core.conversation_manager, "current_agent_id", None))
                payload.setdefault("message_type", "message")
                await _send(event_type, payload)
        except Exception:
            pass

    core.register_ui(_on_ui_event)

    try:
        while True:
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        pass
    finally:
        core.unregister_ui(_on_ui_event)
        for ev, h in handlers:
            try:
                event_bus.unsubscribe(ev, h)
            except Exception:
                pass

@router.get("/api/v1/agents")
async def list_agents(core: PenguinCore = Depends(get_core)):
    """List registered agents including current conversation ids."""
    try:
        cm = core.conversation_manager
        agents = []
        agent_sessions = getattr(cm, 'agent_sessions', {}) or {}
        for aid, conv in agent_sessions.items():
            try:
                agents.append({
                    "agent_id": aid,
                    "conversation_id": getattr(conv.session, 'id', None),
                })
            except Exception:
                continue
        return {"agents": agents}
    except Exception as e:
        logger.error(f"list_agents error: {e}")
        raise HTTPException(status_code=500, detail="Failed to list agents")

@router.post("/api/v1/agents")
async def create_agent(req: AgentCreate, core: PenguinCore = Depends(get_core)):
    _validate_agent_id(req.agent_id)
    try:
        coord = _get_coordinator(core)
        await coord.spawn_agent(
            req.agent_id,
            role=req.role,
            system_prompt=req.system_prompt,
            model_max_tokens=req.model_max_tokens,
            activate=req.activate,
        )
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"create_agent error: {e}")
        raise HTTPException(status_code=500, detail="Failed to create agent")

@router.delete("/api/v1/agents/{agent_id}")
async def delete_agent(agent_id: str, core: PenguinCore = Depends(get_core)):
    _validate_agent_id(agent_id)
    try:
        coord = _get_coordinator(core)
        await coord.destroy_agent(agent_id)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"delete_agent error: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete agent")

@router.post("/api/v1/agents/{agent_id}/register")
async def register_agent(agent_id: str, req: AgentRegister, core: PenguinCore = Depends(get_core)):
    _validate_agent_id(agent_id)
    try:
        coord = _get_coordinator(core)
        coord.register_existing(agent_id, role=req.role)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"register_agent error: {e}")
        raise HTTPException(status_code=500, detail="Failed to register agent")

@router.post("/api/v1/messages/to-agent")
async def api_to_agent(req: ToAgentRequest, core: PenguinCore = Depends(get_core)):
    _validate_agent_id(req.agent_id)
    try:
        ok = await core.send_to_agent(req.agent_id, req.content, message_type=req.message_type or "message", metadata=req.metadata)
        return {"ok": ok}
    except Exception as e:
        logger.error(f"to-agent error: {e}")
        raise HTTPException(status_code=500, detail="Failed to send to agent")

@router.post("/api/v1/messages/to-human")
async def api_to_human(req: ToHumanRequest, core: PenguinCore = Depends(get_core)):
    try:
        ok = await core.send_to_human(req.content, message_type=req.message_type or "status", metadata=req.metadata)
        return {"ok": ok}
    except Exception as e:
        logger.error(f"to-human error: {e}")
        raise HTTPException(status_code=500, detail="Failed to send to human")

@router.post("/api/v1/messages/human-reply")
async def api_human_reply(req: HumanReplyRequest, core: PenguinCore = Depends(get_core)):
    _validate_agent_id(req.agent_id)
    try:
        ok = await core.human_reply(req.agent_id, req.content, message_type=req.message_type or "message")
        return {"ok": ok}
    except Exception as e:
        logger.error(f"human-reply error: {e}")
        raise HTTPException(status_code=500, detail="Failed to send human reply")

@router.post("/api/v1/coord/send-role")
async def api_coord_send_role(req: CoordRoleSend, core: PenguinCore = Depends(get_core)):
    try:
        coord = _get_coordinator(core)
        target = await coord.send_to_role(req.role, req.content, message_type=req.message_type or "message")
        return {"ok": True, "target": target}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"coord send-role error: {e}")
        raise HTTPException(status_code=500, detail="Failed to send to role")

@router.post("/api/v1/coord/broadcast")
async def api_coord_broadcast(req: CoordBroadcast, core: PenguinCore = Depends(get_core)):
    try:
        coord = _get_coordinator(core)
        sent = await coord.broadcast(req.roles, req.content, message_type=req.message_type or "message")
        return {"ok": True, "sent": sent}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"coord broadcast error: {e}")
        raise HTTPException(status_code=500, detail="Failed to broadcast")

@router.post("/api/v1/coord/rr-workflow")
async def api_coord_rr(req: CoordRRWorkflow, core: PenguinCore = Depends(get_core)):
    try:
        coord = _get_coordinator(core)
        await coord.simple_round_robin_workflow(req.prompts, role=req.role)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"coord rr-workflow error: {e}")
        raise HTTPException(status_code=500, detail="Failed rr-workflow")

@router.post("/api/v1/coord/role-chain")
async def api_coord_role_chain(req: CoordRoleChain, core: PenguinCore = Depends(get_core)):
    try:
        coord = _get_coordinator(core)
        await coord.role_chain_workflow(req.content, roles=req.roles)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"coord role-chain error: {e}")
        raise HTTPException(status_code=500, detail="Failed role-chain")


@router.get("/api/v1/health")
async def health():
    """Basic health probe."""
    return {"status": "healthy"}


@router.get("/api/v1/system-info")
async def system_info(core: PenguinCore = Depends(get_core)):
    """Return core system information."""
    try:
        return core.get_system_info()
    except Exception as e:
        logger.error(f"system-info error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/models")
async def list_models(core: PenguinCore = Depends(get_core)):
    """List available models with metadata.

    If no explicit model_configs are present, include at least the current model
    so clients can always see and select something.
    """
    try:
        raw_models = core.list_available_models() if hasattr(core, "list_available_models") else []
        models_list: List[Dict[str, Any]] = list(raw_models or [])

        if not models_list:
            # Fallback: expose the current model so the list is never empty
            cur = core.get_current_model() if hasattr(core, "get_current_model") else None
            if isinstance(cur, dict) and cur.get("model"):
                models_list.append({
                    "id": cur.get("model"),
                    "name": cur.get("model"),
                    "provider": cur.get("provider"),
                    "client_preference": cur.get("client_preference"),
                    "max_tokens": cur.get("max_tokens"),
                    "temperature": cur.get("temperature"),
                    "vision_enabled": cur.get("vision_enabled", False),
                    "current": True,
                })

        return {"models": models_list}
    except Exception as e:
        logger.error(f"Error listing models: {e}")
        raise HTTPException(status_code=500, detail="Failed to list models")


@router.post("/api/v1/models/switch")
async def switch_model(request: ModelLoadRequest, core: PenguinCore = Depends(get_core)):
    """Switch the active model at runtime."""
    try:
        ok = await core.load_model(request.model_id)
        if not ok:
            raise HTTPException(status_code=400, detail=f"Failed to load model '{request.model_id}'")
        return {"ok": True, "current_model": core.get_current_model()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error switching model to {request.model_id}: {e}")
        raise HTTPException(status_code=500, detail="Unexpected error switching model")


@router.get("/api/v1/models/discover")
async def discover_models(core: PenguinCore = Depends(get_core)):
    """Discover models via OpenRouter catalogue.

    Requires OPENROUTER_API_KEY in the server environment. Returns the raw
    OpenRouter catalogue mapped to a lean schema: id, name, provider,
    context_length, max_output_tokens, pricing (if present).
    """
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="OPENROUTER_API_KEY not set on server")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    # Optional headers for leaderboard attribution
    site_url = os.getenv("OPENROUTER_SITE_URL")
    site_title = os.getenv("OPENROUTER_SITE_TITLE") or "Penguin_AI"
    if site_url:
        headers["HTTP-Referer"] = site_url
    if site_title:
        headers["X-Title"] = site_title

    url = "https://openrouter.ai/api/v1/models"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
            data = payload.get("data", []) if isinstance(payload, dict) else []

            # Map to a slimmer structure
            mapped = []
            for m in data:
                try:
                    mapped.append({
                        "id": m.get("id"),
                        "name": m.get("name"),
                        "provider": (m.get("id", "").split("/", 1)[0] if "id" in m else None),
                        "context_length": m.get("context_length"),
                        "max_output_tokens": m.get("max_output_tokens"),
                        "pricing": m.get("pricing"),
                    })
                except Exception:
                    continue

            return {"models": mapped}
    except httpx.HTTPStatusError as e:
        logger.error(f"OpenRouter catalogue error: {e.response.status_code} {e.response.text[:200]}")
        raise HTTPException(status_code=502, detail="Upstream OpenRouter error fetching models")
    except Exception as e:
        logger.error(f"OpenRouter catalogue request failed: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch OpenRouter model catalogue")

@router.post("/api/v1/chat/message")
async def handle_chat_message(
    request: MessageRequest, core: PenguinCore = Depends(get_core)
):
    """Process a chat message, with optional conversation support."""
    try:
        # Maybe?
        # # If no conversation_id is provided, try to use the most recent one
        # if not request.conversation_id:
        #     # This is a temporary solution until the frontend manages sessions more explicitly.
        #     # We fetch the list of conversations and use the most recent one.
        #     recent_conversations = core.list_conversations(limit=1)
        #     if recent_conversations:
        #         request.conversation_id = recent_conversations[0].get("id")
        #         logger.debug(f"No conversation_id provided. Using most recent: {request.conversation_id}")

        # Create input data dictionary from request
        input_data = {
            "text": request.text
        }
        
        # Add image path if provided
        if request.image_path:
            input_data["image_path"] = request.image_path
        
        # If reasoning is requested, capture reasoning chunks via a local callback
        reasoning_buf: List[str] = []
        stream_cb = None
        effective_streaming = bool(request.streaming)
        if request.include_reasoning:
            effective_streaming = True  # force streaming internally to collect reasoning

            async def _rest_stream_cb(chunk: str, message_type: str = "assistant"):
                if message_type == "reasoning" and chunk:
                    reasoning_buf.append(chunk)

            stream_cb = _rest_stream_cb

        # Process the message with all available options
        process_result = await core.process(
            input_data=input_data,
            context=request.context,
            conversation_id=request.conversation_id,
            max_iterations=request.max_iterations or 5,
            context_files=request.context_files,
            streaming=effective_streaming,
            stream_callback=stream_cb,
        )
        
        # Build response
        resp: Dict[str, Any] = {
            "response": process_result.get("assistant_response", ""),
            "action_results": process_result.get("action_results", []),
        }
        if request.include_reasoning:
            resp["reasoning"] = "".join(reasoning_buf)
        return resp
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
            item = None
            try:
                # Wait for a token with a timeout
                item = await asyncio.wait_for(queue.get(), timeout=BUFFER_TIMEOUT)

                if item is None: # Sentinel value to stop
                    logger.debug("[Sender Task] Received stop signal.")
                    # Send any remaining buffer before stopping
                    if send_buffer:
                        logger.debug(f"[Sender Task] Sending final buffer: '{send_buffer}'")
                        await websocket.send_json({"event": "token", "data": {"token": send_buffer}})
                        send_buffer = ""
                    queue.task_done()
                    break

                # Handle dict payloads {token, type, include_reasoning}
                if isinstance(item, dict):
                    tkn = item.get("token", "")
                    mtype = item.get("type", "assistant")
                    inc_reason = bool(item.get("include_reasoning", False))

                    if mtype == "reasoning":
                        # Flush any pending assistant buffer before reasoning
                        if send_buffer and inc_reason:
                            await websocket.send_json({"event": "token", "data": {"token": send_buffer}})
                            send_buffer = ""
                        # Emit reasoning token only if requested
                        if inc_reason and tkn:
                            await websocket.send_json({"event": "reasoning", "data": {"token": tkn}})
                        queue.task_done()
                        continue
                    else:
                        # Regular assistant content – buffer and coalesce
                        send_buffer += tkn
                        queue.task_done()
                        logger.debug(f"[Sender Task] Added to buffer: '{tkn}'. Buffer size: {len(send_buffer)}")
                else:
                    # Backward-compat: plain string token
                    send_buffer += str(item)
                    queue.task_done()
                    logger.debug(f"[Sender Task] Added to buffer: '{item}'. Buffer size: {len(send_buffer)}")

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

    # (per-request stream_callback is defined inside the loop to capture include_reasoning)

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
            include_reasoning = bool(data.get("include_reasoning", False))

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
                # Define a per-request callback that preserves message_type
                async def per_request_stream_callback(chunk: str, message_type: str = "assistant"):
                    try:
                        await response_queue.put({
                            "token": chunk,
                            "type": message_type,
                            "include_reasoning": include_reasoning
                        })
                    except Exception as e:
                        logger.error(f"Error enqueuing stream chunk: {e}")

                process_task = asyncio.create_task(core.process(
                    input_data=input_data,
                    conversation_id=conversation_id,
                    max_iterations=max_iterations,
                    context_files=context_files,
                    context=context,
                    streaming=True,
                    stream_callback=per_request_stream_callback
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
                complete_payload = {
                    "response": process_result.get("assistant_response", ""),
                    "action_results": process_result.get("action_results", [])
                }
                if include_reasoning and hasattr(core, "_streaming_state"):
                    complete_payload["reasoning"] = core._streaming_state.get("reasoning_content", "")
                await websocket.send_json({"event": "complete", "data": complete_payload})
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


# Enhanced Project Management API
class ProjectCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    workspace_path: Optional[str] = None

class ProjectUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None

class TaskCreateRequest(BaseModel):
    project_id: str
    title: str
    description: Optional[str] = None
    parent_task_id: Optional[str] = None
    priority: Optional[int] = 1

class TaskUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[int] = None

# Project Management Endpoints
@router.post("/api/v1/projects")
async def create_project(
    request: ProjectCreateRequest, core: PenguinCore = Depends(get_core)
):
    """Create a new project."""
    try:
        project = await core.project_manager.create_project_async(
            name=request.name,
            description=request.description or f"Project: {request.name}",
            workspace_path=request.workspace_path
        )
        return {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "status": project.status,
            "workspace_path": project.workspace_path,
            "created_at": project.created_at if project.created_at else None
        }
    except Exception as e:
        logger.error(f"Error creating project: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/v1/projects")
async def list_projects(core: PenguinCore = Depends(get_core)):
    """List all projects."""
    try:
        projects = await core.project_manager.list_projects_async()
        return {
            "projects": [
                {
                    "id": project.id,
                    "name": project.name,
                    "description": project.description,
                    "status": project.status,
                    "workspace_path": project.workspace_path,
                    "created_at": project.created_at if project.created_at else None,
                    "updated_at": project.updated_at if project.updated_at else None
                }
                for project in projects
            ]
        }
    except Exception as e:
        logger.error(f"Error listing projects: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/v1/projects/{project_id}")
async def get_project(project_id: str, core: PenguinCore = Depends(get_core)):
    """Get a specific project by ID."""
    try:
        project = await core.project_manager.get_project_async(project_id)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
        
        # Get tasks for this project
        tasks = await core.project_manager.list_tasks_async(project_id=project_id)
        
        return {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "status": project.status,
            "workspace_path": project.workspace_path,
            "created_at": project.created_at if project.created_at else None,
            "updated_at": project.updated_at if project.updated_at else None,
            "tasks": [
                {
                    "id": task.id,
                    "title": task.title,
                    "status": task.status.value,
                    "priority": task.priority,
                    "created_at": task.created_at if task.created_at else None
                }
                for task in tasks
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting project: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Temporarily disabled - update_project method not implemented in ProjectManager
# @router.put("/api/v1/projects/{project_id}")
# async def update_project(...):

# Temporarily disabled - delete_project method not implemented in ProjectManager
# @router.delete("/api/v1/projects/{project_id}")
# async def delete_project(...):

# Task Management Endpoints
@router.post("/api/v1/tasks")
async def create_task(
    request: TaskCreateRequest, core: PenguinCore = Depends(get_core)
):
    """Create a new task in a project."""
    try:
        task = await core.project_manager.create_task_async(
            project_id=request.project_id,
            title=request.title,
            description=request.description or request.title,
            parent_task_id=request.parent_task_id,
            priority=request.priority or 1
        )
        return {
            "id": task.id,
            "project_id": task.project_id,
            "title": task.title,
            "description": task.description,
            "status": task.status.value,
            "priority": task.priority,
            "parent_task_id": task.parent_task_id,
            "created_at": task.created_at if task.created_at else None
        }
    except Exception as e:
        logger.error(f"Error creating task: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/v1/tasks")
async def list_tasks(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    core: PenguinCore = Depends(get_core)
):
    """List tasks, optionally filtered by project or status."""
    try:
        # Parse status filter
        status_filter = None
        if status:
            from penguin.project.models import TaskStatus
            try:
                status_filter = TaskStatus(status.upper())
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid status: {status}. Valid options: pending, running, completed, failed"
                )
        
        tasks = await core.project_manager.list_tasks_async(
            project_id=project_id,
            status=status_filter
        )
        
        return {
            "tasks": [
                {
                    "id": task.id,
                    "project_id": task.project_id,
                    "title": task.title,
                    "description": task.description,
                    "status": task.status.value,
                    "priority": task.priority,
                    "parent_task_id": task.parent_task_id,
                    "created_at": task.created_at if task.created_at else None,
                    "updated_at": task.updated_at if task.updated_at else None
                }
                for task in tasks
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing tasks: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/v1/tasks/{task_id}")
async def get_task(task_id: str, core: PenguinCore = Depends(get_core)):
    """Get a specific task by ID."""
    try:
        task = await core.project_manager.get_task_async(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        
        return {
            "id": task.id,
            "project_id": task.project_id,
            "title": task.title,
            "description": task.description,
            "status": task.status.value,
            "priority": task.priority,
            "parent_task_id": task.parent_task_id,
            "created_at": task.created_at if task.created_at else None,
            "updated_at": task.updated_at if task.updated_at else None
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting task: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Temporarily disabled - general update_task method not implemented in ProjectManager
# Use update_task_status for status changes or implement full update_task method
# @router.put("/api/v1/tasks/{task_id}")
# async def update_task(...):

# Temporarily disabled - delete_task method not implemented in ProjectManager
# @router.delete("/api/v1/tasks/{task_id}")
# async def delete_task(...):

# Task Status Management
@router.post("/api/v1/tasks/{task_id}/start")
async def start_task(task_id: str, core: PenguinCore = Depends(get_core)):
    """Start a task (set status to running)."""
    try:
        from penguin.project.models import TaskStatus
        
        # Get the task first to check its current status
        task = await core.project_manager.get_task_async(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        
        # If task is already active, that's fine - just return success
        if task.status == TaskStatus.ACTIVE:
            return {
                "id": task.id,
                "title": task.title,
                "status": task.status.value,
                "message": "Task is already active"
            }
        
        # Otherwise, try to transition to active
        success = core.project_manager.update_task_status(task_id, TaskStatus.ACTIVE, "Started via API")
        if not success:
            raise HTTPException(status_code=400, detail=f"Cannot start task - invalid status transition from {task.status.value}")
        
        # Get the updated task
        updated_task = await core.project_manager.get_task_async(task_id)
        return {
            "id": updated_task.id,
            "title": updated_task.title,
            "status": updated_task.status.value,
            "message": "Task started successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting task: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/v1/tasks/{task_id}/complete")
async def complete_task(task_id: str, core: PenguinCore = Depends(get_core)):
    """Complete a task (set status to completed)."""
    try:
        from penguin.project.models import TaskStatus
        success = core.project_manager.update_task_status(task_id, TaskStatus.COMPLETED, "Completed via API")
        if not success:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        
        # Get the updated task
        task = await core.project_manager.get_task_async(task_id)
        return {
            "id": task.id,
            "title": task.title,
            "status": task.status.value,
            "message": "Task completed successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error completing task: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/v1/tasks/{task_id}/execute")
async def execute_task_from_project(
    task_id: str, 
    core: PenguinCore = Depends(get_core)
):
    """Execute a task using the Engine with project context."""
    try:
        # Get the task details
        task = await core.project_manager.get_task_async(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        
        # Check if Engine is available
        if not hasattr(core, 'engine') or not core.engine:
            raise HTTPException(
                status_code=503,
                detail="Engine layer not available for task execution"
            )
        
        # Set task to running status
        from penguin.project.models import TaskStatus
        core.project_manager.update_task_status(task_id, TaskStatus.ACTIVE, "Executing via Engine")
        
        # Create task prompt
        task_prompt = f"Task: {task.title}"
        if task.description:
            task_prompt += f"\nDescription: {task.description}"
        
        # Execute task using Engine
        result = await core.engine.run_task(
            task_prompt=task_prompt,
            max_iterations=10,
            task_name=task.title,
            task_context={
                "task_id": task_id,
                "project_id": task.project_id,
                "priority": task.priority
            },
            enable_events=True
        )
        
        # Update task status based on result
        final_status = TaskStatus.COMPLETED if result.get("status") == "completed" else TaskStatus.FAILED
        core.project_manager.update_task_status(task_id, final_status, f"Engine execution result: {result.get('status')}")
        
        return {
            "task_id": task_id,
            "status": result.get("status", "completed"),
            "response": result.get("assistant_response", ""),
            "iterations": result.get("iterations", 0),
            "execution_time": result.get("execution_time", 0),
            "action_results": result.get("action_results", []),
            "final_task_status": final_status.value
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing task: {str(e)}")
        # Set task to failed status
        try:
            from penguin.project.models import TaskStatus
            core.project_manager.update_task_status(task_id, TaskStatus.FAILED, f"Execution error: {str(e)}")
        except:
            pass  # Don't fail the response if status update fails
        raise HTTPException(status_code=500, detail=str(e))


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

# Enhanced task execution with Engine support
@router.post("/api/v1/tasks/execute-sync")
async def execute_task_sync(
    request: TaskRequest,
    core: PenguinCore = Depends(get_core)
):
    """Execute a task synchronously using the Engine layer."""
    try:
        # Check if Engine is available
        if not hasattr(core, 'engine') or not core.engine:
            # Fallback to RunMode
            return await execute_task_via_runmode(request, core)
        
        # Use Engine for task execution
        task_prompt = f"Task: {request.name}"
        if request.description:
            task_prompt += f"\nDescription: {request.description}"
        
        # Execute task using Engine
        result = await core.engine.run_task(
            task_prompt=task_prompt,
            max_iterations=10,  # Default to 10 iterations
            task_name=request.name,
            task_context={
                "continuous": request.continuous,
                "time_limit": request.time_limit
            },
            enable_events=True
        )
        
        return {
            "status": result.get("status", "completed"),
            "response": result.get("assistant_response", ""),
            "iterations": result.get("iterations", 0),
            "execution_time": result.get("execution_time", 0),
            "action_results": result.get("action_results", []),
            "task_metadata": result.get("task", {})
        }
        
    except Exception as e:
        logger.error(f"Error executing task synchronously: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error executing task: {str(e)}"
        )

async def execute_task_via_runmode(request: TaskRequest, core: PenguinCore) -> Dict[str, Any]:
    """Fallback method using RunMode when Engine is not available."""
    try:
        # This would need to be modified to return result instead of running in background
        # For now, return an error indicating Engine is required
        raise HTTPException(
            status_code=503,
            detail="Engine layer not available. Use /api/v1/tasks/execute for background execution via RunMode."
        )
    except Exception as e:
        logger.error(f"Error in RunMode fallback: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error in fallback execution: {str(e)}"
        )


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


# Conversation-specific checkpointing
class ConversationCheckpointRequest(BaseModel):
    conversation_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None


@router.post("/api/v1/conversations/checkpoint")
async def create_conversation_checkpoint(
    request: ConversationCheckpointRequest,
    core: PenguinCore = Depends(get_core)
):
    """Create a checkpoint for a specific conversation."""
    try:
        # Create checkpoint for current conversation (simplified approach)
        checkpoint_id = await core.create_checkpoint(
            name=request.name or "Conversation checkpoint",
            description=request.description or "Checkpoint created via conversation API"
        )
        
        if checkpoint_id:
            current_session = core.conversation_manager.get_current_session()
            return {
                "checkpoint_id": checkpoint_id,
                "conversation_id": current_session.id if current_session else None,
                "status": "created",
                "name": request.name,
                "description": request.description
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to create conversation checkpoint")
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating conversation checkpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


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

# --- Checkpoint Management Endpoints ---

@router.post("/api/v1/checkpoints/create")
async def create_checkpoint(
    request: CheckpointCreateRequest,
    core: PenguinCore = Depends(get_core)
):
    """Create a manual checkpoint of the current conversation state."""
    try:
        # Validate input - reject empty names or invalid descriptions
        if request.name is not None and request.name.strip() == "":
            raise HTTPException(
                status_code=400,
                detail="Checkpoint name cannot be empty"
            )
        
        # Validate description if provided
        if request.description is not None and not isinstance(request.description, str):
            raise HTTPException(
                status_code=400,
                detail="Checkpoint description must be a string"
            )
        
        checkpoint_id = await core.create_checkpoint(
            name=request.name,
            description=request.description
        )
        
        if checkpoint_id:
            return {
                "checkpoint_id": checkpoint_id,
                "status": "created",
                "name": request.name,
                "description": request.description
            }
        else:
            raise HTTPException(
                status_code=500,
                detail="Failed to create checkpoint"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating checkpoint: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error creating checkpoint: {str(e)}"
        )

@router.get("/api/v1/checkpoints")
async def list_checkpoints(
    session_id: Optional[str] = None,
    limit: int = 50,
    core: PenguinCore = Depends(get_core)
):
    """List available checkpoints with optional filtering."""
    try:
        checkpoints = core.list_checkpoints(
            session_id=session_id,
            limit=limit
        )
        return {"checkpoints": checkpoints}
    except Exception as e:
        logger.error(f"Error listing checkpoints: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error listing checkpoints: {str(e)}"
        )

@router.post("/api/v1/checkpoints/{checkpoint_id}/rollback")
async def rollback_to_checkpoint(
    checkpoint_id: str,
    core: PenguinCore = Depends(get_core)
):
    """Rollback conversation to a specific checkpoint."""
    try:
        success = await core.rollback_to_checkpoint(checkpoint_id)
        
        if success:
            return {
                "status": "success",
                "checkpoint_id": checkpoint_id,
                "message": f"Successfully rolled back to checkpoint {checkpoint_id}"
            }
        else:
            raise HTTPException(
                status_code=404,
                detail=f"Checkpoint {checkpoint_id} not found or rollback failed"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rolling back to checkpoint {checkpoint_id}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error rolling back to checkpoint: {str(e)}"
        )

@router.post("/api/v1/checkpoints/{checkpoint_id}/branch")
async def branch_from_checkpoint(
    checkpoint_id: str,
    request: CheckpointBranchRequest,
    core: PenguinCore = Depends(get_core)
):
    """Create a new conversation branch from a checkpoint."""
    try:
        branch_id = await core.branch_from_checkpoint(
            checkpoint_id,
            name=request.name,
            description=request.description
        )
        
        if branch_id:
            return {
                "branch_id": branch_id,
                "source_checkpoint_id": checkpoint_id,
                "status": "created",
                "name": request.name,
                "description": request.description
            }
        else:
            raise HTTPException(
                status_code=404,
                detail=f"Checkpoint {checkpoint_id} not found or branch creation failed"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating branch from checkpoint {checkpoint_id}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error creating branch from checkpoint: {str(e)}"
        )

@router.get("/api/v1/checkpoints/stats")
async def get_checkpoint_stats(core: PenguinCore = Depends(get_core)):
    """Get statistics about the checkpointing system."""
    try:
        stats = core.get_checkpoint_stats()
        return stats
    except Exception as e:
        logger.error(f"Error getting checkpoint stats: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error getting checkpoint stats: {str(e)}"
        )

@router.post("/api/v1/checkpoints/cleanup")
async def cleanup_old_checkpoints(core: PenguinCore = Depends(get_core)):
    """Clean up old checkpoints according to retention policy."""
    try:
        cleaned_count = await core.cleanup_old_checkpoints()
        return {
            "status": "completed",
            "cleaned_count": cleaned_count,
            "message": f"Cleaned up {cleaned_count} old checkpoints"
        }
    except Exception as e:
        logger.error(f"Error cleaning up checkpoints: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error cleaning up checkpoints: {str(e)}"
        )

# --- Model Management Endpoints ---

@router.get("/api/v1/models")
async def list_models(core: PenguinCore = Depends(get_core)):
    """List all available models."""
    try:
        models = core.list_available_models()
        return {"models": models}
    except Exception as e:
        logger.error(f"Error listing models: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error listing models: {str(e)}"
        )

@router.post("/api/v1/models/load")
async def load_model(
    request: ModelLoadRequest,
    core: PenguinCore = Depends(get_core)
):
    """Switch to a different model."""
    try:
        success = await core.load_model(request.model_id)
        
        if success:
            current_model = None
            if core.model_config and core.model_config.model:
                current_model = core.model_config.model
                
            return {
                "status": "success",
                "model_id": request.model_id,
                "current_model": current_model,
                "message": f"Successfully loaded model: {request.model_id}"
            }
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to load model: {request.model_id}"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error loading model {request.model_id}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error loading model: {str(e)}"
        )

@router.get("/api/v1/models/current")
async def get_current_model(core: PenguinCore = Depends(get_core)):
    """Get information about the currently loaded model."""
    try:
        if not core.model_config:
            raise HTTPException(
                status_code=404,
                detail="No model configuration found"
            )
            
        return {
            "model": core.model_config.model,
            "provider": core.model_config.provider,
            "client_preference": core.model_config.client_preference,
            "max_tokens": core.model_config.max_tokens,
            "temperature": core.model_config.temperature,
            "streaming_enabled": core.model_config.streaming_enabled,
            "vision_enabled": core.model_config.vision_enabled
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting current model: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error getting current model: {str(e)}"
        )

# --- System Information and Diagnostics ---

@router.get("/api/v1/system/info")
async def get_system_info(core: PenguinCore = Depends(get_core)):
    """Get comprehensive system information."""
    try:
        info = {
            "penguin_version": "0.1.0",  # Could be extracted from package info
            "engine_available": hasattr(core, 'engine') and core.engine is not None,
            "checkpoints_enabled": core.get_checkpoint_stats().get('enabled', False),
            "current_model": None,
            "conversation_manager": {
                "active": hasattr(core, 'conversation_manager') and core.conversation_manager is not None,
                "current_session_id": None,
                "total_messages": 0
            },
            "tool_manager": {
                "active": hasattr(core, 'tool_manager') and core.tool_manager is not None,
                "total_tools": 0
            }
        }
        
        # Add current model info
        if core.model_config:
            info["current_model"] = {
                "model": core.model_config.model,
                "provider": core.model_config.provider,
                "streaming_enabled": core.model_config.streaming_enabled,
                "vision_enabled": core.model_config.vision_enabled
            }
        
        # Add conversation manager details
        if hasattr(core, 'conversation_manager') and core.conversation_manager:
            current_session = core.conversation_manager.get_current_session()
            if current_session:
                info["conversation_manager"]["current_session_id"] = current_session.id
                info["conversation_manager"]["total_messages"] = len(current_session.messages)
        
        # Add tool manager details
        if hasattr(core, 'tool_manager') and core.tool_manager:
            info["tool_manager"]["total_tools"] = len(getattr(core.tool_manager, 'tools', {}))
        
        return info
        
    except Exception as e:
        logger.error(f"Error getting system info: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error getting system info: {str(e)}"
        )

@router.get("/api/v1/system/status")
async def get_system_status(core: PenguinCore = Depends(get_core)):
    """Get current system status including RunMode state."""
    try:
        status = {
            "status": "active",
            "runmode_status": getattr(core, 'current_runmode_status_summary', 'RunMode idle.'),
            "continuous_mode": getattr(core, '_continuous_mode', False),
            "streaming_active": getattr(core, '_streaming_state', {}).get('active', False),
            "token_usage": core.get_token_usage(),
            "timestamp": datetime.now().isoformat()
        }
        
        return status
        
    except Exception as e:
        logger.error(f"Error getting system status: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error getting system status: {str(e)}"
        )


# Memory System API Endpoints
@router.post("/api/v1/memory/store")
async def store_memory(
    request: MemoryStoreRequest,
    core: PenguinCore = Depends(get_core)
):
    """Store a new memory entry."""
    try:
        # Use the ToolManager's memory functionality
        tool_manager = core.tool_manager
        
        # Check if memory provider is available
        if not hasattr(tool_manager, '_memory_provider') or tool_manager._memory_provider is None:
            # Initialize memory provider
            from penguin.memory.providers.factory import MemoryProviderFactory
            memory_config = tool_manager.config.get("memory", {}) if hasattr(tool_manager.config, 'get') else {}
            tool_manager._memory_provider = MemoryProviderFactory.create_provider(memory_config)
            await tool_manager._memory_provider.initialize()
        
        # Store the memory
        memory_id = await tool_manager._memory_provider.add_memory(
            content=request.content,
            metadata=request.metadata,
            categories=request.categories
        )
        
        return {
            "memory_id": memory_id,
            "status": "success",
            "message": "Memory stored successfully"
        }
        
    except Exception as e:
        logger.error(f"Error storing memory: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/memory/search")
async def search_memory(
    request: MemorySearchRequest,
    core: PenguinCore = Depends(get_core)
):
    """Search for memories."""
    try:
        # Use ToolManager's memory search functionality
        result = await core.tool_manager.perform_memory_search(
            query=request.query,
            k=request.max_results,
            memory_type=request.memory_type,
            categories=request.categories
        )
        
        # Parse the JSON result from perform_memory_search
        import json
        try:
            parsed_result = json.loads(result)
            if isinstance(parsed_result, dict) and "error" in parsed_result:
                raise HTTPException(status_code=500, detail=parsed_result["error"])
            
            return {
                "query": request.query,
                "results": parsed_result if isinstance(parsed_result, list) else [parsed_result],
                "count": len(parsed_result) if isinstance(parsed_result, list) else 1
            }
        except json.JSONDecodeError:
            # If it's not JSON, return as text
            return {
                "query": request.query,
                "results": [{"content": result}],
                "count": 1
            }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error searching memory: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/memory/{memory_id}")
async def get_memory(
    memory_id: str,
    core: PenguinCore = Depends(get_core)
):
    """Get a specific memory by ID."""
    try:
        # Access memory provider
        tool_manager = core.tool_manager
        if not hasattr(tool_manager, '_memory_provider') or tool_manager._memory_provider is None:
            raise HTTPException(status_code=500, detail="Memory system not initialized")
        
        memory = await tool_manager._memory_provider.get_memory(memory_id)
        if not memory:
            raise HTTPException(status_code=404, detail=f"Memory {memory_id} not found")
        
        return memory
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving memory: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/memory/stats")
async def get_memory_stats(core: PenguinCore = Depends(get_core)):
    """Get memory system statistics."""
    try:
        tool_manager = core.tool_manager
        if not hasattr(tool_manager, '_memory_provider') or tool_manager._memory_provider is None:
            return {
                "total_memories": 0,
                "status": "not_initialized"
            }
        
        stats = await tool_manager._memory_provider.get_memory_stats()
        return stats
        
    except Exception as e:
        logger.error(f"Error getting memory stats: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
