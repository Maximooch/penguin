# Penguin Roadmap Issues

This document contains all roadmap issues (original + additional) with milestones, labels, and acceptance criteria.
Use it to refine, cut, or expand before creating GitHub issues.

---

## Milestones
- **M1 — Week 1: Stabilize Core** *(Days 1–5)*
- **M2 — Week 2: Perf & Safety** *(Days 6–10)*
- **M3 — Week 3: Capabilities** *(Days 11–16)*
- **M4 — Week 4: Multi-Agent & Release** *(Days 17–30)*

## Labels
`area/core`, `area/engine`, `area/tools`, `area/memory`, `area/project-store`, `area/exec`, `area/infra`, `area/evals`, `area/ui`  
`kind/refactor`, `kind/feature`, `kind/perf`, `kind/test`, `kind/docs`, `kind/bug`  
`priority/P0`, `priority/P1`, `priority/P2`, `priority/P3`

---

## Issues

### 1) Type hints + contracts across core
**Labels:** area/core, kind/refactor, priority/P0  
**Milestone:** M1 — Week 1  
**Why:** Kill spaghetti; enable static guarantees.  
**Tasks**
- Add full type hints to `core`, `engine`, `tool_manager`, `memory`, `project_store`
- Break up any >200-line functions; single-responsibility
- Add module-level interfaces (`Memory`, `Tool`, `Engine`, `ProjectStore`)
**Acceptance**
- `mypy` passes (no new `# type: ignore` in our code)
- CI gate enforces typing

### 2) Structured logging + trace IDs end-to-end
**Labels:** area/core, kind/refactor, priority/P0  
**Milestone:** M1 — Week 1  
**Tasks**
- Replace prints with `logging` + JSON formatter
- Add request/trace IDs through engine/tool calls
- Emit spans for LLM, tool, memory, DB
**Acceptance**
- One interaction shows a single trace with nested spans in logs

### 3) Error envelopes + unified tool error handling
**Labels:** area/tools, kind/refactor, priority/P0  
**Milestone:** M1 — Week 1  
**Tasks**
- Standardize `{ok, result, error:{code,msg}}`
- Surface human-readable summaries to the LLM
- Add retries for transient failures
**Acceptance**
- Tool failures don’t crash loop; errors are summarized to the model

### 4) Test harness: engine, tools, memory, parsing
**Labels:** area/evals, kind/test, priority/P0  
**Milestone:** M1 — Week 1  
**Tasks**
- Pytest suites + fixtures; snapshot/golden tests for prompts
- CI coverage report; coverage gate ≥60%
**Acceptance**
- CI green with ≥60% coverage

### 5) Bench suite: 20 coding tasks
**Labels:** area/evals, kind/test, priority/P1  
**Milestone:** M1 — Week 1  
**Tasks**
- Add `bench/` with 20 tasks (bugfix, feature, refactor)
- Record expected output / pass criteria
**Acceptance**
- `make bench` runs and reports pass rate & latency

### 6) Asyncify LLM + I/O hot path
**Labels:** area/engine, kind/perf, priority/P0  
**Milestone:** M2 — Week 2  
**Tasks**
- Switch to `async` engine loop
- Use `httpx.AsyncClient` with connection pooling
- Make memory/vector I/O non-blocking
**Acceptance**
- Two concurrent prompts don’t block; P50 latency improves vs baseline

### 7) Background Memory Daemon (indexing queue)
**Labels:** area/memory, kind/perf, priority/P0  
**Milestone:** M2 — Week 2  
**Tasks**
- Worker for embeddings/indexing with batch writes + backpressure
- Non-blocking ingestion during interactions
**Acceptance**
- P95 latency unchanged during 100-doc ingest

### 8) Sandboxed code execution (separate process)
**Labels:** area/exec, area/tools, kind/feature, priority/P0  
**Milestone:** M2 — Week 2  
**Tasks**
- Execute in child process with CPU/mem/time limits
- Capture stdout/stderr/artifacts; ephemeral workspace cleanup
**Acceptance**
- Infinite loop doesn’t freeze agent; timeout summarized to LLM

### 9) Resource quotas & budgets
**Labels:** area/engine, kind/feature, priority/P1  
**Milestone:** M2 — Week 2  
**Tasks**
- Token, wall-clock, tool-call budgets per task
- Abort/fallback behavior when exceeded
**Acceptance**
- Runaway loops terminate gracefully with summary

### 10) Tool function-calling / JSON schema validation
**Labels:** area/tools, kind/feature, priority/P0  
**Milestone:** M3 — Week 3  
**Tasks**
- Expose tools via function-calling or strict JSON schema
- Validate/auto-repair malformed calls
**Acceptance**
- <2% malformed tool calls on bench

### 11) RAG: code & docs retrieval (one backend)
**Labels:** area/memory, kind/feature, priority/P0  
**Milestone:** M3 — Week 3  
**Tasks**
- Choose FAISS/Lance/Chroma and wire deeply
- Heuristic re-ranking (path/name/recency boosts)
**Acceptance**
- Retrieval MRR ≥0.75 on internal eval

### 12) Auto-context: retrieve before code edits
**Labels:** area/engine, area/memory, kind/feature, priority/P1  
**Milestone:** M3 — Week 3  
**Tasks**
- For code-mod tasks, auto-fetch target files/defs/usages
- Inject relevant snippets into prompt
**Acceptance**
- Bench success +10% on code-edit tasks vs no-RAG

### 13) Conversation summarization + cross-session recall
**Labels:** area/memory, kind/feature, priority/P1  
**Milestone:** M3 — Week 3  
**Tasks**
- Rolling summaries beyond token threshold
- Store tagged summaries, load on session start
**Acceptance**
- Long chats stay under limit with no quality drop (manual spot-check)

### 14) Planning step (task decomposition)
**Labels:** area/engine, kind/feature, priority/P0  
**Milestone:** M3 — Week 3  
**Tasks**
- Engine step 0: produce internal plan/TODO
- Optional display to user; cache plan in task context
**Acceptance**
- Plans generated for all complex tasks; improves bench pass rate

### 15) Self-critique & auto-repair loop
**Labels:** area/engine, area/exec, kind/feature, priority/P0  
**Milestone:** M3 — Week 3  
**Tasks**
- After action, run tests/linters/exec; summarize failures
- Up to K retries with targeted fixes
**Acceptance**
- +15–25% bench pass vs Week 1 baseline

### 16) Tool plugin system (v1)
**Labels:** area/tools, kind/feature, priority/P1  
**Milestone:** M3 — Week 3  
**Tasks**
- Define `Tool` interface; dynamic discovery (entry points/plugins dir)
- Migrate 2–3 built-ins to plugins
**Acceptance**
- Plugin tool loads without core changes; hot-reload in dev

### 17) Multi-agent skeleton (planner/coder/tester)
**Labels:** area/engine, kind/feature, priority/P0  
**Milestone:** M4 — Week 4  
**Tasks**
- Role prompts; simple orchestrator state machine
- In-proc message bus for tasks + artifacts
**Acceptance**
- 3 demo tasks complete plan→code→test without human help

### 18) Process isolation for roles + parallelism
**Labels:** area/engine, area/infra, kind/perf, priority/P1  
**Milestone:** M4 — Week 4  
**Tasks**
- Run coder & tester in separate processes
- Shared project store; quotas per role
**Acceptance**
- Parallel subtask speedup on multi-file changes

### 19) Caches: workspace, AST/index, doc fetch
**Labels:** area/perf, area/memory, kind/perf, priority/P1  
**Milestone:** M4 — Week 4  
**Tasks**
- Cache file listings, parsed ASTs, recent doc fetches
- Invalidate on FS change
**Acceptance**
- P50 ≤3.5s; P95 ≤8s on bench

### 20) Circuit breakers + retry/backoff
**Labels:** area/tools, area/engine, kind/feature, priority/P1  
**Milestone:** M4 — Week 4  
**Tasks**
- Per-tool error rate tracking; open/half-open/close
- Provider fallback routing
**Acceptance**
- 5% chaos (random tool failures) still yields successful completion

### 21) Observability: metrics & traces bundle
**Labels:** area/infra, kind/feature, priority/P1  
**Milestone:** M4 — Week 4  
**Tasks**
- Emit latency/tokens/tool counts/cache hits; trace IDs throughout
- Optional OTLP/Prometheus exporters
**Acceptance**
- Dashboards show per-turn metrics and spans

### 22) Performance hardening pass
**Labels:** area/perf, kind/perf, priority/P1  
**Milestone:** M4 — Week 4  
**Tasks**
- Profile hotspots (embedding, diffing, large files)
- Fix top 3; confirm idle RSS ≤200MB
**Acceptance**
- Meets North-Star latency + memory targets

### 23) Evals: nightly bench & soak
**Labels:** area/evals, kind/test, priority/P1  
**Milestone:** M4 — Week 4  
**Tasks**
- Nightly `bench` run + 2-hr soak; store trend charts
- Regressions break CI or open auto-issue
**Acceptance**
- Trend visible; regressions flagged automatically

### 24) Docs: architecture diagram + contributor guide
**Labels:** area/docs, kind/docs, priority/P1  
**Milestone:** M4 — Week 4  
**Tasks**
- Update README with architecture + flow diagrams
- “Write a Tool Plugin” and “Engine lifecycle” guides
**Acceptance**
- New dev can build/run in <10 minutes

### 25) Examples: bugfix, refactor, endpoint add
**Labels:** area/docs, kind/docs, priority/P2  
**Milestone:** M4 — Week 4  
**Tasks**
- `examples/` with 3 runnable recipes + expected outputs
**Acceptance**
- Examples pass locally + in CI

### 26) CI gates: typing, style, coverage ≥80%
**Labels:** area/infra, kind/test, priority/P1  
**Milestone:** M4 — Week 4  
**Tasks**
- Enforce mypy/ruff/coverage thresholds
- Protect `main` with required checks
**Acceptance**
- Red builds blocked from merge

### 27) Release engineering: version, notes, demo
**Labels:** area/infra, kind/docs, priority/P2  
**Milestone:** M4 — Week 4  
**Tasks**
- Bump version; CHANGELOG; short demo video/gif
**Acceptance**
- Tagged release with notes + assets

### 28) UX polish: diffs, tool call labels
**Labels:** area/ui, kind/feature, priority/P2  
**Milestone:** M4 — Week 4  
**Tasks**
- Clear diffs in outputs; show tool names/sources inline
**Acceptance**
- Human-readable outputs by default

### 29) Guardrails: deterministic settings + retries
**Labels:** area/engine, kind/feature, priority/P1  
**Milestone:** M4 — Week 4  
**Tasks**
- Default temp=0 for tool calls; exponential backoff
**Acceptance**
- Lower variance; fewer flaky failures on bench

### 30) Backlog seed: semantic code graph (tree-sitter/LSP)
**Labels:** area/memory, kind/feature, priority/P3  
**Milestone:** (Backlog)  
**Tasks**
- Spike: build call/def/use index; query API
**Acceptance**
- Prototype query works on sample repo

### 31) Native OpenAI client w/ routing fallback
**Labels:** area/engine, area/infra, kind/feature, priority/P0  
**Milestone:** M2 — Perf & Safety  
**Tasks**
- Add first-class OpenAI client (function/tool calling, responses API) alongside OpenRouter.
- Router: model alias → provider (OpenAI/OpenRouter/Anthropic/etc) with health checks.
- Config via env & YAML.
**Acceptance**
- Switching `PENGUIN_MODEL_PROVIDER=openai` works with zero code changes.
- Parity on bench; failures auto-fallback to secondary.

### 32) Harmony prompt format exploration (spec + A/B)
**Labels:** area/engine, area/evals, kind/feature, priority/P1  
**Milestone:** M3 — Capabilities  
**Tasks**
- Implement Harmony-style role blocks template alongside current.
- A/B on bench tasks; log token deltas & pass rates.
**Acceptance**
- Report: accuracy/latency deltas; template selectable per task.

### 33) Prompt templating à la Claude Code
**Labels:** area/engine, kind/feature, priority/P0  
**Milestone:** M3 — Capabilities  
**Tasks**
- Decompose prompts: system persona, coding rubric, repo context, task spec, guardrails.
- Macro slots: `<CONTEXT> <PLAN> <DIFF>`; deterministic tool-call subprompt.
**Acceptance**
- Template pack switch changes behavior without code edits.
- +10% pass on code-edit tasks vs Week 1 baseline.

### 34) Expose reasoning tokens in Web/API + docs
**Labels:** area/infra, area/ui, kind/feature, priority/P0  
**Milestone:** M4 — Multi-Agent & Release  
**Tasks**
- API surface: `reasoning_tokens_used`, `thinking_time_ms`, `steps`.
- Redact/obfuscate content as needed; config flag `EXPOSE_REASONING=true`.
- API reference + example responses.
**Acceptance**
- `/v1/tasks/{id}` shows metrics; docs updated.

### 35) Cross-language exploration plan
**Labels:** area/core, kind/spike, priority/P2  
**Milestone:** M4 — Multi-Agent & Release  
**Tasks**
- Spike doc: what to move to Rust/Go (diffing, AST index, sandbox runner).
- Prototype one component in Rust (e.g., fast unified diff) with Python bindings.
**Acceptance**
- Benchmark: ≥2–5× speedup vs Python impl; integration path documented.

### 36) Browser-use tools v2 (Playwright + heuristics)
**Labels:** area/tools, kind/feature, priority/P0  
**Milestone:** M3 — Capabilities  
**Tasks**
- Replace/augment with Playwright.
- Add actions: login flows, form fill, paginated scrape, semantic extract.
- Cache fetched pages; throttling & robots-respect toggle.
**Acceptance**
- 3 scripted web tasks pass reliably (docs search, auth page scrape, multi-page crawl).

### 37) Computer Use (containerized)
**Labels:** area/exec, area/tools, kind/feature, priority/P1  
**Milestone:** M4 — Multi-Agent & Release  
**Tasks**
- Headless X/wayland + VNC/noVNC inside Docker; tool for mouse/keyboard events.
- Strict sandbox; record/replay sessions; artifact export.
**Acceptance**
- Demo: open app, edit file, run tests inside container via agent.

### 38) Docker images for runners & dev
**Labels:** area/infra, kind/feature, priority/P0  
**Milestone:** M2 — Perf & Safety  
**Tasks**
- `penguin-runner` (minimal, sandbox, non-root) and `penguin-dev` (tools, playwright).
- Multi-arch build; pinned versions; SBOM; image scan in CI.
**Acceptance**
- `docker compose up` runs end-to-end locally; images published with hashes.

### 39) Inference backends: vLLM, SGLang, llama.cpp
**Labels:** area/engine, kind/feature, priority/P0  
**Milestone:** M3 — Capabilities  
**Tasks**
- Abstract `ModelClient` interface; adapters for vLLM, SGLang HTTP, llama.cpp server.
- Configurable batch size, KV cache, speculative/streaming.
**Acceptance**
- Swap backend via config; bench runs with open models successfully.

### 40) “Nervous system” event bus
**Labels:** area/core, kind/feature, priority/P0  
**Milestone:** M2 — Perf & Safety  
**Tasks**
- In-proc pub/sub: events `task.started`, `tool.done`, `plan.updated`, `error`.
- Typed payloads; wildcard subscriptions; backpressure.
**Acceptance**
- Tools/UI/memory react via events; no direct tight coupling.

### 41) Personality & preference profiles
**Labels:** area/engine, area/ui, kind/feature, priority/P1  
**Milestone:** M3 — Capabilities  
**Tasks**
- User/Workspace profiles: tone, verbosity, risk, ref style.
- Prompt conditioning + tool-policy tweaks based on profile.
**Acceptance**
- Switch profile → observable changes in responses & tool choices.

### 42) Automated DB backups + restore
**Labels:** area/infra, area/project-store, kind/feature, priority/P1  
**Milestone:** M4 — Multi-Agent & Release  
**Tasks**
- Snapshot SQLite/PG; rotate; encrypt (optional).
- `penguin backup create|list|restore`.
**Acceptance**
- Simulated corruption → restore succeeds; docs added.

### 43) RL suite for open models (coding tasks)
**Labels:** area/evals, kind/feature, priority/P2  
**Milestone:** M4 — Multi-Agent & Release  
**Tasks**
- Offline RL loop: logging trajectories, reward shaping (tests pass, compile).
- Support PPO/GRPO on small open models; export checkpoints.
**Acceptance**
- Training run improves pass rate on a micro-bench vs SFT baseline.

### 44) Cognition module (planning/critique libraries)
**Labels:** area/engine, kind/feature, priority/P0  
**Milestone:** M3 — Capabilities  
**Tasks**
- Encapsulate: planners (outline, itinerary), critics (lint/test/error), verifiers.
- Configurable policies (depth, retries, budgets).
**Acceptance**
- Engine uses module hooks; measurable quality lift on bench.

### 45) DSPy integration (programmatic prompting)
**Labels:** area/engine, kind/feature, priority/P1  
**Milestone:** M3 — Capabilities  
**Tasks**
- Add DSPy programs for retrieval chains & tool routing.
- Compare against hand-written prompts.
**Acceptance**
- Report on accuracy/latency deltas; toggle via config.

### 46) Mechanistic interpretability (open models only)
**Labels:** area/evals, kind/spike, priority/P3  
**Milestone:** M4 — Multi-Agent & Release  
**Tasks**
- Hook: capture activations/attention via vLLM/llama.cpp for small models.
- Simple probes on coding tokens (e.g., brackets, API call slots).
**Acceptance**
- Notebook + API endpoints to dump activations on a toy model; doc trade-offs.

### 47) MCP (Model Context Protocol) integration—client & server
**Labels:** area/engine, area/tools, kind/feature, priority/P0  
**Milestone:** M3 — Capabilities  
**Tasks**
- MCP client to call external tools/providers; MCP server to expose Penguin tools.
- Auth, schema, and capability discovery.
**Acceptance**
- Round-trip demo: external MCP tool used inside Penguin; Penguin tool consumed by another client.

### 48) API reference refresh incl. reasoning + MCP
**Labels:** area/docs, kind/docs, priority/P0  
**Milestone:** M4 — Multi-Agent & Release  
**Tasks**
- Document: reasoning metrics, event bus, multi-agent endpoints, MCP.
- Curl & SDK examples.
**Acceptance**
- Dev can build integration in <60 minutes from docs.

### 49) Container-safe “Computer Use” policy & monitor
**Labels:** area/exec, kind/feature, priority/P1  
**Milestone:** M4 — Multi-Agent & Release  
**Tasks**
- Guardrails: allowlist apps/paths, IO quotas, screen-capture scrubbing.
- Realtime monitor endpoint; kill-switch.
**Acceptance**
- Policy violations blocked & logged; kill-switch works in demo.

### 50) Model routing policy (cost/latency/quality)
**Labels:** area/engine, kind/feature, priority/P1  
**Milestone:** M2 — Perf & Safety  
**Tasks**
- Rules: simple Q→cheap-fast; complex edit→quality; tool-calls→function-capable.
- Collect per-model success/latency to update rules.
**Acceptance**
- Measurable cost ↓ on bench with equal/higher pass rate.

### 51) Dockerized Playwright + GPU variants
**Labels:** area/infra, kind/feature, priority/P1  
**Milestone:** M2 — Perf & Safety  
**Tasks**
- Image with Playwright deps & XVFB.
- Optional CUDA base for GPU-accelerated tasks (e.g., vision models).
**Acceptance**
- CI runs browser tests headless in container.

### 52) AST index (proto) for code navigation
**Labels:** area/memory, kind/feature, priority/P2  
**Milestone:** M4 — Multi-Agent & Release  
**Tasks**
- tree-sitter index: defs, refs, call graph; query API.
- Hybrid retrieval: AST filter → vector re-rank.
**Acceptance**
- “Find usages / modify API” tasks improve vs vector-only.

### 53) Database migrations & schema versioning
**Labels:** area/infra, area/project-store, kind/feature, priority/P1  
**Milestone:** M2 — Perf & Safety  
**Tasks**
- Alembic migrations (or equivalent); versioned schema.
- Upgrade/downgrade tested.
**Acceptance**
- Seamless upgrade across two versions in CI.

### 54) Personality profiles UI + API
**Labels:** area/ui, area/engine, kind/feature, priority/P2  
**Milestone:** M4 — Multi-Agent & Release  
**Tasks**
- Simple UI to set tone/verbosity/risk.
- Store per-user/workspace; reflect in prompts/tool limits.
**Acceptance**
- Live toggle changes behavior in-session.

### 55) Event-driven UI (subscribe to bus)
**Labels:** area/ui, area/core, kind/feature, priority/P1  
**Milestone:** M4 — Multi-Agent & Release  
**Tasks**
- WebSocket stream of event bus for UI: steps, tools, diffs, tests.
**Acceptance**
- UI timeline updates in real-time during a run.

### 56) Scheduled encrypted backups (S3/Local)
**Labels:** area/infra, kind/feature, priority/P2  
**Milestone:** M4 — Multi-Agent & Release  
**Tasks**
- Cron-style scheduler; encrypt with KMS or age; retention policy.
**Acceptance**
- E2E restore drill logged in CI.

### 57) RL logging & reward shaping API
**Labels:** area/evals, kind/feature, priority/P2  
**Milestone:** M4 — Multi-Agent & Release  
**Tasks**
- Log trajectories (prompt, actions, outcomes); pluggable reward functions.
- Export to parquet; starter notebook for PPO/GRPO.
**Acceptance**
- One open-model improves on micro-bench after short RL run.
