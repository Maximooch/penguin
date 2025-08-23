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

Priority focus – General robustness

- [ ] Standard error envelope across REST + WS (include code/message/request_id)
- [ ] Request IDs propagated (X-Request-ID) through logs and responses
- [ ] Provider fallback policy (retry once without reasoning; clear 404/validation on unknown model ids)
- [ ] Outbound timeouts and backoff for provider calls (OpenRouter/etc.)
- [ ] Basic rate limiting with 429 + Retry-After
- [ ] WS heartbeats/idle timeout and backpressure-safe buffering
- [ ] Structured JSON logging (latency, provider timing), minimal PII

Implementation checklist

- [x] Add include_reasoning to WebSocket handler and forward type to events
  <!-- Implemented: penguin/penguin/web/routes.py (WS handler); core forwards message_type to external callbacks -->
- [x] Add include_reasoning to REST chat and include reasoning in response when requested
  <!-- Implemented: penguin/penguin/web/routes.py (collects reasoning via stream_callback and returns 'reasoning' when requested) -->
- [x] Expose /api/v1/health and /api/v1/system-info
  <!-- Implemented: penguin/penguin/web/routes.py -->
- [x] Add python-multipart to [project.optional-dependencies].web
  <!-- Implemented: penguin/pyproject.toml -->
- [ ] (Optional) Add /api/v1/models and switch endpoint
- [ ] Update docs: API reference, getting started, and examples

Next endpoints/support

- [ ] Merge discovered models with configured ones in /api/v1/models (never empty)
- [ ] Add filters to /api/v1/models/discover (provider=, search=, min_context=)
- [ ] RunMode REST: POST /api/v1/run/start, GET /api/v1/run/status, POST /api/v1/run/stop
- [ ] RunMode WS: /api/v1/run/stream (status, message, token, reasoning, complete)
- [ ] SSE alternative for chat stream: /api/v1/chat/stream-sse with same event names

---

Additional improvements (proposed)

- Standard error envelope (REST + WS):
  - REST response on error: {"error": {"code": "...", "message": "...", "details": {...}, "request_id": "..."}}
  - WS error event: {"event":"error","data":{"code":"...","message":"...","request_id":"..."}}
  - Always attach a request_id and propagate X-Request-ID/X-Correlation-ID.

- Rate limiting & headers:
  - Per-IP and per-API-key sliding window with 429 + Retry-After.
  - Expose X-RateLimit-Limit/Remaining/Reset headers on REST; WS sends a warning event before closing.

- Auth & security:
  - Pluggable auth: API key (current) and OAuth2 (device code / client credentials) as optional backends.
  - Strict CORS allowlist and configurable origins; consider signed WS tokens (query/header) with expiry.
  - Sanitize uploads (MIME allowlist, size caps), prevent path traversal, and redact secrets in logs.

- Versioning & deprecation:
  - Keep URL version (/api/v1) and optionally support Accept: application/vnd.penguin.v1+json.
  - Emit deprecation headers (Sunset/Deprecation) and changelog links when retiring fields.

- Observability:
  - Structured JSON logs, request timing, and provider breakdown (connect, first-byte, total).
  - OpenTelemetry traces (WS spans for start→complete), with provider spans.
  - /metrics (Prometheus): request counts, latency histograms, WS connections, tokens streamed.

- Provider fallback policy:
  - When reasoning-enabled provider fails: retry once without reasoning; optionally failover to secondary provider.
  - Include {"provider":"...","reasoning_used":true|false} in complete payload for transparency.

- WS robustness:
  - Heartbeats/keepalive (ping) and idle timeout; client sees progress or heartbeat events periodically.
  - Backpressure-aware buffering and maximum message size limits; document close codes.

- Contracts & limits:
  - Document max text length, max image size, supported MIME types, and truncation semantics.
  - Idempotency-Key header for upload and run/start endpoints.
  - Optional batch chat endpoint for non-streaming batch requests.

- OpenAPI & SDKs:
  - Expand examples for REST & WS (reasoning on/off, images, context files).
  - Generate client SDKs (Python/TypeScript) from OpenAPI with typed events.

- Testing & chaos:
  - Integration tests for WS reasoning/token ordering, error paths, and timeouts.
  - Chaos toggles to simulate provider timeouts/network failures to validate fallbacks.