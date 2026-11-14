# Correct All Implicit State Machines

Status: backlog, not started (written 2026-11-13)
Related: `testing-pyramid.md`, `llm-provider-contract.md`, `message-loop-reliability.md`, `model-config-mutation-state-leak.md`, `prototypes/bend_runtime/README.md`

## Objective

Work through every implicit state machine found in the 2026-11-11 sweep, in
order of importance, in a near-continuous loop. An implicit state machine is a
lifecycle whose state is spread across flags, optional fields, string literals,
counters, dict membership or call ordering, with no single place that decides
which transitions are legal.

"Correct" means one of these, whichever is smallest:

- The illegal state can no longer be represented.
- Every transition goes through one function that rejects illegal moves.
- Duplicated copies of the same decision are replaced by one shared function.
- The machine is dead code and is deleted.

It does not mean "add an enum and a transition table to everything".

## Where the list came from, and how far to trust it

- Six read-only sweeps covered `penguin/` on branch
  `penguin/pullfrog-permission-runtime`, on top of `36e32f623`, with uncommitted
  changes present. Line numbers are from that tree and will drift.
- Nothing was executed. Every entry is a claim from reading code.
- Entries marked **[confirmed]** were re-read by a second pass. Entries marked
  **[inferred]** depend on behaviour outside the code that was read.
- Everything else is unconfirmed. Treat each entry as a hypothesis until step 2
  of the loop reproduces it.
- Not opened at all: `penguin/cognition/`, `penguin/dashboard/`,
  `penguin/server/ws_server.py`, `penguin/memory/providers/`,
  `penguin/multi/admission.py`, `penguin/multi/routing.py`,
  `penguin/system/runtime_event_ledger.py`, `penguin/security/mcp_isolation.py`,
  `penguin/security/tool_capabilities.py`, the modal / runinfra / ollama
  adapters. A second sweep of these belongs at the end of the backlog.

## The loop

One iteration handles one backlog item. Take the first unchecked item whose
`Blocked by` items are done.

1. **Re-read.** Open the cited code at the current commit. If the code has
   changed so the entry no longer applies, mark it `stale` with one line of
   explanation and go to the next item.
2. **Reproduce as a failing test.** Write the smallest deterministic test in
   `tests/` that fails because of the gap. Follow `testing-pyramid.md`: fake
   providers, contract tests, state-machine tests and fault injection before
   anything live. If no failing test can be written in a reasonable attempt,
   mark the item `not reproduced`, record what was tried, and go to the next
   item. Do not change product code for a gap that was not reproduced.
3. **Fix at the root.** Make the smallest change that turns the test green
   under the definition of "correct" above. Respect `AGENTS.md`: no logic in
   `core.py`, business logic out of `web/routes.py`, raise `PenguinError`
   subclasses, no file past about 2000 lines.
4. **Show the guard can fail.** Revert the fix locally, confirm the new test
   goes red, restore the fix. Never do this with a test that runs real
   handlers once the guard is gone: on SM-03 that started a headless browser.
   Revert against a narrow, side-effect-free subset instead.
5. **Bend lane, shape (a) items only.** If the item is tagged `bend`, add a
   pure projection, `LAWS.bend`, `PROOF.bend` and an opt-in differential test
   under `prototypes/`, following `prototypes/bend_runtime/`. Bend stays an
   optional assurance lane: no runtime dependency, tests skip without
   `PENGUIN_TEST_BEND=1`.
6. **Verify.** Run the item's test file, then the suites for the touched
   package, then `ruff check` on touched files. Record the commands and
   results in the item's log line.
7. **Record.** Tick the item, add the commit hash and one line on what
   changed. One item per commit.

### Stop and ask a human when

- The baseline suite for the touched package is already red before the change.
- The fix changes behaviour a user or an API client can observe (status
  strings, HTTP codes, event order, permission outcomes) beyond the correction
  named in the item. The named correction itself is pre-approved (agreed
  2026-11-13).
- The item is tagged `design`: more than one reasonable fix exists and the
  choice shapes later items.
- The diff for one item passes roughly 300 changed lines outside tests.
- Three consecutive items end as `not reproduced` or `stale`. The list is
  probably out of date and needs a fresh sweep.
- A fix needs a second item's files that another item in progress also edits.

### Decisions the loop needs before it starts

Recommended defaults are given; change them here.

| Decision | Recommended default |
|---|---|
| Starting tree | Land or stash the current uncommitted work first. It touches `openai.py`, `openrouter.py`, `tool_manager.py`, `async_dispatch.py`, `providers/mcp.py`, `config.py` and `model_runtime.py`, which this backlog also edits. |
| Branching | One branch, `FV/squash-implicit-state-machines`, cut from `origin/main` at `42007c0ef`. One commit per item, grouped by tier in one large PR (Maximus, 2026-11-13). SM-01 and SM-02 landed on main before the branch. |
| Commit and push | The loop commits locally. It does not push or open PRs without being told to. |
| Autonomy | Maximus is away (2026-11-13): keep going, stop only when input is truly required. Where a `design` item has a reasonable reversible answer, implement it and list it under "Decisions taken while away"; otherwise mark the item `on hold` and move on. |
| Behaviour changes | Stop and ask (see above). |
| Bend | Only for items tagged `bend`. |

## Decisions taken while away

One line each, newest last, for review. Each is one commit and can be reverted
on its own.

- SM-03: under a restricted startup allowlist, an action tag is allowed only if
  its own name, or the tool it aliases to, is on the list. Control actions such
  as `finish_response` get no exemption, matching `execute_tool`. An allowlist
  that omits them cannot end a turn through action tags.
- SM-03: an `ImportError` from the agent permission module now denies, like any
  other failure of that check.
- SM-04: a wider scope that cannot be honoured (SESSION with no session id,
  PATTERN with no pattern) is granted and recorded as ONCE with a warning. The
  item said "reject"; rejecting would leave the user's click with no effect.
- SM-04: resolved approval history is capped at 1000 entries
  (`MAX_RESOLVED_HISTORY`); the oldest are dropped.

## Item format

`- [ ] SM-nn Name (shape) [tags]`, then location, the gap, and the intended
correction. Shape: **a** pure decision, **b** sequential lifecycle, **c**
concurrent protocol.

Tags: `confirmed`, `inferred`, `bend`, `design`, `security`.

## Tier 0: wrong side effects, permission errors, lost history

- [x] **SM-01 Ordered-batch child result status** (a) [confirmed, security, bend]
  - `penguin/tools/tool_manager.py:4297`, `penguin/tools/runtime.py:29,1769`
  - A child returning `{"status": "pending_approval"}` is recorded as
    `completed`, so `stop_on_error` does not stop and later children run. Three
    vocabularies exist (`pending_approval`, `requires_approval`,
    `ApprovalStatus.PENDING`) and two mappers disagree.
  - Correction: one mapper from tool output to `ToolResultStatus`; any status
    that is not a known success is not `completed`.
  - Found on re-read: the executor also halted only on `status == "error"`, so
    a correctly mapped `requires_approval` child would still not stop the batch.
  - State: fixed and committed locally. Laws in
    `prototypes/bend_tool_status/LAWS.bend` were drafted by Claude and await
    Maximus's review.
- [x] **SM-02 Action-tag grammar, five implementations** (a) [confirmed, security, design]
  - `penguin/utils/parser.py:958-1088`, `penguin/tui_adapter/part_events.py:181`,
    `penguin/cli/cli.py:3821`, `penguin/cli/streaming_display.py:66`
  - The pre-check and the stripper ignore case, the extractor does not, so
    `<EXECUTE>…</EXECUTE>` is deleted from history without running. The
    executor has no code-fence awareness while the UI treats quoted tags as
    literal. `strip_incomplete_action_tags` deletes everything after any `<`
    with no later `>`. A nested same-name close truncates the payload.
  - Correction: one tokenizer used by execute, strip and display.
  - Decision (Maximus, 2026-11-13): "let's still stick with action tags".
    Read as: a tag is an action tag wherever it appears, including inside a
    code fence or backticks, so the executor's behaviour stays and the other
    copies are brought in line with it. Confirm this reading before the
    display copies (SM-44) are changed.
  - State: the two confirmed gaps are fixed. Left open, each a behaviour
    question and not a contradiction between copies: a nested same-name close
    tag still truncates the payload (a regex cannot pair them);
    `html.unescape` still rewrites `&lt;` and `&amp;` inside params; the CLI
    display copies still use their own single-tag patterns. The streaming
    display's treatment of backtick-adjacent tags as literal is SM-44.
- [x] **SM-03 Effective permission mode** (a) [security, bend]
  - `penguin/security/permission_engine.py:274-397,487`,
    `penguin/security/tool_permissions.py:476-586,955`,
    `penguin/security/agent_permissions.py:397`
  - A policy that raises is skipped, an agent-policy error returns ALLOW,
    unknown tools are ALLOW without a request policy, and the last-denial
    reason is read from a shared list.
  - Correction: fail closed on policy errors; one resolution function. Extend
    `prototypes/bend_permissions`.
  - State: the three fail-open paths are closed (enforcer policy error, agent
    policy error, startup capability policy on the action-tag path). On hold,
    each needs a product decision: unknown tools are still ALLOW without a
    request policy; an agent with no registered policy is still ALLOW; the
    last-denial reason is still read from a shared list; MCP servers are still
    accepted from project-level config. Bend extension deferred.
- [x] **SM-04 Approval request lifecycle** (c) [security]
  - `penguin/security/approval.py:176-334,471,516`,
    `penguin/security/permission_engine.py:279,323`
  - `approve()` does not check expiry. SESSION scope without a session id, or
    PATTERN without a pattern, degrades to ONCE while recording the wider
    scope. `_resolved` grows without bound. A second, enforcer-global
    allowlist has no session key.
  - Correction: one `resolve(request, decision)` function with a terminal
    guard; reject mismatched scope instead of degrading.
  - State: fixed. On hold: `PermissionEnforcer._session_allowlist` is still a
    second remembered-allow store with no session key; SESSION scope still
    grants the whole operation on any resource.
- [x] **SM-05 Permission reply surfaces** (c) [security]
  - `penguin/web/routes.py:1670-1985,8169-8238,8505-8595`,
    `penguin/integrations/acp/server.py:189`
  - Two reply endpoints disagree on already-resolved requests, glob escaping
    and scope. Neither checks that the request belongs to the caller's
    session. Callbacks register lazily, so some approvals emit no
    `permission.asked`. `_approval_ws_manager.connect()` is never called.
  - Correction: one service function behind both endpoints; session
    ownership check; register callbacks at startup; delete the dead manager.
  - State: event delivery is fixed. On hold: neither reply endpoint checks
    that the request belongs to the caller's session (needs the client to send
    a session id, an API change); the two endpoints still differ on an
    already-resolved request (`True` versus 404) and on scopes offered;
    `_approval_ws_manager.connect()` is still never called.
  - Blocked by: SM-04
- [ ] **SM-06 Per-call authorization grant** (on hold) (c) [security]
  - `penguin/tools/async_dispatch.py:112-264`,
    `penguin/security/tool_approval.py:22-116`,
    `penguin/tools/tool_manager.py:2445-2591,4487`
  - The grant only holds if the key is byte-identical after a second context
    merge. Drift spends the approval and creates an orphan request. Async
    tools are checked twice. The wait has no timeout of its own.
  - Correction: carry the grant as a value from approval to dispatch instead
    of recomputing a key.
  - On hold (2026-11-13): when the key drifts the code asks again, which is
    safe. The fix is a redesign of a security boundary with a large existing
    contract suite (`tests/tools/test_permission_resume.py`); it needs a
    design conversation, not a loop iteration.
- [x] **SM-07 Session dirty/save protocol** (c) [design]
  - `penguin/system/conversation.py:100-269,648`,
    `penguin/system/session_manager.py:86-103,252-263,501,553,841`
  - No lock between the auto-save thread and appends, so a message added
    between serialise and clear is marked clean. Both writers share one temp
    path. `mark_session_modified` is a no-op for an uncached session.
    `save_session` returns True when the index write failed.
  - Correction: one dirty counter compared before and after serialise, or one
    lock; unique temp paths; surface index failures.
  - State: fixed. Main had already added unique temp files, a store lock and
    index-failure reporting; the dirty-bit lost update remained and is now
    closed with a per-session revision counter. Left open:
    `mark_session_modified` is still a no-op for a session that is neither
    cached nor current; `SessionManager.__del__` still saves to disk during
    garbage collection, which crashed the interpreter once in a test here.
- [x] **SM-08 Rollback and branch pointer swap** (b)
  - `penguin/system/conversation_manager.py:1678-1718`,
    `penguin/system/checkpoint_manager.py:300`
  - After rollback the cache still maps the session id to the pre-rollback
    object, so auto-save can write old history back. Rollback and branch
    disagree on marking and saving.
  - Correction: one `replace_current_session` function used by both.
  - State: fixed as `SessionManager.adopt_current_session`. Left open:
    `system_prompt_sent` is not recomputed after a rollback; the manager used
    is whichever agent's is current.
  - Blocked by: SM-07
- [ ] **SM-09 Session load, recovery and index consistency** (b)
  - `penguin/system/session_manager.py:126-178,341-479,669,818`
  - A backup-only state never tries the backup. A recovery session with a new
    id is reported as a successful load of the requested id. Delete and
    continuation update the index and the files in the unsafe order.
  - Correction: explicit load result (loaded, restored, recovered, missing);
    files before index on create, index before files on delete.
- [ ] **SM-10 `process()` retry envelope** (b) [inferred]
  - `penguin/core_runtime/process_runtime.py:42-310`
  - A failure in the error emit after the engine ran tools may re-run the
    whole turn, re-adding the user message and re-running tools.
  - Correction: retry only before the engine has started.
- [ ] **SM-11 GitHub webhook delivery** (b/c) [security]
  - `penguin/web/integrations/github_webhook.py:30-81,269,286-343,455,647`
  - No sender filter, and the bot's own completion comment contains an
    `@Penguin` mention. Dedupe is in memory and marks a delivery seen before
    the work runs. Handlers swap the global current session.
  - Correction: ignore the bot's own comments; mark seen after success;
    stop mutating the global session.

## Tier 1: wrong output, hung or stuck sessions

- [ ] **SM-12 Stream-end outcome, seven copies** (b → a) [confirmed, bend, design]
  - `penguin/llm/adapters/openai.py:1852,2627,2719`,
    `penguin/llm/adapters/openrouter.py:1547,2212`,
    `penguin/llm/adapters/anthropic.py:760-1091`,
    `penguin/llm/adapters/litellm.py:610-634`
  - OpenAI HTTP swallows a provider error event inside `except Exception:
    continue` and reports a retryable network error instead. Anthropic timeout
    sets `finish_reason=ERROR` without recording the error, so the error text
    is returned as the answer. `response.incomplete` is unhandled. OpenRouter
    finalizes tool calls before the error check. LiteLLM's `finally: return`
    hides failures. Errors come back as raises, sentinel strings, or text
    appended to model output.
  - Correction: one pure `classify_stream_end(saw_completed, saw_error,
    pending_tool, has_text, cancelled, …)` used by every adapter; errors are
    raised, never returned as text. Model it in Bend next to `retry.bend`.
- [ ] **SM-13 Pending tool-call accumulation, four adapters** (c)
  - `penguin/llm/adapters/openai.py:143-158,451-565`,
    `penguin/llm/adapters/openrouter.py:91,709-814,2552`,
    `penguin/llm/adapters/anthropic.py:78,422-498`,
    `penguin/llm/providers/link/provider.py:132,334,422`
  - Each adapter promotes a call to pending at a different point. Error paths
    do not clear. The drained shape differs for Link. Id-less dedup merges
    identical calls.
  - Correction: one accumulator class with one promotion rule.
  - Blocked by: SM-12
- [ ] **SM-14 Retry and replay layering** (b) [bend]
  - `penguin/llm/runtime.py:329-347,599-757`,
    `penguin/llm/providers/link/provider.py:205-246`,
    `penguin/llm/adapters/openai.py:920-929`
  - Three independent retry layers. The OpenAI SDK-to-HTTP fallback can emit
    text twice. The Link loop is unbounded. Error sentinels differ by layer.
  - Correction: one retry owner (the runtime); adapters never re-request.
  - Blocked by: SM-12
- [ ] **SM-15 Turn-loop termination, two copies** (a in b) [bend, design]
  - `penguin/engine.py:1679-2060,2306-2451`
  - The task loop and `run_response` disagree on stop, finish-tool status and
    empty responses. The `LENGTH` and malformed-action continues have no
    counter. `CancelledError` skips save and stream abort.
  - Correction: one `LoopOutcome` reducer both loops call; bound every
    continue.
- [ ] **SM-16 Session abort, request accounting and busy/idle** (c) [design]
  - `penguin/core_runtime/process_lifecycle.py:30-313`,
    `penguin/core_runtime/stream_events.py:244-325,417-547,1031`,
    `penguin/web/services/session_view.py:1090-1133`,
    `penguin/web/routes.py:3952,4401-4426,6063`
  - Task set and counter encode one fact in three places. The abort marker can
    outlive the request. Busy is derived from four sources, one of which (an
    uncompleted persisted message) has no owner, so a crash leaves the session
    busy forever. Every cancellation returns as a normal 200.
  - Correction: one per-session run record owned by `process_lifecycle`;
    status derived from it only.
- [ ] **SM-17 Stream scope lifecycle** (c)
  - `penguin/core_runtime/stream_events.py:193-216,604-986`,
    `penguin/core_runtime/process_streaming.py:114`,
    `penguin/engine.py:3363-3532,3847`
  - The scope key is derived three ways with different precedence, and
    `_llm_step` aborts the stream only on `LLMProviderError`.
  - Correction: compute the key once per request and pass it; abort in
    `finally`.
- [ ] **SM-18 Engine `_llm_stream` sentinel** (c) [confirmed]
  - `penguin/engine.py:3952-3989`
  - The producer task is never awaited, so an exception leaves the consumer
    waiting forever. Chunks are queued through `create_task` and can land
    after the sentinel.
  - Correction: queue the sentinel in `finally`, put chunks directly, await
    the producer.
- [ ] **SM-19 Task status × phase** (b) [confirmed, bend]
  - `penguin/project/models.py:33-79,554,586-681,805-818`,
    `penguin/orchestration/native.py:536`,
    `penguin/web/routes.py:5460`, `penguin/cli/cli.py:3593`
  - `mark_pending_review` and `approve` set `phase = DONE` and then ignore a
    rejected status transition, leaving ACTIVE + DONE. Phase writes are
    unguarded. Web and CLI bypass the manager.
  - Correction: one transition over the (status, phase) pair that either
    applies both or neither and raises on rejection. Law: DONE pairs only with
    PENDING_REVIEW or COMPLETED.
- [ ] **SM-20 Workflow orchestrator** (b)
  - `penguin/project/workflow_orchestrator.py:104-329`
  - The PR result status is never inspected. `if not success` branches are
    dead. The except handler raises again. Cancellation leaves the task
    RUNNING.
  - Blocked by: SM-19
- [ ] **SM-21 Native and Temporal workflow backends** (c)
  - `penguin/orchestration/native.py:53-56,158-290`,
    `penguin/orchestration/temporal/workflows.py:95,250`,
    `penguin/orchestration/temporal/backend.py:160`
  - A pause saved by `signal_workflow` is overwritten by the runner's next
    save. Cancelling a completed workflow rewrites it. No recovery of RUNNING
    rows after restart.
- [ ] **SM-22 Checkpoint lifecycle** (c)
  - `penguin/system/checkpoint_manager.py:112-300,749`,
    `penguin/system/conversation.py:231-246`
  - The id is returned before the file exists. The live session is
    serialised at dequeue time. Workers can start in a throwaway loop with
    `_workers_started` left True. An index load error resets the index.
- [ ] **SM-23 Session boundary rollover** (b)
  - `penguin/system/conversation.py:256-269,677`,
    `penguin/system/session_manager.py:578-625`,
    `penguin/system/context_epoch.py:136`
  - Rollover can fire between a tool call and its result.
  - Correction: defer rollover while a tool group is open.
- [ ] **SM-24 Managed process lifecycle** (c)
  - `penguin/tools/process_runtime.py:45-651`
  - `completion_reason` is written from two threads. `stop` can signal a
    reaped pid. `cleanup` holds the lock across blocking stops and drops
    receipts. Lookups race with `_retire`.
- [ ] **SM-25 Process completion notice and idempotent start** (c)
  - `penguin/tools/process_tools.py:47-267`,
    `penguin/tools/async_dispatch.py:187-204`
  - Exactly-once delivery depends on the consumer acknowledging. Listeners
    are never unbound. The cancel wait is unbounded.
  - Blocked by: SM-24
- [ ] **SM-26 Durable chat-request receipt** (c)
  - `penguin/web/services/chat_requests.py:36,85-347`,
    `penguin/web/services/a2a.py:74-248`, `penguin/web/app.py:211`
  - Rows whose owner died stay "recovering" forever. Fingerprints differ by
    caller. Shutdown neither awaits nor cancels in-flight tasks. The A2A
    repair mapper disagrees with the execute mapper.
- [ ] **SM-27 WebSocket chat stream** (c)
  - `penguin/web/routes.py:4434-5047`
  - One queue is shared across messages, so a stale sentinel ends the next
    reply early. The socket is not read during processing. Handlers have no
    session filter.
- [ ] **SM-28 SSE connection and ledger batch** (c)
  - `penguin/web/sse_events.py:124-461`
  - A full queue drops events silently. The batch is not flushed at shutdown.
- [ ] **SM-29 In-process code execution** (c)
  - `penguin/tools/tool_manager.py:342,4967-5024`
  - A timed-out execution keeps running and keeps the lock, so later calls
    queue behind it.
- [ ] **SM-30 RunMode continuous loop and result vocabulary** (b)
  - `penguin/run_mode.py:79-101,444,657-981,1427-1563`
  - Several engine failure statuses fall through as success. The
    empty-response retry has no counter. `start()` checks a status the task
    engine never returns.
  - Blocked by: SM-15
- [ ] **SM-31 `utils` event bus subscription liveness** (c) [confirmed]
  - `penguin/utils/events.py:79,117,128`
  - Handlers are stored as `weakref.ref`, which is dead immediately for bound
    methods. `publish` mutates the list it iterates and holds a lock across
    handler awaits.
  - Correction: `weakref.WeakMethod` for bound methods, or strong references
    with explicit unsubscribe.

## Tier 2: drift, leaks, duplicated truth

- [ ] **SM-32 `LLMRequestLifecycle.status`** (b) [bend]: `penguin/llm/contracts.py:72,194`; update helper copy-pasted in three adapters; no terminal guard; `RETRYING` never written. Blocked by SM-12.
- [ ] **SM-33 Call outcome classification** (a) [bend]: `penguin/llm/api_client.py:535-992`, `penguin/llm/runtime.py:286`; computed twice with different rules. Blocked by SM-12.
- [ ] **SM-34 Tool-replay adjacency repair, three copies** (a): `openai.py:1342-1519`, `openrouter.py:1201-1366`, `anthropic.py:1341-1418`; each provider treats orphans differently; OpenRouter rewrites `call_…` tokens in plain content.
- [ ] **SM-35 Per-request `last_*` state on the adapter** (c) [design]: resets at `openai.py:820`, `openrouter.py:1404`, `anthropic.py:700`; Link resets a subset; `prepare_native_tool_kwargs` flips `interrupt_on_tool_call` permanently (`runtime.py:424`). See `model-config-mutation-state-leak.md`.
- [ ] **SM-36 Reasoning-variant override** (b): `penguin/web/routes.py:1063-1091,4191,4418,4796`; the REST restore may write a deep-copied config's snapshot onto the global config. Unconfirmed.
- [ ] **SM-37 Model switch propagation** (b): `penguin/core_runtime/model_runtime.py:107-375`; multi-step, non-atomic, failures downgraded to warnings.
- [ ] **SM-38 Stall / empty / repeat guard** (a) [bend]: `penguin/engine.py:304-418,1376-1602`; counters reset in four places; recovery never re-arms; a kill in response mode looks like `completed`. Blocked by SM-15.
- [ ] **SM-39 Per-session stream state dict** (c): `penguin/core_runtime/stream_events.py:68-85,448,1247-1349`; `active` with no message id exists across an await; adapter map entries leak. Blocked by SM-16.
- [ ] **SM-40 Session-goal run claim** (c): `penguin/core_runtime/session_goal_runtime.py:741-1079`; gate checked at 844 and acquired at 883; orphan test assumes one process per workspace.
- [ ] **SM-41 RunMode singleton lifecycle** (b): `penguin/core_runtime/runmode_lifecycle.py:29-92`; no re-entrancy guard.
- [ ] **SM-42 MCP connection lifecycle** (b): `penguin/tools/providers/mcp.py:22-115`, `penguin/integrations/mcp/manager.py:71-503`; a failed discovery is sticky; (FAILED, session set) is representable; `_ensure_actor` is unlocked; `list_changed` is never consumed.
- [ ] **SM-43 Plugin lifecycle** (b): `penguin/plugins/plugin_manager.py:52-483`; parallel load looks like a deadlock (not run); action unregistration compares the wrong name.
- [ ] **SM-44 Streaming action-tag stripper** (b): `penguin/tui_adapter/part_events.py:112,181-267`; an unterminated tag drops all later text; reasoning and content share one parser state. Blocked by SM-02.
- [ ] **SM-45 Message / part / tool lifecycle** (c): `penguin/tui_adapter/part_events.py:97-769`; the error path leaves `_stream_active` set; two sources of truth for active tools.
- [ ] **SM-46 Headless CLI streaming display** (c): `penguin/cli/streaming_manager.py:27-80`, `penguin/cli/streaming_display.py:53-201`, `penguin/cli/cli.py:3763-4617`, `penguin/cli/event_manager.py:151-291`; stopping the spinner leaves the stream id set; five copies of the cleanup.
- [ ] **SM-47 CLI event bus delivery and dedup** (c): `penguin/cli/events.py:107-234`; events without `content` share a dedup key; sync handlers mutate display state from a worker thread.
- [ ] **SM-48 Launcher web-server ownership** (b): `penguin/cli/opencode_launcher.py:205-276,964-1054`; a foreign server on the port counts as ours; no SIGTERM handler.
- [ ] **SM-49 Provider OAuth pending flow** (c): `penguin/web/services/provider_auth.py:40-512,1023-1227`; one slot per provider, popped by provider and not by state; four TODOs already name the gaps.
- [ ] **SM-50 OpenAI OAuth resolve and refresh** (b): `penguin/llm/adapters/openai.py:1019-1145`; resolve and peek duplicate env parsing; refresh writes process-wide state unlocked.
- [ ] **SM-51 ACP session turn** (c): `penguin/integrations/acp/server.py:39-187`; `cancel` can call `.cancel()` on a task already set to None.
- [ ] **SM-52 Run-mode task WebSocket** (b): `penguin/web/routes.py:6682-6886`; `core._temp_ws_callback` is a single slot.
- [ ] **SM-53 Sub-agent registry** (b): `penguin/system/conversation_manager.py:224-240,340,501-582,1598`; removing the current agent leaves three "current" pointers stale.
- [ ] **SM-54 AgentExecutor task state** (c): `penguin/multi/executor.py:212-443`, `penguin/multi/coordinator.py:309`; PAUSED is a label only; `cancel()` overwrites a finished state.
- [ ] **SM-55 Context window trimming and epoch** (a) [bend]: `penguin/system/context_window.py:272-1220`, `penguin/system/context_epoch.py:24-155`; total over budget with every category under its own budget trims nothing. Keep the category-priority trimming model; do not introduce compaction.
- [ ] **SM-56 Edit commit and rollback** (b): `penguin/tools/editing/service.py:507-533`, `penguin/tools/editing/legacy_multifile.py:164-262`; the snapshot is appended after the write.
- [ ] **SM-57 File-root / execution mode** (b): `penguin/tools/tool_manager.py:4030-4166`, `penguin/config.py:532,597`; three writers disagree on env vars and the notebook directory.
- [ ] **SM-58 PyDoll browser session** (b): `penguin/tools/pydoll_tools.py:14-201`; (browser set, not initialized) is reachable; a dead cleanup task blocks the idle timer.
- [ ] **SM-59 Browser-harness daemon identity** (c): `penguin/tools/browser_harness_tools.py:24,264-426`, `penguin/tools/browser_harness_ownership.py:81`; cleanup runs without the helpers lock.
- [ ] **SM-60 Lazy tool loading** (b): `penguin/tools/tool_manager.py:278,2231-2907,6355`; check-then-set with no lock on worker threads.
- [ ] **SM-61 Memory incremental index** (c): `penguin/memory/indexing/incremental.py:47-142`, `penguin/memory/indexing/metadata.py:38-108`; re-index duplicates entries; non-atomic metadata write.
- [ ] **SM-62 Git PR flow** (b): `penguin/project/git_manager.py:153-308`; no checkout back to base on failure.

## Tier 3: minor, legacy, or probably deletable

Check for callers first. If there are none, delete.

- [ ] **SM-63 Interrupt flags** (a): `penguin/engine.py:765`, `penguin/run_mode.py:81,479,757`, `penguin/core_runtime/core_state.py:56`; `Engine._interrupted` is never read; `core._interrupted` is never set True.
- [ ] **SM-64 Legacy `get_response` retry** (b): `penguin/core_runtime/response_generation.py:31-114`; swallows cancellation and persists an apology string.
- [ ] **SM-65 Legacy `local_task` status strings** (b): `penguin/local_task/manager.py:137-182` and bypass sites; handlers are unreachable until SM-31 is fixed. Still imported by `utils/parser.py:22`.
- [ ] **SM-66 Legacy process attach** (b): `penguin/utils/parser.py:1112,2015-2038`, `penguin/utils/process_manager.py:13-160`.
- [ ] **SM-67 Legacy Textual TUI stream** (c): `penguin/cli/tui.py:1473-2614`; referenced only from `misc/` and a prototype.
- [ ] **SM-68 Legacy `BrowserManager`** (b): `penguin/tools/browser_tools.py:42,181`; `initialize` always returns False.
- [ ] **SM-69 REPL interrupt and turn loop** (b): `penguin/cli/cli.py:4103-4602`, `penguin/cli/session_manager.py:52`; Ctrl-C during processing never cancels the core; `/exit` sets a flag nothing checks.
- [ ] **SM-70 CLI message dedupe** (a): `penguin/cli/cli.py:3754-4151`, `penguin/cli/event_manager.py:130-189`; keyed on the first 50 characters, never pruned.
- [ ] **SM-71 Config root and env precedence** (b): `penguin/config.py:30-831`; module-level `config` never reloads; a project `.env` overrides shell-exported keys.
- [ ] **SM-72 Sidecar binary cache** (b): `penguin/cli/opencode_launcher.py:531-717`; a partial copy passes the existence check.
- [ ] **SM-73 First-run setup marker** (b): `penguin/setup/wizard.py:123-354`; the marker file is written and never read.
- [ ] **SM-74 Skills activation, QuestionManager, ProcessWaitGuard** (b): `penguin/skills/manager.py:21-112`, `penguin/security/question.py:73-257`, `penguin/tools/process_wait.py:17`; unpruned sets and no expiry.
- [ ] **SM-75 Small singletons and slots**: `CircuitBreaker` string state (`penguin/project/resilience.py:97`), `RuntimeJobRecord.status` upsert (`penguin/project/storage.py:488`), `PenguinState._previous_state` (`penguin/system/state.py:471`), DAG cache invalidation (`penguin/project/manager.py:1340`), MessageBus drop (`penguin/system/message_bus.py:92`), VCS watcher slot (`penguin/web/services/system_status.py:20`), title refresh tasks (`penguin/web/routes.py:963`), `events_ws` (`penguin/web/routes.py:2367`), connection pool `close_all` (`penguin/llm/api_client.py:164`), core/app singletons (`penguin/web/app.py:36,212`).
- [ ] **SM-76 Second sweep** of the directories listed as not opened, and of any file touched since `36e32f623`.

## Changes on main since the sweep

`origin/main` moved 63 commits between the sweep and 2026-11-13. Seen so far:

- `penguin/system/atomic_storage.py` now backs `SessionManager` saves with a
  unique temp file, a store lock and a merged index write, and `_save_index`
  returns a bool. SM-07 and SM-09 are partly addressed; re-read before working
  them.
- The MCP provider in `ToolManager` is lazy (`_get_mcp_provider`), and client
  tools were added. SM-42 and SM-60 line numbers have moved.

## From the automated security review of `fafe14074`

Not verified. Fold into SM-03 when it is worked.

- `ToolCapabilityPolicy` is enforced in `execute_tool`, `execute_tool_async`,
  `get_tool` and `get_tools`, but reportedly not at
  `ActionExecutor.execute_action`, so legacy action handlers (process and
  browser actions) may bypass a restricted policy.
- `Config.mcp` accepts server definitions from project-level config, so an
  untrusted project could define an MCP server command. Suggested: a
  user-config-only trust flag, as with `trust_project_skills`.

## Seen in passing, not state machines

- `run_agent_turn` passes `image_path=` but `run_single_turn` accepts only
  `image_paths` (`penguin/engine.py:4013`). Unconfirmed.
- Test files live in source directories: `penguin/cli/test_tui_*.py`,
  `penguin/utils/test_*.py`, `penguin/local_task/test_manager.py`.
- Two `CommandRegistry` classes: `penguin/cli/commands.py:63` and
  `penguin/cli/command_registry.py:81`.

## Log

Append one line per finished item: id, outcome (`fixed`, `deleted`, `stale`,
`not reproduced`), commit, commands run and their result.

- SM-01: fixed (2026-11-13, on top of `548ad4ec9`).
  Added `tool_status_from_output` and `halts_ordered_execution` in
  `penguin/tools/runtime.py`; `_tool_result_from_child_output` and the three
  `stop_on_error` checks use them. Narrower than planned: only `error`,
  `cancelled`, `pending_approval` and `requires_approval` map away from
  `completed`; unknown status words such as `running` stay `completed`.
  - `pytest -q tests/tools/test_ordered_batch_input.py`: 12 passed (2 new,
    both red before the fix and red again under two mutations of it).
  - `pytest -q tests/tools tests/test_tool_runtime_ir.py
    tests/test_tool_capabilities.py tests/test_tool_schema_contract.py
    tests/test_engine_responses_tool_calls.py tests/test_event_bus_lifecycle.py`:
    285 passed, 2 failed. The 2 failures are
    `tests/tools/test_process_permission_contract.py::test_new_policy_applies_to_each_operation`
    (`process_start`, `process_write_stdin`) and fail the same way with
    `HEAD`'s `runtime.py`, so they predate this item.
  - `PENGUIN_TEST_BEND=1 pytest -q tests/integrations/test_bend_tool_status.py`:
    4 passed: nine laws proven, the model matches Python on 12 cases, and two
    unsafe mutations of the model fail the proofs. `--verdict` not run (no
    Lean installed).
  - `ruff check` on touched files: no new findings.
- Baseline repair (2026-11-13, `548ad4ec9`): the two
  `test_process_permission_contract.py` failures were a stale test. `9ddb96066`
  made unsandboxed shell ask unless every capability is allowed; the test set
  only `shell: allow`. Test updated; no product change.
- Baseline repair (2026-11-13): `tests/test_core_tool_mapping.py::test_run_agent_prompt_in_session_overrides_parent_execution_scope`
  failed on `origin/main` because its bare core had no UI emitter after the
  agent lifecycle emit was added. Fixture updated; no product change.
- SM-02: fixed (2026-11-13). `parse_action` now matches tags with the same
  case-insensitive flags as `strip_action_tags`, and
  `strip_incomplete_action_tags` removes a trailing fragment only when it is a
  prefix of an action tag name.
  - `pytest -q tests/test_action_tag_grammar.py`: 13 passed (7 red before the
    fix; red again under two mutations).
  - 25 parser-using test files plus `tests/llm`,
    `tests/test_part_event_persist_callback.py` and
    `tests/test_engine_task_finish_contract.py`: 731 passed, 4 skipped.
  - `ruff check` on the new test file: clean.
- Baseline repair (2026-11-13): `tests/api/test_concurrent_session_isolation.py`
  used `routes_module` without importing it. Import added.
- SM-03: fixed (2026-11-13). `PermissionEnforcer.check` and
  `_check_agent_permission` deny when a policy raises;
  `ActionExecutor.execute_action` applies `ToolCapabilityPolicy` before any
  handler.
  - `pytest -q tests/test_permission_fail_closed.py`: 93 passed. The two
    policy tests and the `process_list` / `task_list` cases were red before the
    fix; each fix removed alone turns its test red.
  - Every test file mentioning permissions, `ActionExecutor` or tool
    capabilities, plus `tests/tools`: 902 passed, 36 skipped.
- SM-04: fixed (2026-11-13). All three terminal moves go through
  `ApprovalManager._record_resolved`; `approve()` on an expired request records
  EXPIRED, notifies listeners and returns None.
  - `pytest -q tests/test_approval_lifecycle.py`: 4 passed, all red without the fix.
  - Every test file mentioning approvals or permissions: 617 passed, 15
    skipped, 1 failed. The failure is
    `tests/test_cli_surface_audit_regressions.py::test_runmode_help_text_reflects_continuous_mode_truth`,
    a `TypeError` inside click's `make_metavar` in this environment; it fails
    the same way without this change.
- SM-05: fixed (2026-11-13). `permission.asked` / `permission.replied` are
  emitted before, and independently of, the WebSocket send; listeners are
  registered in the app lifespan and in `/approvals/*`; a reject message is
  attached before the request is resolved.
  - `pytest -q tests/api/test_permission_reply_surfaces.py`: 3 passed, all red
    before the fix.
  - `tests/api`, `tests/web` and `tests/tools/test_permission_resume.py`, one
    file at a time with a 60 s cap: all pass except the two below.
- Known red baseline, not caused by this branch (same result on `HEAD`
  without the change), not yet investigated:
  - `tests/api/test_web_app_credentials_rehydrate.py`: 1 failed.
  - `tests/api/test_web_auth_hardening.py`: hangs for more than 60 s. This is
    why whole-directory and whole-suite runs never finish. Run `tests/api`
    per file, or deselect it.
  - `tests/test_cli_surface_audit_regressions.py::test_runmode_help_text_reflects_continuous_mode_truth`:
    click `make_metavar` `TypeError` in this environment.
  - `tests/test_a2a_server.py`: cannot be collected, `a2a` is not installed.
- SM-07: fixed (2026-11-13). `SessionManager` counts modifications per
  session; `save_session` clears the modified flag only if the count is
  unchanged since it took its snapshot, and `_auto_save_sessions` no longer
  clears the flag itself.
  - `pytest -q tests/system/test_session_dirty_tracking.py`: 3 passed; 2 red
    without the fix.
  - `tests/system` and `tests/core_runtime`: 544 passed, 2 skipped, 3 xfailed.
    Other files that use `SessionManager`: 120 passed, 3 skipped.
- SM-08: fixed (2026-11-13). Rollback and branch both call
  `ConversationManager._adopt_restored_session`, which replaces the cached
  object for that session id, marks it modified and saves it.
  - `pytest -q tests/system/test_rollback_session_swap.py`: 1 passed; red
    before the fix (auto-save wrote the pre-rollback history back).
  - Every non-API test file mentioning checkpoints: 333 passed, 3 skipped,
    1 xfailed.
