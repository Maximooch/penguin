# Penguin Dashboard Observability Plan

## Objective

Build Penguin's web dashboard as a local-first developer observability console for the Penguin runtime.

The goal is not to create another chat UI. The goal is to make Penguin's agent execution observable, debuggable, replayable, and trustworthy.

Short version:

> Penguin dashboard = local DevTools for AI agent execution.

It should answer questions like:

- Why did the agent stop?
- What context did the model actually see?
- Which tool call failed, retried, or hung?
- Did the backend emit truthful `busy -> idle` transitions?
- Did the TUI synthesize optimistic state that masked backend truth?
- Was a bad run caused by model latency, prompt bloat, context trimming, event-stream loss, a tool failure, or RunMode lifecycle bugs?
- Can this failed run be exported as a useful redacted debug bundle?

## Product Boundary: Penguin vs Link

Penguin and Link should overlap in runtime concepts, not in product shape.

Penguin dashboard:

- Local runtime observability and debugging for one Penguin runtime.
- Developer/operator audience.
- Can expose Penguin-native event names, traces, raw-ish tool records, and local debug artifacts.
- Optimized for debugging, runtime trust, and Penguin development.

Link:

- AI-native team workspace.
- Humans and agents share channels, tasks, files, permissions, workspace boundaries, audit trails, and review state.
- Agents are first-class accounts with capabilities, roles, permissions, and audit trails.
- Penguin is one registered runtime among future runtimes such as A2A, OpenCode, Codex, Claude SDK, and others.
- Link should consume Link-owned `RuntimeEvent` / `SessionEvent` projections, not raw Penguin or OpenCode event vocabulary.

Clean split:

```text
Penguin Runtime
  ├── native events
  ├── trace spans
  ├── logs
  ├── tool results
  ├── prompt/context snapshots
  └── local artifacts

        ↓ adapter / projection

Link RuntimeEvent / SessionEvent
  ├── team-safe audit trail
  ├── workspace permissions
  ├── human/agent collaboration
  ├── task review semantics
  └── cross-runtime abstraction
```

Penguin is the engine bay. Link is the operations center.

## Core Principle

Do not start with charts.

Start with a durable event and trace model. Charts built on untrustworthy events are decorative lies.

The observability stack should have four layers:

1. Events: what happened?
2. Traces: why did this run take this path, and where did time go?
3. Metrics: how often, how slow, how expensive, and how reliable?
4. Artifacts: what evidence was produced?

## Layer 1: Events

Events are the append-only timeline of runtime truth.

Examples:

```text
session.created
message.received
run.started
prompt.build.started
context.memory_retrieved
context.trimmed
model.request.started
model.response.delta
tool.call.started
tool.call.completed
clarification.requested
checkpoint.created
stream.reconnected
run.completed
run.failed
```

Events should be:

- append-only
- replayable
- correlated by stable IDs
- safe to inspect locally
- exportable for debugging
- clear about native vs normalized/projected shape

This is directly relevant to Penguin TUI upstreaming. Event replay, projector behavior, stream reconnection, stale stream detection, and optimistic TUI state are already known risk areas.

## Layer 2: Traces

A trace represents one full agent run or task execution.

Example:

```text
Trace: run_abc123
├── receive_user_message
├── build_prompt
│   ├── load_context_files
│   ├── retrieve_memory
│   ├── trim_context_window
│   └── serialize_messages
├── model_call
│   ├── provider
│   ├── model
│   ├── input_tokens
│   ├── output_tokens
│   └── latency
├── parse_tool_calls
├── execute_tool: read_file
├── execute_tool: edit_file
├── execute_tool: pytest
├── model_call
└── finish_task / finish_response / waiting_input / failure
```

Every run should have a waterfall. This is the highest-value developer debugging view.

Trace spans should capture:

- parent-child relationships
- start/end timestamps
- status
- duration
- span kind: model, tool, context, memory, task, stream, filesystem, browser, agent, etc.
- sanitized attributes
- artifact references
- error metadata

## Layer 3: Metrics

Metrics answer aggregate questions after events and traces are reliable.

Useful metrics:

- time to first token
- time to first tool call
- model latency by provider/model
- tool latency and failure rate
- total run duration
- prompt build duration
- context tokens by category
- context pressure over time
- stream reconnect count
- stale stream count
- clarification rate
- task `waiting_input` rate
- task pending-review rate
- token and estimated-cost usage by session/task/model
- malformed tool-call rate
- checkpoint rollback frequency
- test/lint/typecheck pass-after-edit rate

Metrics should be local-first. Avoid SaaS assumptions in the first version.

## Layer 4: Artifacts

Artifacts are the evidence behind a run.

Examples:

- full tool stdout/stderr
- diffs
- screenshots
- generated files
- test reports
- prompt metadata
- optional redacted/full prompt payloads
- context snapshots
- model request/response metadata
- checkpoint snapshots
- task evidence bundles
- raw event frames when debug capture is enabled

Artifacts should be referenced from events and spans rather than embedded everywhere.

## Main Dashboard Screens

### 1. Trace Explorer

The flagship observability screen.

Show a list of recent traces/runs with:

- status
- duration
- session
- task
- agent
- model/provider
- tool count
- model-call count
- token count
- estimated cost
- terminal state: completed, failed, cancelled, waiting_input, pending_review, stale, etc.

Trace detail should show:

```text
Run: fix-auth-test-abc123
Status: failed
Duration: 48.2s
Model calls: 3
Tool calls: 7
Tokens: 62k input / 4k output
Estimated cost: $0.38
Final state: waiting_input

Waterfall
00.000 user.message.received
00.018 prompt.build.started
00.133 context.retrieve_memory
00.246 context.trimmed 18k tokens removed
00.421 model.call.started
07.812 model.call.completed
07.840 tool.read_file.started
07.870 tool.read_file.completed
08.001 tool.pytest.started
38.422 tool.pytest.failed
39.120 clarification.requested
```

Clicking a span should reveal:

- inputs, redacted by default
- outputs or artifact links
- duration
- status
- token counts
- error metadata
- related events

### 2. Run Waterfall

A Chrome DevTools-style waterfall for agent execution.

Columns:

```text
Span                      Start     Duration   Status
prompt.build              0ms       420ms      ok
model.openrouter.call      421ms     7.3s       ok
tool.read_file             7.8s      31ms       ok
tool.pytest                8.0s      30.4s      failed
model.openrouter.call      39.0s     4.8s       ok
```

This should expose bottlenecks without guesswork.

### 3. Prompt and Context Inspector

For each model call, show:

- system prompt version/hash
- model/provider
- request parameters
- message count
- token counts by category
- context files included
- memory entries injected
- tool outputs included
- what was trimmed
- final serialized prompt preview behind explicit sensitive-content gates

Example:

```text
Context Budget
SYSTEM          12,410 tokens
CONTEXT         44,902 tokens
DIALOG          71,334 tokens
SYSTEM_OUTPUT    8,201 tokens

Trimmed
- tool output: pytest full log, 18,300 tokens
- old dialog: 12 messages, 9,100 tokens
```

This answers the common debugging question: why did the model forget or miss something?

### 4. Event Stream Debugger

Especially important for TUI upstreaming and Link projection work.

Show raw and normalized/projected events side by side:

```text
Raw Penguin Event                    Normalized UI Event
message.part.updated                 message.part.updated
session.status: busy                 run.state: running
stream.reconnected                   connection.state: reconnecting
finish_response marker stripped      text.delta.cleaned
```

Use this to debug:

- missing idle events
- duplicate message parts
- stale spinner behavior
- reconnect replay bugs
- optimistic TUI events masking backend truth
- mismatched session/message/part IDs
- projector ordering bugs

This should exist before any broad TUI rebase. Otherwise Penguin is flying blind.

### 5. Tool Call Inspector

For every tool call, show:

- tool name
- parameters, redacted
- cwd/workspace
- started/completed timestamps
- duration
- exit code or structured status
- stdout/stderr artifacts
- changed files
- diff preview
- structured output
- retry count
- permission approval, if any
- related task/session/agent IDs

Example:

```text
Tool: execute_command
Command: pytest tests/test_auth.py -q
Exit: 1
Duration: 12.8s
Failure class: test_failure
Artifacts:
- stdout.log
- junit.xml
- diff.patch
```

### 6. State Machine Viewer

Penguin has multiple state machines. Make transitions visible.

Task lifecycle example:

```text
created
→ running
→ waiting_input
→ resumed
→ pending_review
```

Run/stream lifecycle example:

```text
idle
→ pending
→ running
→ stale
→ reconnecting
→ running
→ completed
```

This catches a class of bugs where the UI and backend disagree.

### 7. Metrics Overview

Only build richer analytics once traces are trustworthy.

Useful panels:

```text
Reliability
- Runs: 284
- Success: 71%
- Failed: 12%
- Waiting input: 9%
- Cancelled: 8%

Latency
- p50 run: 21s
- p95 run: 4m 12s
- p95 model call: 38s
- p95 tool call: 92s

Cost / Tokens
- Total input tokens: 18.2M
- Total output tokens: 1.1M
- Avg tokens/run: 68k
- Top expensive sessions

Failures
- tool_error: 38
- model_timeout: 12
- context_overflow: 5
- permission_denied: 4
- malformed_tool_call: 3
```

## Agent Runtime Golden Signals

Traditional infrastructure has latency, traffic, errors, and saturation. Penguin needs agent-native equivalents.

### Latency

- time to first token
- time to first tool call
- model latency
- tool latency
- total run duration
- time stuck in `waiting_input`
- prompt build time
- memory retrieval time

### Reliability

- successful runs
- failed runs
- cancelled runs
- retries
- malformed tool calls
- tool failure rate
- event stream disconnects
- incomplete traces
- missing terminal events

### Cost / Tokens

- input tokens
- output tokens
- estimated cost
- context pressure
- tokens by category
- cost by provider/model
- cost by task/session

### Autonomy

- tool calls per run
- replans per run
- clarification requests per run
- human approvals per run
- manual interventions
- percent of runs reaching pending review
- percent of runs requiring resume

This is the metric category that tells whether Penguin is becoming more capable or merely more verbose.

### Quality Proxies

- tests passed/failed after code changes
- lint/typecheck outcomes
- revert frequency
- checkpoint rollback frequency
- task reopened after done/pending-review
- diff size vs task size
- repeated edits to the same file
- hallucinated file/tool references

These are imperfect, but better than vibes.

## Minimal Data Model

Keep it boring. Boring schemas survive.

Trace identity:

```json
{
  "trace_id": "trace_...",
  "run_id": "run_...",
  "session_id": "session_...",
  "conversation_id": "conv_...",
  "task_id": "task_...",
  "agent_id": "default",
  "parent_agent_id": null,
  "workspace": "/path/to/project",
  "started_at": "...",
  "completed_at": "...",
  "status": "completed"
}
```

Span shape:

```json
{
  "span_id": "span_...",
  "trace_id": "trace_...",
  "parent_span_id": "span_...",
  "name": "tool.execute",
  "kind": "tool",
  "started_at": "...",
  "ended_at": "...",
  "status": "error",
  "attributes": {
    "tool.name": "execute_command",
    "command.redacted": "pytest tests/test_auth.py -q",
    "exit_code": 1,
    "workspace": "/repo"
  },
  "artifact_ids": ["artifact_stdout_...", "artifact_stderr_..."]
}
```

Event shape:

```json
{
  "event_id": "evt_...",
  "trace_id": "trace_...",
  "span_id": "span_...",
  "session_id": "session_...",
  "agent_id": "default",
  "type": "tool.call.completed",
  "timestamp": "...",
  "payload": {
    "tool_name": "execute_command",
    "status": "failed",
    "duration_ms": 12830
  }
}
```

## OpenTelemetry Strategy

Support OpenTelemetry-style traces/spans, but do not contort Penguin's internal model just to satisfy a generic standard.

Recommended shape:

```text
Penguin internal trace/event schema
        ↓
OTLP exporter
        ↓
Jaeger / Tempo / Honeycomb / Datadog / local viewer
```

Benefits:

- Developers can use existing trace tooling.
- Advanced users can wire Penguin into their own observability stack.
- Link can ingest structured runtime traces later.
- Penguin avoids needing to build every trace visualization from scratch.

But the local Penguin dashboard should keep first-party views tailored to agent debugging. Generic tracing tools do not understand context trimming, tool calls, prompt assembly, clarification state, or RunMode truth.

## Storage Strategy

Local-first SQLite is enough for v1.

Suggested tables:

```text
observability_traces
observability_spans
observability_events
observability_metrics
observability_artifacts
observability_redactions
```

Retention settings should be explicit:

```text
Keep traces: 30 days
Keep full prompt bodies: off by default or 7 days when debug capture is enabled
Keep tool stdout/stderr: 14 days
Keep metrics rollups: 180 days
Export before deletion: optional
```

Do not accidentally build an infinite local telemetry trash compactor.

## Privacy and Redaction

This is non-negotiable.

### Default Mode

Store:

- span names
- durations
- statuses
- token counts
- tool names
- redacted params
- artifact references
- maybe file paths, depending on config

Avoid storing by default:

- full prompt bodies
- API keys
- full file contents
- secrets in env
- raw model responses with sensitive code
- raw SSE frames

### Debug Capture Mode

Opt-in mode can store:

- full prompt payloads
- full model responses
- full tool stdout/stderr
- context snapshots
- raw SSE frames
- provider request/response metadata

Debug capture should be visually obvious in the dashboard:

```text
⚠ Debug Capture Enabled
Full prompts, model responses, and tool outputs may be stored locally.
```

### Redaction Rules

Redact:

- `*_API_KEY`
- `Authorization`
- tokens
- cookies
- private keys
- `.env` values
- known credential patterns
- tool params named `content`, `patch`, `old_string`, `new_string`, or `new_content` unless explicitly expanded

Penguin already treats edit diagnostics carefully. Extend that discipline into observability.

## Developer Debugging Use Cases

### Why did the TUI spinner stop while the backend was still running?

Need:

- session status events
- SDK stream health
- last event timestamp
- local pending state
- synthetic optimistic events
- run-state derivation trace

### Why did the model make a dumb edit?

Need:

- exact model call metadata
- context included
- context trimmed
- tool outputs visible to the model
- system prompt version/hash
- model/provider parameters

### Why did task execution flatten into fake completion?

Need:

- RunMode state transitions
- task `status` and `phase`
- clarification events
- finish tool calls
- terminal vs non-terminal result classification

### Why did reconnect duplicate messages?

Need:

- raw event stream
- replayed events
- message IDs
- part IDs
- projector output
- optimistic client-generated IDs

### Why is this slow?

Need:

- waterfall
- model latency
- prompt build latency
- tool latency
- filesystem latency
- memory retrieval latency
- stream gap timestamps

### Why did this cost so much?

Need:

- tokens by model call
- context category breakdown
- repeated prompt rebuilds
- large tool outputs included
- memory/context injection size

## Suggested Architecture

```text
PenguinCore
  ├── emits runtime events
  ├── creates trace spans
  ├── records artifacts
  └── updates metrics

ObservabilityService
  ├── TraceRecorder
  ├── EventStore
  ├── MetricsAggregator
  ├── ArtifactStore
  ├── RedactionService
  └── Exporters
      ├── JSONL
      ├── OTLP
      └── Link adapter later

Web API
  ├── /api/v1/observability/traces
  ├── /api/v1/observability/traces/{id}
  ├── /api/v1/observability/events
  ├── /api/v1/observability/metrics
  ├── /api/v1/observability/artifacts/{id}
  └── /api/v1/observability/export

Dashboard
  ├── Trace Explorer
  ├── Run Waterfall
  ├── Event Stream Debugger
  ├── Tool Inspector
  ├── Context Inspector
  └── Metrics Overview
```

## MVP Plan

### Phase 1: Flight Recorder

Backend first.

- Add append-only event store.
- Add trace/span model.
- Correlate session/run/task/agent/message IDs.
- Capture model calls, tool calls, prompt/context build, RunMode transitions, stream transitions, and errors.
- Store locally in SQLite.
- Add basic redaction.
- Add retention config.

No fancy analytics yet.

### Phase 2: Trace UI

Build:

- trace list
- run detail
- span waterfall
- event timeline
- tool call detail
- model call metadata
- context/token summary
- artifact links

This immediately helps development.

### Phase 3: Stream / Projector Debugger

Build:

- raw event view
- normalized event view
- replay view
- connection state
- last-event timestamp
- duplicate/missing event detection
- synthetic event markers

This directly supports TUI upstreaming and Link runtime projection work.

### Phase 4: Metrics Rollups

Build local analytics:

- latency
- tokens/cost
- tool errors
- model errors
- task outcomes
- context pressure
- reconnect/stale stream counts
- clarification/manual-intervention rates

### Phase 5: Export and Integration

Add:

- JSONL export
- OTLP export
- redacted debug bundle export
- optional Link adapter/projection path

## Killer Feature: Share Debug Bundle

For a bad run, export a redacted bundle:

```text
trace.json
events.jsonl
spans.jsonl
redacted_prompt_metadata.json
tool_results/
artifacts/
environment.json
penguin_version.txt
```

This would make debugging Penguin dramatically easier.

The bundle should have explicit privacy modes:

- metadata-only
- redacted local debug
- full local debug, opt-in only

## What Not To Build

Avoid:

- a generic Grafana clone
- charts before trustworthy traces
- raw prompt storage by default
- Link team analytics inside Penguin's local dashboard
- raw Penguin/OpenCode event names as Link frontend contracts
- hidden synthetic TUI events
- vanity counters
- lifecycle lies around `done`, `completed`, `pending_review`, and `waiting_input`

If the observability layer lies about lifecycle truth, it is worse than no dashboard.

## Link Alignment Notes

Penguin-native event examples:

```text
message.part.updated
session.status
finish_response marker stripped
```

OpenCode-native event examples:

```text
message.part.delta
session.updated
```

Claude SDK / Codex / A2A will have their own vocabularies.

Link should project these into Link-native events such as:

```text
runtime.output.delta
runtime.tool.started
runtime.tool.completed
runtime.approval.requested
runtime.state.changed
session.artifact.created
```

Comparison:

| Concern | Penguin Dashboard | Link |
| --- | --- | --- |
| Scope | Local runtime | Team workspace |
| Audience | Developer/operator | Team/user/org |
| Event shape | Penguin-native + debug detail | Link-native normalized |
| Secrets | Local, opt-in debug | Strictly permissioned |
| Goal | Debug runtime behavior | Coordinate work |
| Analytics | Runtime performance | Team/agent productivity + audit |
| UX | DevTools | Agentboard/workspace |

## Open Questions

- Should Penguin's trace schema be internal-first with OTLP export, or OpenTelemetry-native from day one?
- What is the minimum event set needed to debug TUI optimistic state and replay bugs?
- Should prompt payload capture be per-session, per-run, or global debug mode?
- What retention defaults are safe enough for local development without silently eating disk?
- Which IDs should be canonical across session, conversation, task, run, trace, message, and part records?
- Should traces be stored in the existing project/task SQLite DB or a separate observability DB?
- How much event normalization should Penguin do internally versus leaving native truth exposed to the dashboard?
- What exact projection boundary should Link use when ingesting Penguin traces/events?

## Strategic Recommendation

Make Penguin's web dashboard an agent runtime observability console first and a control surface second.

Read-heavy first:

1. observe sessions
2. inspect traces
3. inspect tool/model/context behavior
4. debug event streams and lifecycle state

Control-light second:

1. answer clarifications
2. retry failed runs/tools
3. pause/resume agents
4. rollback checkpoints
5. export debug bundles

The wedge is debugging. The value is trust.

If a developer can open a failed run and see the exact trace, context, model calls, tool calls, event stream transitions, artifacts, cost, and lifecycle state, Penguin becomes much easier to improve. Link also gets a cleaner runtime projection foundation instead of inheriting invisible compatibility hacks.
