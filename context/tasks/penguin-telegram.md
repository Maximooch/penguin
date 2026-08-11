# Penguin Telegram Integration Plan

## Status

- Created: 2026-08-11
- State: active — Phases 0–5 baseline implemented; Phases 6–8 planned
- Owner: Penguin runtime and integrations
- Target: basic personal bot through Hermes-level Telegram parity
- Primary implementation language: Python
- Recommended Telegram library: `python-telegram-bot`

## Objective

Add Telegram as a first-class Penguin channel, beginning with a secure personal
DM bot and growing into the practical feature set provided by Hermes:

- DMs, groups, and forum topics
- stable Penguin session routing
- streaming responses and progress
- text, images, documents, voice, and outbound artifacts
- commands and interactive buttons
- allowlists, pairing, and remote permission controls
- polling and webhooks
- proactive and scheduled delivery
- restart-safe ingress and outbound delivery
- status, diagnostics, and recovery behavior

The result should feel like Penguin running through Telegram, not a separate bot
that happens to call Penguin.

## Executive Recommendation

Build a small channel platform inside Penguin, then implement Telegram as its
first external adapter.

Do not copy the Hermes adapter into `penguin/` and wire it directly to
`PenguinCore.process()`. Hermes's Telegram code depends on its gateway, session,
delivery, command, and platform contracts. Penguin needs equivalent behavior
through Penguin-owned boundaries.

The recommended sequence is:

1. Extract a transport-neutral chat service from the current HTTP route.
2. Add channel envelopes, session bindings, authorization policy, and durable
   ingress/outbound stores.
3. Port the reusable Telegram-specific mechanics and tests from Hermes.
4. Borrow OpenClaw's stronger durability and recovery invariants.
5. Add advanced media, voice, interactivity, and proactive delivery until the
   Hermes parity checklist is complete.

A basic bot should not wait for every parity feature. Each phase below is
intended to ship a useful, tested increment.

## Scope

### In Scope

- One configured Telegram bot account.
- Long polling as the default transport.
- Webhook transport as an optional production mode.
- Private chats, groups, supergroups, and forum topics.
- Numeric Telegram identities for authorization decisions.
- Stable Telegram address to Penguin session bindings.
- Session creation, reset, abort, model selection, and status commands.
- Mention-gated group behavior and bounded group context.
- Penguin answer streaming through throttled Telegram message edits.
- Tool progress, questions, approvals, and background completion notices.
- Inbound and outbound Telegram media supported by the parity phase.
- Durable ingress, deduplication, ordering, retries, outbound delivery, and
  restart recovery.
- Proactive sends and a home-channel destination for scheduled/background work.
- CLI/web status and diagnostics for configured Telegram support.
- Deterministic tests with an opt-in live Telegram smoke suite.

### Deferred Or Explicit Non-Goals

- Copying Hermes's entire gateway architecture.
- Running a second direct `PenguinCore` process beside `penguin-web`.
- Multiple Telegram bot accounts in the first parity milestone.
- OpenClaw-only breadth such as a Telegram Mini App/dashboard.
- Full Telegram Bot API rich-message blocks before ordinary HTML delivery is
  reliable.
- Every native Telegram action, including arbitrary polls, stickers, venues,
  channel posts, and topic administration.
- Using mutable Telegram usernames as security identities.
- Treating Telegram as authorization to bypass Penguin tool permissions.
- Making live Telegram tests the proof of correctness.

These can be revisited after Hermes parity is stable.

## Reference Implementations

### Hermes

Hermes is the primary implementation donor because it is Python-based and uses
`python-telegram-bot`.

Pinned audit reference:

- Commit:
  `9829746dfe3d5077f4f076e257505ec7f8feaa65`
- Telegram guide:
  <https://github.com/NousResearch/hermes-agent/blob/9829746dfe3d5077f4f076e257505ec7f8feaa65/website/docs/user-guide/messaging/telegram.md>
- Telegram adapter:
  <https://github.com/NousResearch/hermes-agent/blob/9829746dfe3d5077f4f076e257505ec7f8feaa65/plugins/platforms/telegram/adapter.py>
- Gateway tests:
  <https://github.com/NousResearch/hermes-agent/tree/9829746dfe3d5077f4f076e257505ec7f8feaa65/tests/gateway>
- License:
  <https://github.com/NousResearch/hermes-agent/blob/9829746dfe3d5077f4f076e257505ec7f8feaa65/LICENSE>

The local `reference/hermes-agent/` checkout is useful for exploration, but it
must be compared with the pinned upstream revision before code or tests are
ported.

### OpenClaw

OpenClaw is the reliability and behavior reference, not a direct code donor. Its
Telegram implementation is TypeScript and depends heavily on the OpenClaw
Plugin SDK.

Pinned audit reference:

- Commit:
  `f788af02383175164bb4562ce358f797fe498d04`
- Telegram guide:
  <https://github.com/openclaw/openclaw/blob/f788af02383175164bb4562ce358f797fe498d04/docs/channels/telegram.md>
- Telegram maintainer invariants:
  <https://github.com/openclaw/openclaw/blob/f788af02383175164bb4562ce358f797fe498d04/extensions/telegram/AGENTS.md>
- Telegram source and tests:
  <https://github.com/openclaw/openclaw/tree/f788af02383175164bb4562ce358f797fe498d04/extensions/telegram>
- License:
  <https://github.com/openclaw/openclaw/blob/f788af02383175164bb4562ce358f797fe498d04/LICENSE>

### Copy, Adapt, And Rewrite Policy

Port from Hermes where the code is predominantly Telegram-specific:

- identifier and topic normalization
- formatting and entity helpers
- UTF-16-aware length accounting and message splitting
- caption overflow behavior
- media classification and Telegram limits
- retry classification and network fallback helpers
- webhook and polling setup patterns
- command parsing and inline-keyboard helpers
- focused Telegram behavior tests

Rewrite against Penguin contracts:

- process lifecycle and cancellation
- session creation and persistence
- execution context and permission propagation
- questions and approvals
- tool and artifact events
- background work and proactive delivery
- ingress, delivery, and dead-letter persistence
- diagnostics and configuration

Use OpenClaw as a specification for:

- durable-before-ack ingress
- `update_id` idempotency
- per-chat/topic ordered lanes
- polling-offset safety
- retry leases and dead letters
- webhook authentication and body guards
- outbound fallback behavior
- restart recovery and poller-conflict handling

Both upstream projects are MIT licensed. Any copied or materially adapted source
or tests must retain the applicable copyright/license notice. Add a repository
third-party notice or file-level provenance where appropriate. Do not obscure
the source of copied tests.

## Current Penguin Substrate

Penguin already has much of the agent-facing runtime required by a channel:

- `PenguinCore` and `Engine` own the reasoning/tool loop.
- `ConversationManager` and `SessionManager` persist conversations.
- `get_session_request_gate()` serializes work for one session.
- direct stream callbacks expose assistant and reasoning chunks.
- canonical runtime events expose lifecycle, stream, tool, task, error, and
  user-input events.
- `ApprovalManager` and `QuestionManager` expose interactive runtime controls.
- FastAPI lifespan already owns construction and shutdown of the main core.
- Run Mode and background agents can emit completion state.

Relevant files:

- `penguin/web/app.py`
- `penguin/web/routes.py`
- `penguin/core_runtime/process_facade.py`
- `penguin/core_runtime/process_runtime.py`
- `penguin/core_runtime/process_lifecycle.py`
- `penguin/core_runtime/process_streaming.py`
- `penguin/system/runtime_events.py`
- `penguin/system/runtime_event_ledger.py`
- `penguin/security/approval.py`
- `penguin/security/question.py`
- `penguin/integrations/integrations.md`
- `context/rationale/penguin-service-topology.md`
- `context/tasks/testing-pyramid.md`

## Current Gaps

The current web chat handler in `penguin/web/routes.py` contains important
business logic that is not available through a channel-neutral service. Calling
`PenguinCore.process()` directly would skip or duplicate:

- execution-context construction
- per-session request locking
- directory and agent binding
- model and variant selection
- input/media normalization
- permission and approval policy
- request tracking, title refresh, and cleanup

Other material gaps are:

- no external channel envelope or capability contract
- no durable Telegram address to Penguin session binding
- no durable inbound update spool or outbound delivery outbox
- no pairing/authorized-identity store
- no general voice transcription or speech generation subsystem
- only limited text/image/document ingestion
- no complete first-class outbound artifact contract
- approval resolution does not currently suspend and resume/retry the original
  tool operation
- questions suspend execution and require a direct reply path that must bypass
  the normal session request gate
- no production gateway-style cron/reminder scheduler
- Run Mode has process-global state that needs isolation before multiple chats
  can safely run autonomous work concurrently

The redacted runtime event ledger is not a replacement for a channel ingress or
delivery store. It intentionally does not retain every private transport payload
needed to retry external delivery.

## Guiding Principles

1. Keep Telegram mechanics in `penguin/integrations/telegram/`.
2. Keep channel-neutral routing, state, and delivery semantics in a core channel
   package.
3. Keep HTTP and Telegram on the same chat/application service.
4. Run one main Penguin runtime process until cross-process session and event
   coordination is designed explicitly.
5. Default to deny for remote identities and groups.
6. Treat Telegram metadata and media as untrusted input.
7. Persist an inbound update before acknowledging it as accepted.
8. Serialize one chat/topic lane while allowing independent lanes to progress.
9. Never perform Telegram network calls synchronously inside Penguin's shared
   event-bus subscribers.
10. Keep live-provider and live-Telegram checks as opt-in smoke tests.
11. Prefer behavioral parity over preserving Hermes's internal structure.
12. Make configured integration failures visible through status and diagnostics.

## Target Architecture

```text
Telegram Bot API
  │
  ├── long polling
  └── authenticated webhook
          │
          ▼
TelegramAdapter
  - Bot API lifecycle
  - Telegram auth/policy projection
  - media download/upload
  - commands/callbacks
  - Telegram formatting
          │
          ▼
ChannelIngressStore
  - persist before acknowledgement
  - update_id dedupe
  - retry/lease/dead-letter state
  - per-address delivery lanes
          │
          ▼
ChannelManager
  - normalized inbound envelope
  - address/session binding
  - capability and policy enforcement
          │
          ▼
ChatService
  - execution context
  - session request gate
  - input normalization
  - PenguinCore.process()
  - cancellation and cleanup
          │
          ▼
PenguinCore → Engine → ConversationManager / ToolManager
          │
          ├── direct assistant/reasoning stream callback
          └── scoped canonical runtime events
                      │
                      ▼
ChannelPresentation + DeliveryStore
  - progress/final message planning
  - chunk/edit/media fallback
  - durable outbound retries
                      │
                      ▼
TelegramAdapter
```

### Runtime Topology Decision

Start the Telegram manager within the existing FastAPI lifespan in
`penguin/web/app.py`, sharing the same `PenguinCore` instance as HTTP/SSE.

Initial topology:

```text
one supervised penguin-web/gateway process
  ├── FastAPI
  ├── PenguinCore
  ├── Telegram polling or webhook adapter
  ├── channel ingress workers
  └── channel delivery workers
```

Only one process may own polling for a bot token. Do not start a second core or
poller from a standalone `penguin telegram run` command. A future gateway CLI
may be an alias over this same runtime composition.

## Package And File Layout

Proposed channel-neutral package:

```text
penguin/channels/
  __init__.py
  schema.py             # envelopes, addresses, attachments, deliveries
  service.py            # shared ChatService/application boundary
  manager.py            # channel registration, lifecycle, routing
  policy.py             # normalized identity/access policy
  presentation.py       # runtime events/results -> channel deliveries
  session_store.py      # channel address -> Penguin session binding
  ingress_store.py      # durable inbound work and leases
  delivery_store.py     # durable outbound outbox and dead letters
  errors.py             # explicit channel exceptions
```

Proposed Telegram integration:

```text
penguin/integrations/telegram/
  __init__.py
  config.py             # typed Telegram config and validation
  manager.py            # adapter lifecycle and account client
  adapter.py            # python-telegram-bot handlers and Bot API calls
  auth.py               # DM/group/pairing policy projection
  commands.py           # native command registration and dispatch
  callbacks.py          # questions, approvals, model/topic selection
  formatting.py         # HTML rendering, splitting, plain fallback
  media.py              # bounded download/upload and media normalization
  streaming.py          # throttled preview/progress editing
  network.py            # retry/error classification and proxy behavior
  webhooks.py           # thin webhook route and secret verification
  diagnostics.py        # status/probe snapshots
  errors.py             # explicit Telegram exceptions
```

Companion surfaces:

```text
penguin/web/integrations/telegram_webhook.py  # thin status/webhook routes
penguin/cli/telegram.py                         # setup/status/pairing/diagnostics
tests/channels/
tests/integrations/telegram/
```

Exact filenames may change, but the dependency direction may not:

```text
Telegram integration → channel facades → Penguin public/runtime services
```

The Telegram integration must not depend on arbitrary private state scattered
through `PenguinCore`, `Engine`, or `ToolManager`.

## Configuration Surface

Add a typed schema outside `penguin/config.py`; configuration loading and merge
logic may remain there, while dataclass/Pydantic definitions belong with the
channel integration.

Proposed shape:

```yaml
channels:
  telegram:
    enabled: false
    transport: polling          # polling | webhook
    token_env: TELEGRAM_BOT_TOKEN
    token_file: null

    dm_policy: allowlist        # pairing | allowlist | open | disabled
    allow_from:                 # numeric Telegram user ids only
      - 123456789

    group_policy: allowlist     # allowlist | open | disabled
    group_allow_from: []        # numeric Telegram user ids
    groups:
      "-1001234567890":
        enabled: true
        require_mention: true
        history_limit: 50
        prompt: null
        directory: null
        agent_id: null
        topics:
          "42":
            enabled: true
            require_mention: false
            prompt: null
            directory: null
            agent_id: null

    streaming:
      mode: progress            # off | edit | progress
      edit_interval_ms: 750
      include_reasoning: false

    media:
      max_download_mb: 20
      max_document_text_chars: 100000
      voice_transcription: false
      voice_replies: false

    permissions:
      mode: workspace           # read_only | workspace | full_access
      approvals:
        shell: ask
        fileWrite: ask
        fileDelete: ask
        gitPush: ask
        network: ask
        secrets: deny
        default: ask
      timeout_seconds: 300
      allow_yolo: false

    delivery:
      retry_attempts: 8
      dead_letter_after_hours: 24

    webhook:
      public_url: null
      path: /api/v1/integrations/telegram/webhook
      secret_env: TELEGRAM_WEBHOOK_SECRET

    proxy_url_env: null
    home_chat_id: null
    home_topic_id: null
```

Configuration invariants:

- `enabled: false` is the default.
- Tokens and webhook secrets come from environment variables, secret references,
  or guarded regular files. They are never returned through status endpoints.
- `dm_policy: open` requires an explicit wildcard acknowledgement rather than
  becoming open because an allowlist is empty.
- User and group authorization uses numeric IDs, not usernames.
- Group access and DM pairing are separate grants.
- Remote permission mode cannot exceed the instance-level permission ceiling.
- `PENGUIN_YOLO` must not silently make Telegram remote execution unrestricted.
- Webhook mode requires a secret.
- Polling and webhook mode cannot own the same token simultaneously.

Add an optional package extra after verifying the supported Python matrix:

```toml
telegram = [
  "python-telegram-bot[webhooks]<23",
]
```

Pin more tightly while initially porting Hermes tests, then widen only after the
supported dependency range is exercised in CI.

## Core Data Model

### Channel Address

A normalized destination/source independent of Telegram handler objects:

```text
ChannelAddress
  platform: "telegram"
  account_id: "default"
  chat_id: str
  topic_id: str | null
  peer_id: str | null
```

Use strings at the Penguin boundary so large signed Telegram IDs survive storage
and JSON round trips without coercion.

### Inbound Envelope

```text
InboundEnvelope
  event_id
  address
  sender identity
  occurred_at
  text/caption
  attachments
  reply/forward metadata
  command/callback metadata
  raw transport metadata subset
```

Do not persist a complete unbounded Telegram update when a normalized bounded
record is sufficient. Preserve the raw `update_id` and the fields required for
idempotency, reply routing, diagnostics, and recovery.

### Session Binding

```text
platform + account_id + chat_id + topic_id + configured DM scope
    → Penguin session_id + directory + agent_id + agent_mode
```

Store Penguin-generated UUID session IDs rather than encoding raw Telegram keys
as filesystem session IDs. `/new` creates a new Penguin session and atomically
updates the binding.

### Ingress Record

Minimum durable fields:

- platform/account/update ID
- normalized lane key
- bounded inbound envelope
- state: pending, claimed, completed, retry, dead
- claim owner and lease expiry
- attempt count and next-attempt time
- last error class and bounded message
- created/updated/completed timestamps

### Delivery Record

Minimum durable fields:

- stable delivery ID and idempotency key
- source session/request/runtime-event ID
- destination address
- delivery kind: text, edit, media, reaction, callback update
- bounded payload or artifact reference
- reply/topic metadata
- Telegram message ID after delivery
- state, lease, attempt count, next-attempt time, and last error
- created/updated/completed timestamps

### Supporting Caches

Use bounded caches only where Telegram cannot provide later lookup:

- observed messages for reply context
- sent messages for edit/reaction/topic recovery
- pairing codes and authorized identities
- group/topic names for diagnostics
- last successful home-channel destination

## Session And Topic Semantics

Safe defaults:

- A private chat binds per bot account and peer. Never share one DM session
  across different users.
- A group binds per group chat.
- A forum topic adds `message_thread_id` and receives its own session/lane.
- Group sender authorization is checked separately from the shared group session.
- Replies remain in the bound chat/topic session unless a command explicitly
  changes it.
- Same-lane work is serialized through the durable lane and Penguin's existing
  session request gate.
- Different sessions may execute concurrently within configured capacity.

Commands that change session state must operate on the same binding store as
ordinary messages. They must not maintain a second Telegram-only session map.

Question replies are exceptional: an answer to a suspended `QuestionManager`
waiter must resolve that waiter directly. Sending it through a new chat turn can
deadlock behind the original session gate.

## Security And Permission Model

Telegram exposes a local coding agent to a remote network. The security posture
must be stricter than the loopback web default.

Required controls:

- default-deny DM and group policies
- numeric immutable identity checks
- DM-only pairing grants
- separate group and sender allowlists
- mention gating for groups by default
- callback ownership validation using user, chat, topic, and request identity
- conservative remote execution context and permission ceiling
- explicit approvals for destructive/high-risk tools
- bounded message, callback, and media payloads
- MIME/magic checks and safe temporary-file handling
- filenames reduced to safe basenames
- no arbitrary local path access from Telegram payload metadata
- token/secret redaction in logs, events, status, and exceptions
- constant-time webhook secret comparison
- webhook body/time limits and failed-auth throttling
- outbound URL and local-file validation where supported
- rate limits per bot token and destination

Pairing authorizes communication; it does not grant group access, change the
permission mode, authorize approval callbacks for another person, or establish
an implicit proactive-delivery destination.

## Reliability Invariants

The channel layer must encode these invariants in tests:

1. Persist a polling/webhook update before acknowledging or advancing beyond it.
2. The same Telegram `update_id` is admitted at most once per bot identity.
3. Updates in one chat/topic lane are processed in order.
4. A failed lane does not block unrelated lanes.
5. Claims have leases and are recoverable after process death.
6. Successful completion is durable before an ingress record is discarded.
7. Outbound deliveries survive process restart.
8. Delivery retry honors Telegram `retry_after` and bounded backoff.
9. Retry transient network, `429`, and `5xx` failures.
10. Treat invalid token/not-found failures as fatal and surface them in status.
11. Surface `409` polling conflicts rather than hiding duplicate pollers.
12. Failed formatting retries through a safer representation, eventually plain
    text, without losing the final answer.
13. Streaming edits and final durable delivery use the same formatting/chunking
    rules.
14. Network calls execute in bounded workers, not shared event-bus callbacks.
15. Dead letters are visible, inspectable, and manually retryable.
16. Replaying a crashed inbound request must not silently repeat a known
    non-idempotent tool operation.

The last invariant requires coordination with Penguin request/tool lifecycle
records. An ingress record that crashed after starting a turn cannot always be
blindly replayed. It must either resume from durable Penguin state or surface a
recoverable/manual-retry outcome.

## Telegram UX And Feature Matrix

| Capability | Basic | Daily Driver | Hermes Parity |
|---|---:|---:|---:|
| Private text chat | yes | yes | yes |
| Stable session binding and `/new` | yes | yes | yes |
| Default-deny numeric allowlist | yes | yes | yes |
| Typing indicator | yes | yes | yes |
| Final text chunking/fallback | yes | yes | yes |
| Editable streaming answer | no | yes | yes |
| Tool/progress status | no | yes | yes |
| `/stop`, `/status`, `/model` | partial | yes | yes |
| Inbound photos | no | yes | yes |
| Bounded text documents | no | yes | yes |
| Groups and mention gating | no | yes | yes |
| Forum topic sessions | no | yes | yes |
| Pairing and guest policy | no | optional | yes |
| Inline questions | no | yes | yes |
| Resumable tool approvals | no | partial | yes |
| Webhooks | no | optional | yes |
| Durable ingress/outbox | minimal | yes | yes |
| Restart recovery/dead letters | no | yes | yes |
| Voice transcription | no | no | yes |
| Voice replies/TTS | no | no | yes |
| Broad media/file handling | no | partial | yes |
| Reactions/status reactions | no | optional | yes |
| Per-topic prompt/agent/skill binding | no | optional | yes |
| Proactive/background delivery | no | yes | yes |
| Scheduled/home-channel delivery | no | partial | yes |
| Polling, webhook, proxy diagnostics | minimal | yes | yes |
| Startup/recovery notifications | no | optional | yes |

## Implementation Phases

### Phase 0 — Shared Chat Service And Runtime Spike

Objective: establish the correct Penguin integration seam before writing bot
handlers.

Work:

- [x] Extract the reusable orchestration in
  `penguin/web/routes.py::handle_chat_message` into a typed application service.
- [x] Preserve execution context, session binding, request gate, model/variant,
  media normalization, permission policy, cancellation, and cleanup behavior.
- [x] Migrate the HTTP route to the new service without changing its contract.
- [x] Audit the WebSocket chat path and route it through the same service where
  feasible.
- [x] Define `ChannelAddress`, `InboundEnvelope`, attachments, stream updates,
  and delivery requests.
- [x] Add a minimal in-memory fake channel adapter for contract tests.
- [x] Verify one direct service call can stream and complete a Penguin response.
- [x] Verify same-session calls serialize and separate-session calls isolate.
- [x] Decide and test the supported `python-telegram-bot` version across Penguin's
  Python 3.9-3.12 package matrix.

Acceptance criteria:

- HTTP chat behavior remains compatible.
- The new service has no FastAPI request/response types in its public contract.
- A fake channel can execute, stream, cancel, and complete a Penguin turn.
- No Telegram-specific code exists inside `PenguinCore` or `Engine`.

### Phase 1 — Basic Personal DM Bot

Objective: ship the smallest secure, genuinely useful Telegram surface.

Work:

- [x] Add the optional `telegram` dependency extra.
- [x] Add typed disabled-by-default Telegram configuration.
- [x] Create and stop the Telegram manager from the application lifespan.
- [x] Support long polling for one bot token.
- [x] Validate the token and expose bot identity/status without exposing it.
- [x] Enforce a numeric DM allowlist before admitting work.
- [x] Normalize text updates into `InboundEnvelope`.
- [x] Persist a stable DM-to-Penguin session binding.
- [x] Route text through the shared chat service.
- [x] Show a typing indicator while Penguin runs.
- [x] Send final output with conservative 4,000-character chunking.
- [x] Render Telegram HTML with plain-text fallback.
- [x] Add `/start`, `/help`, `/new`, `/status`, `/stop`, and `/whoami`.
- [x] Handle provider/tool/runtime failures as errors, not assistant success text.
- [x] Add update-ID deduplication before exposing the bot beyond local testing.

Acceptance criteria:

- An allowed user can hold a multi-turn Penguin conversation from Telegram.
- An unlisted user cannot start a Penguin turn.
- Restarting Penguin retains the same bound session.
- `/new` creates and binds a fresh Penguin session.
- `/stop` cancels the active request for that session.
- Long responses arrive without parse errors or silent truncation.

### Phase 2 — Daily-Driver Streaming, Commands, And Basic Media

Objective: make Telegram pleasant enough for routine Penguin use.

Work:

- [x] Add throttled editable answer previews.
- [x] Add `progress` mode with one status/tool message and a clean final answer.
- [x] Keep reasoning hidden by default; expose only through explicit safe config.
- [x] Coalesce small deltas and limit edit frequency.
- [x] Rotate/chunk previews that exceed Telegram limits.
- [x] Fall back from edit failure to ordinary final delivery.
- [x] Register a native Telegram command menu.
- [x] Add `/model`, `/mode`, `/session`, `/goal`, and `/project` where Penguin has
  stable service contracts for them.
- [x] Download inbound photos into validated temporary files and pass them as
  Penguin image inputs.
- [x] Ingest bounded UTF-8 text documents as context.
- [x] Add a first-class outbound artifact projection for Penguin-generated images
  and files.
- [x] Preserve reply-to context for observed messages.
- [x] Clean all temporary media on success, failure, and cancellation.

Acceptance criteria:

- Streaming does not create an edit storm or block Penguin event subscribers.
- Text, tool progress, and final output stay scoped to the originating session.
- Photos reach Penguin's multimodal input path.
- Supported text documents are bounded and clearly attributed as untrusted input.
- Generated artifacts are delivered or produce a visible delivery failure.

### Phase 3 — Groups, Topics, Pairing, And Channel Policy

Objective: support shared Telegram spaces without session or authorization leaks.

Work:

- [x] Add DM policies: pairing, allowlist, open, and disabled.
- [x] Add one-hour, single-use pairing codes and approval CLI/API.
- [x] Keep pairing grants DM-only.
- [x] Add group allowlist and group-sender allowlist policy.
- [x] Default groups to mention-gated behavior.
- [x] Handle BotFather privacy-mode limitations clearly in diagnostics/docs.
- [x] Ignore commands addressed to another bot.
- [x] Create separate session bindings for groups and forum topics.
- [x] Preserve topic IDs on typing, replies, edits, and final sends.
- [x] Add bounded rolling group context for observed messages.
- [x] Support per-group/topic prompt, directory, agent, mode, and skill binding.
- [x] Add `/activation mention|always` and `/topic` behavior where appropriate.
- [x] Handle supergroup ID migration without losing bindings.

Acceptance criteria:

- One DM user cannot see or affect another user's session.
- Two groups and two topics remain isolated under concurrent load.
- Unauthorized senders cannot trigger Penguin in an allowed group.
- Mention gating behaves correctly with Telegram privacy mode enabled and disabled.
- Group/topic configuration is resolved deterministically and fails closed.

### Phase 4 — Interactive Questions And Resumable Approvals

Objective: make Penguin's interactive safety model usable from Telegram.

Work:

- [x] Project `QuestionManager` prompts as Telegram messages with inline choices.
- [x] Route free-text question replies directly to the pending waiter.
- [x] Ensure question replies do not deadlock behind the session request gate.
- [x] Add callback ownership checks and single-use callback records.
- [x] Project tool approval requests with approve/deny buttons.
- [x] Add session/request/tool identity to approval callback payload records.
- [x] Implement resumable approval semantics so approval can continue or retry the
  original tool operation safely.
- [x] Expire stale questions/approvals and update their Telegram messages.
- [x] Add callback unregister/cleanup behavior for application shutdown.
- [x] Prevent approval command text from leaking into unauthorized groups/topics.

Acceptance criteria:

- A pending question can be answered with a button or text without creating a
  second model turn.
- Only the authorized recipient can resolve a callback.
- Approve resumes the intended operation at most once; deny does not execute it.
- Restart or expiry produces a clear terminal state rather than a hanging button.

### Phase 5 — Durable Delivery And Restart Recovery

Objective: make Telegram reliable enough for long-lived/background Penguin work.

Work:

- [x] Implement the SQLite channel session-binding store.
- [x] Implement durable ingress admission, claims, leases, retry, and dead letters.
- [x] Persist updates before advancing the polling watermark.
- [x] Implement per-chat/topic lane scheduling.
- [x] Implement the durable outbound delivery store and bounded workers.
- [x] Classify Telegram retryable, fatal, rate-limit, and polling-conflict errors.
- [x] Honor `retry_after` and use bounded jittered backoff.
- [x] Recover expired ingress and delivery leases on startup.
- [x] Add dead-letter list, inspect, retry, and discard operator controls.
- [x] Detect duplicate token/poller ownership.
- [x] Add authenticated webhook mode using the same ingress path as polling.
- [x] Return webhook success only after durable adoption.
- [x] Add webhook body limits, timeouts, and constant-time secret verification.
- [x] Define crash behavior for turns that may have started non-idempotent tools.

Acceptance criteria:

- Killing Penguin after ingress admission does not lose the update.
- Restarting after an outbound network failure eventually delivers or dead-letters
  the result.
- Duplicate updates do not execute duplicate completed turns.
- One blocked lane does not stall unrelated chats.
- Polling and webhook paths pass the same normalized ingress contract tests.

### Phase 6 — Voice, Files, Reactions, And Media Parity

Objective: reach Hermes-level conversational media support.

Work:

- [ ] Introduce a provider-neutral audio transcription service.
- [ ] Support a local transcription backend and configured remote providers.
- [ ] Treat transcripts as machine-generated, untrusted input.
- [ ] Support voice/audio mention detection only under an explicit policy.
- [ ] Add optional TTS and Telegram voice-bubble delivery.
- [ ] Support common document, audio, video, and media-group inputs safely.
- [ ] Define which binary documents are parsed, attached as artifacts, or rejected.
- [ ] Expand outbound artifact delivery for photo, document, audio, voice, and
  video where Penguin can produce them.
- [ ] Add caption overflow and media fallback behavior.
- [ ] Add processing/done/error reactions with conservative defaults.
- [ ] Add reply, edit, pin, and deletion actions required by Hermes parity.
- [ ] Support proxy configuration and optional local Telegram Bot API deployment.

Acceptance criteria:

- Voice notes can be transcribed into a clearly marked Penguin input.
- Optional voice replies play as Telegram voice messages.
- Unsupported or oversized media fails clearly and leaves no temporary files.
- Media sends use safe fallbacks and do not discard accompanying text.
- Reaction/status behavior respects authorization and Telegram capabilities.

### Phase 7 — Proactive Delivery And Automation

Objective: make Telegram an outbound Penguin destination, not only a request/
response surface.

Work:

- [ ] Add an explicit channel destination model usable by Run Mode, goals,
  projects, background agents, and notifications.
- [ ] Add `home_chat_id`/`home_topic_id` configuration and validation.
- [ ] Deliver background completion, failure, and attention-required events.
- [ ] Persist proactive messages through the same delivery outbox.
- [ ] Add explicit CLI/API sends to a configured Telegram destination.
- [ ] Define safe last-used destination semantics without treating pairing as
  proactive-send consent.
- [ ] Add a durable scheduler for one-shot reminders, intervals, and cron jobs, or
  integrate Telegram delivery with Penguin's chosen supervised timer model.
- [ ] Bind scheduled runs to explicit Penguin session modes and destinations.
- [ ] Add startup/recovery notification policy and quiet modes.
- [ ] Ensure concurrent autonomous runs do not share global Run Mode callbacks.

Acceptance criteria:

- A background run can complete after the originating Telegram request and still
  deliver its result after restart.
- Scheduled delivery always names an explicit authorized destination.
- Pairing alone never causes unsolicited scheduled messages.
- Delivery failures are visible and recoverable through the outbox/dead-letter
  controls.

### Phase 8 — Hermes Parity Hardening

Objective: close the feature matrix, operational, documentation, and QA gaps.

Work:

- [ ] Audit every capability in the pinned Hermes Telegram documentation.
- [ ] Port remaining relevant Hermes Telegram tests with attribution.
- [ ] Test polling, webhook, proxy, and local Bot API configurations.
- [ ] Add notification modes, edited status, pins, and recovery notices.
- [ ] Complete command menu validation, help text, and access tiers.
- [ ] Add model picker, topic skill binding, and per-channel prompt behavior.
- [ ] Add setup, status, probe, doctor, pairing, and dead-letter CLI flows.
- [ ] Add actionable diagnostics for token, permissions, privacy mode, webhook,
  network, polling conflicts, and delivery backlog.
- [ ] Add systemd-user and launchd guidance using Penguin's single-gateway model.
- [ ] Complete security audit and fault-injection campaign.
- [ ] Run opt-in live Telegram smoke tests and capture the verification matrix.
- [ ] Update README, configuration reference, web docs, and architecture docs.
- [ ] Produce a final documented list of intentional Hermes divergences.

Acceptance criteria:

- Every Hermes parity matrix row is implemented, explicitly waived, or documented
  as an intentional Penguin difference.
- All deterministic channel tests pass without network/provider access.
- Live smoke tests cover one DM, one group, one topic, media, callback, polling,
  webhook, restart recovery, and proactive delivery.
- No business logic has leaked back into HTTP or Telegram route handlers.

## Testing Strategy

Follow `context/tasks/testing-pyramid.md`. Provider and transport reliability must
be proven with deterministic tests before live checks.

### Unit Tests

- config validation and secret precedence
- numeric identity and allowlist normalization
- address/lane/session key resolution
- group/topic policy inheritance
- command parsing and callback ownership
- Markdown-to-HTML rendering and plain fallback
- UTF-16 length accounting and message/caption splitting
- media type/size/name validation
- Telegram error classification and backoff
- delivery planning from runtime events/results

### Property Tests

- arbitrary Unicode chunks never exceed Telegram limits
- formatting fallback preserves visible text
- address normalization is stable across serialization
- topic/group/DM keys cannot collide
- configuration merges never broaden access accidentally
- retry schedules remain bounded and monotonic

### State-Machine Tests

- ingress pending/claim/lease/retry/complete/dead transitions
- delivery pending/claim/retry/sent/dead transitions
- crash before and after durable ingress acknowledgement
- crash before and after Telegram send acknowledgement
- duplicate updates and delivery idempotency
- lane ordering and unrelated-lane progress
- webhook/polling transport replacement and `409` conflicts
- question and approval pending/resolved/expired transitions

### Contract Tests

- fake `python-telegram-bot` update to normalized `InboundEnvelope`
- channel address to Penguin session binding
- ChatService execution-context and permission propagation
- direct stream callback to throttled Telegram edits
- canonical runtime event to tool/progress/background delivery
- media download to Penguin input and artifact to Telegram output
- polling and webhook parity through the same ingress worker

### Hermetic Integration Tests

Use a fake LLM/provider and fake Telegram Bot API to cover:

- multi-turn DM conversation and `/new`
- simultaneous isolated chats and serialized same-chat turns
- group mention and topic routing
- provider failure and next-turn recovery
- abort during streaming/tool execution
- question and approval callbacks
- restart with pending ingress/outbound work
- photo/document/voice processing and cleanup
- proactive delivery after the original request completes

### Fault Injection

- incomplete model streams
- provider errors and timeouts
- Telegram `429`, `5xx`, `401`, `404`, and `409`
- malformed Telegram HTML/entity rejection
- edit-message failure after partial streaming
- database busy/I/O failure
- expired leases and process restart
- deleted or missing artifact files
- media download interruption and oversized bodies
- callback replay and wrong-user callback attempts

### Opt-In Live Telegram Smoke Tests

Live tests require explicit environment variables and are never part of the
default suite.

Suggested gates:

```text
PENGUIN_LIVE_TELEGRAM=1
TELEGRAM_BOT_TOKEN=...
TELEGRAM_TEST_USER_ID=...
TELEGRAM_TEST_CHAT_ID=...
TELEGRAM_TEST_TOPIC_ID=...
```

Live tests should create identifiable messages, clean up when possible, avoid
destructive tools, and document any Telegram/BotFather setup requirements.

## Observability And Operations

Expose a bounded, redacted status snapshot:

```json
{
  "enabled": true,
  "transport": "polling",
  "bot_id": "123456789",
  "bot_username": "penguin_example_bot",
  "state": "running",
  "last_update_at": "...",
  "last_success_at": "...",
  "ingress_pending": 0,
  "deliveries_pending": 0,
  "dead_letters": 0,
  "last_error": null
}
```

The token, webhook secret, proxy credentials, private message bodies, and local
artifact paths must not appear in status or routine logs.

Recommended operator commands:

```text
penguin telegram status
penguin telegram probe
penguin telegram pairing list
penguin telegram pairing approve <code>
penguin telegram deliveries list
penguin telegram deliveries retry <id>
penguin telegram doctor
```

If these commands are implemented under a future generic channel CLI, keep
equivalent discoverability.

## Documentation And Packaging

Required documentation:

- BotFather bot creation and privacy-mode setup
- optional dependency installation with `uv`
- safe token/secret configuration
- numeric user, group, and topic ID discovery
- DM allowlist and pairing setup
- group mention and privacy-mode behavior
- polling versus webhook operation
- reverse-proxy and webhook-secret setup
- permission and approval behavior for a remote bot
- supported media and configured limits
- home-channel and scheduled-delivery consent
- status, logs, recovery, and dead-letter operations
- launchd/systemd-user single-gateway deployment
- local Telegram Bot API server limitations and trust boundary

Packaging requirements:

- Telegram remains optional when unconfigured.
- Missing optional dependencies produce one actionable error.
- Importing Penguin without the Telegram extra continues to work.
- The extra participates in supported Python-version CI.
- Public modules define `__all__`.
- Upstream MIT notices/provenance are included where code/tests are ported.

## Estimated Effort

These are cumulative one-engineer estimates and assume the core Penguin provider
and tool runtime remain functional:

| Milestone | Estimate |
|---|---:|
| Phase 0-1 basic personal bot | 1-2 weeks |
| Phase 0-2 daily-driver bot | 3-5 weeks |
| Through groups, approvals, and durability | 7-10 weeks |
| Hermes parity, including voice and proactive delivery | 10-14+ weeks |

The scheduler, resumable approvals, voice services, and first-class artifact
contract are Penguin-wide work. If those become separate generalized projects,
calendar time may increase even though the Telegram-specific adapter becomes
smaller.

## Recommended Pull Request Sequence

1. Shared `ChatService` extraction and HTTP contract regression tests.
2. Channel schemas, fake adapter, session binding, and policy contracts.
3. Basic Telegram polling DM bot and commands.
4. Formatting, streaming, photos/documents, and artifact projection.
5. Groups, topics, mention policy, and pairing.
6. Questions and resumable approvals.
7. Durable ingress, outbox, retry/dead-letter state machines, and webhooks.
8. Voice/media/reactions and network deployment options.
9. Proactive delivery, scheduler integration, and Run Mode isolation.
10. Hermes parity audit, diagnostics, packaging, docs, and live smoke evidence.

Each pull request should leave the repository green and independently improve a
shippable configuration. Avoid a single long-lived parity branch.

## Main Risks

### Architectural Risks

- Duplicating the web chat handler inside Telegram.
- Calling `PenguinCore.process()` without required request scoping.
- Running two cores against the same file-backed session state.
- Blocking the shared event bus on Telegram network I/O.
- Leaking runtime events between sessions due to missing scope filters.
- Creating a Telegram-only command/session system that drifts from other clients.

### Reliability Risks

- Duplicate Telegram updates repeating non-idempotent tool work.
- Advancing polling offsets before durable admission.
- Losing final output after the Penguin turn commits.
- Edit storms or rate-limit loops during streaming.
- Malformed formatting dropping an otherwise valid final answer.
- Stale callbacks approving the wrong request.
- Global Run Mode state routing completion to the wrong chat.

### Security Risks

- Open or username-based authorization defaults.
- Remote Telegram users inheriting permissive local/YOLO execution.
- Cross-user DM session reuse.
- Group members resolving another user's question or approval.
- Unbounded file/media download and unsafe local-path handling.
- Secrets appearing in config responses or logs.
- Treating pairing as consent for unsolicited proactive messages.

### Maintenance Risks

- Copying one large Hermes adapter instead of smaller owned modules.
- Porting tests without recording their upstream revision.
- Telegram Bot API/library changes invalidating behavior silently.
- Coupling parity to optional features without a stable Penguin-wide contract.

## Open Questions

Resolve these before or during the named phase, not all before Phase 1:

1. Should the shared application boundary be named `ChatService`,
   `InteractionService`, or a broader `ChannelExecutionService`?
2. Should channel SQLite state use one database with multiple tables or separate
   binding/ingress/delivery databases?
3. Which workspace path owns channel state and retention configuration?
4. Is pairing necessary for the first public release, or is an explicit numeric
   allowlist sufficient until Phase 3?
5. Which STT/TTS providers are acceptable defaults, and which remain extras?
6. What exact tool operation record is required to resume approved work safely?
7. Which Penguin artifacts are stable enough for reliable outbound delivery?
8. Should cron live inside Penguin or remain supervised through launchd/systemd
   timers that call a Penguin command?
9. Which commands are channel-neutral and which remain Telegram-specific?
10. What portion of group history belongs in persisted conversation context versus
    ephemeral Telegram context?
11. Should per-topic agent/directory/skill bindings be config-only initially or
    mutable through owner commands?
12. What retention and redaction policy applies to inbound/outbound channel rows?

## Definition Of Done

Hermes-level Penguin Telegram support is complete when:

- [ ] A fresh user can install the optional extra, create/configure a bot, and
  diagnose setup using documented commands.
- [ ] DMs, allowed groups, and forum topics route to isolated durable Penguin
  sessions.
- [ ] Text, images, bounded documents, voice, and supported files work with clear
  limits and cleanup.
- [ ] Streaming, tool progress, formatting fallback, replies, and final artifacts
  behave reliably.
- [ ] Commands, model selection, questions, and resumable approvals use Penguin's
  canonical services.
- [ ] Authorization fails closed and remote permissions cannot exceed configured
  Penguin policy.
- [ ] Polling and authenticated webhooks share durable ingress semantics.
- [ ] Duplicate updates, restarts, rate limits, and network failures cannot
  silently lose committed results.
- [ ] Background and scheduled work can deliver through an explicit authorized
  home destination.
- [ ] Status, probe, doctor, pairing, outbox, and dead-letter controls are usable.
- [ ] Deterministic unit, property, state-machine, contract, integration, and
  fault-injection suites pass.
- [ ] Opt-in live smoke evidence covers the critical Telegram surfaces.
- [ ] Upstream attribution is preserved for copied/adapted Hermes/OpenClaw work.
- [ ] README, user docs, architecture docs, and configuration references match
  runtime truth.
- [ ] Any intentional difference from the pinned Hermes behavior is documented.
