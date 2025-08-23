- Yes—your stack already streams reasoning internally, but the WebSocket doesn’t expose it. Do these:
  - WebSocket: include message type per chunk. Change the stream callback to enqueue both token and type, and emit distinct events:
    - event: "reasoning" for thinking tokens
    - event: "token" (assistant content)
    - event: "complete" should include response and optional reasoning
  - Client opt-in: accept {"text": "...", "include_reasoning": true} to enable reasoning on the wire (default off).
  - REST /api/v1/chat/message: add include_reasoning to return {"response": "...", "reasoning": "..."} when requested.

- Python API improvements:
  - PenguinAPI.chat: add on_chunk: Callable[[str, str], Awaitable[None]] and/or return an async iterator for streaming. Pass through to Engine.run_response(streaming=True, stream_callback).
  - Expose a simple “stream” helper returning an async generator yielding (message_type, chunk).

- Add a diagnostics surface:
  - REST: /api/v1/health and /api/v1/system-info (core.get_system_status/info()) for quick checks.
  - Python: expose core.get_system_status/info via PenguinAPI.

- Better OpenAPI docs:
  - Annotate models so /api/docs shows include_reasoning, conversation_id, image_path, max_iterations, and the event schema for WebSocket (discrete events: start, reasoning, token, progress, complete, error).

- Web extra dependencies:
  - Add python-multipart to [project.optional-dependencies].web to avoid runtime “install python-multipart” errors.

- Versioning and capabilities:
  - Include version and enabled features in /api/v1/capabilities (reasoning_supported, streaming_supported) and in the root “/”.

- Consistency:
  - Align final “complete” event structure across WebSocket and REST: always include response, action_results, iteration metadata, and (optionally) reasoning when requested.

- Model control (optional next):
  - Add GET /api/v1/models and POST /api/v1/models/switch to mirror core.list_available_models() and core.load_model().

- SSE option (optional):
  - Provide /api/v1/chat/stream-sse for environments that prefer SSE over WebSocket, with the same event names.

These changes make reasoning tokens first-class, stabilize client behavior, and reduce setup surprises. Adding python-multipart to the web extra is the quick fix; streaming event typing and include_reasoning are the highest impact next steps.

---

API contract (proposed)

1) WebSocket /api/v1/chat/stream

- Request JSON:
  {
    "text": "...",
    "conversation_id": "optional",
    "context": {"k": "v"},
    "context_files": ["..."],
    "image_path": "optional",
    "max_iterations": 5,
    "include_reasoning": false
  }

- Events (server → client):
  - {"event":"start","data":{}}
  - {"event":"progress","data":{"iteration":1,"max_iterations":5,"message":"..."}}
  - {"event":"reasoning","data":{"token":"..."}}        # only when include_reasoning=true and model supports reasoning
  - {"event":"token","data":{"token":"..."}}            # assistant visible content
  - {"event":"error","data":{"message":"..."}}
  - {"event":"complete","data":{"response":"...","action_results":[],"reasoning":"...optional...","iterations":N}}

Compatibility notes:
- If include_reasoning is omitted/false, no reasoning events are emitted and "reasoning" is omitted from complete.
- Existing clients that only read "token" and "complete" keep working.

2) REST POST /api/v1/chat/message

- Request JSON:
  {"text":"...","conversation_id":"optional","streaming":false,"include_reasoning":false,"max_iterations":5}

- Response JSON:
  {"response":"...","action_results":[],"reasoning":"...optional..."}

3) Health and system info

- GET /api/v1/health → {"status":"healthy"|"unhealthy", ...}
- GET /api/v1/system-info → core.get_system_info() payload

4) Model control (optional)

- GET /api/v1/models → [{id,name,provider,current,max_tokens,...}]
- POST /api/v1/models/switch {"model_id":"provider/model"} → {"ok":true}

Python API (proposed)

- PenguinAPI.chat(..., streaming: bool = False, on_chunk: Optional[Callable[[str,str], Awaitable[None]]] = None, include_reasoning: bool = False)
  - If streaming=True and on_chunk is provided, invoke on_chunk(chunk, message_type) with message_type in {"reasoning","assistant"}.
  - Return structured dict including assistant_response, action_results, and optionally reasoning.

OpenAPI additions

- Document include_reasoning, event schema for WebSocket, and REST response fields.

Implementation checklist

- [ ] Add include_reasoning to WebSocket handler and forward type to events
- [ ] Add include_reasoning to REST chat and include reasoning in response when requested
- [ ] Expose /api/v1/health and /api/v1/system-info
- [ ] Add python-multipart to [project.optional-dependencies].web
- [ ] (Optional) Add /api/v1/models and switch endpoint
- [ ] Update docs: API reference, getting started, and examples