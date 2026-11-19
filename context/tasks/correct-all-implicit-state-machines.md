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
- SM-31: bound-method subscribers on the `utils` event bus now receive
  events. That wakes handlers that have never run: `TelemetryCollector` and
  the legacy `local_task` `ProjectManager` handlers. Handler errors are caught
  and logged by the bus. If either misbehaves, revert this commit or
  unsubscribe that handler.
- SM-12: the Anthropic adapter's fixed 30-second limit on a whole streamed
  response is removed (a longer answer was cut off and reported as a timeout).
  The 10-second gap check next to it could never fire and is removed too.
  Stalls are left to the SDK's own HTTP timeouts.
- SM-12: an OpenAI `response.incomplete` event is now a cut-off answer
  (`LENGTH`, or `CONTENT_FILTER` when the provider says so), not a dropped
  connection to retry. An unrecognised reason counts as `LENGTH`. Tool calls
  from a cut-off response are discarded.
- SM-12: OpenRouter and Anthropic keep returning a marked string with the
  error recorded, because existing tests assert that and `APIClient` reads the
  recorded error. Only LiteLLM changed to raising. The item said "errors are
  raised, never returned as text".
- SM-16: a session is busy only while a request, stream or adapter is live.
  A saved assistant message with no completion time no longer makes it busy,
  so a session interrupted by a crash can be reverted and shows as idle.
- SM-16: an abort marker left with no tracked request is used up the first
  time it cancels a stream chunk. Before, it cancelled every later chunk for
  that session until a `process` request cleared it.
- SM-14: when the OpenAI SDK stream fails after it has produced output, the
  adapter no longer re-sends the request over HTTP. A transport failure is
  raised as a retryable network error (the runtime does not replay it once
  text has streamed); any other error is raised as it is. A failure before
  the first event still falls back to HTTP, as before.
- SM-32: `RETRYING` is kept and given a meaning instead of being deleted: a
  failed attempt that is being retried (Link's reconnect wait). A failed
  attempt can only move to `RETRYING`; `COMPLETED` and `CANCELLED` are final.
  A refused transition is ignored and logged at debug level, not raised.
- SM-16: a session is busy when any live source says so (a request in
  flight, an active stream, or its TUI adapter). Before, the sources
  overwrote each other in turn, so an adapter reporting idle hid a stream
  that was still running.
- SM-15: `run_response` now runs the same loop as `run_task`, so its
  results change where the two had drifted apart: a stop request reports
  `stopped` (was `completed`); a `finish_response` call whose tool status is
  not `completed` no longer ends the run; an empty provider answer reports
  `llm_empty_response_error` (was `error`; A2A now fails the task on it); the
  output-limit cap reports `max_iterations` (was `completed`); usage is kept
  on a failed run (was `{}`). The error text in `assistant_response` is
  unchanged. A failure while preparing the conversation, before the first
  turn, now raises to `core.process` instead of returning an `error` result.
- SM-15: malformed tool syntax gets at most 3 repair turns
  (`MAX_MALFORMED_ACTION_REPAIRS`); the run then stops with the iteration-limit
  status (`max_iterations` or `iterations_exceeded`) rather than a new status,
  so goal and RunMode consumers treat it as "limit reached, progress saved".
  The output-limit and repair counters reset only after an ordinary turn.
- SM-15: a cancelled run saves the conversation before re-raising, so
  completed turns and tool results survive a restart. A tool call left
  without its result by the cancel is saved as it is in memory.
- SM-22: the checkpoint queue and its two workers are removed. A
  checkpoint is snapshotted when requested and its file written on a worker
  thread; with no event loop running (a sync caller), an automatic checkpoint
  is now written on the spot. Before, it was started in a throwaway loop and
  lost. `cleanup_old_checkpoints` now runs the cleanup and returns the real
  count (was always 0).
- SM-22: an unreadable checkpoint index is kept as
  `checkpoint_index.json.corrupt` and the index is rebuilt from the
  checkpoint files, which each hold their own metadata. One bad entry is
  skipped instead of dropping the whole index.
- SM-24: once Penguin has reaped a process's shell, it signals that
  process group only if no process now has the shell's pid. If one does, the
  pid was reused and the group id may name another program's group (on macOS
  most apps lead their own group), so nothing is sent. Children that outlived
  their shell are still killed when the pid is free.
- SM-24: `ProcessRuntime.cleanup` retires each record instead of dropping
  it, so the retry receipt survives and a retried start with the same
  process id reports `process_result_expired` instead of running the command
  again. `test_process_runtime_cleanup_stops_and_removes_managed_processes`
  now expects that instead of `unknown_process_id`.
- SM-25: cancelling a process tool waits at most 10 seconds
  (`PROCESS_CANCEL_GRACE_SECONDS`) for its worker to stop the process, then
  returns the cancellation and logs a warning. The worker keeps running and
  still owns cleanup; only the caller stops waiting.
- SM-26: at web-server shutdown, in-flight durable chat requests are
  stopped with a new abort reason, `server_shutdown`, and given up to 5 s to
  record it. Their receipts then read as stopped (`aborted: true`), which
  A2A maps to cancelled, instead of staying accepted.
- SM-26: the Link and A2A callers keep their own request fingerprints. They
  write to separate stores, so they never meet. A2A's narrower one ignores
  `link_execution` when a message id is reused.
- SM-27: a `/api/v1/chat/stream` client that disconnects while its message
  is processed now cancels that processing (it ran to the end before). A
  message sent while a reply is still streaming is answered after it, in
  order. Tool events are forwarded only for the request's own session; a
  request that sends no session id still receives every event, as before.
- SM-38: when the wallet guard stops a run that is not making progress, the
  status now says why, in both modes: `repeated_response`,
  `tool_result_echo` or `empty_responses`. Before, response mode reported
  `completed` and task mode `implicit_completion`. Session goals treat these
  like other unknown statuses (`blocked`), as they already treat the
  tool-only stall statuses, so a stuck goal waits for the user instead of
  continuing on its own. A run that ends with a plain answer keeps
  `completed` or `implicit_completion`.
- SM-40: a goal-run claim now names its host and pid. A claim held by
  another live process on the same host is refused ("running in another
  Penguin process") instead of being recovered as orphaned. If that pid has
  been reused by an unrelated process, the run is refused rather than run
  twice. Claims from another host, or in the older id format, are still
  recovered as before.
- SM-44: when a stream ends while an action tag is still open (the model
  never closed it, or named a tag such as `<execute>` in prose), the text
  held back since that tag is now shown instead of dropped. A truncated
  tool call can therefore show its partial syntax, which the engine also
  repairs (SM-15).
- SM-48: the launcher now counts a server as Penguin only when
  `/api/v1/health` answers 200 with Penguin's health payload (it has
  `agent_capacity`). Another service on the port is no longer reused; the
  launcher then tries to start its own server, which fails on the occupied
  port with an error.
- SM-50: a stored OpenAI OAuth record that has a refresh token but no
  access token is now refreshed (`oauth_record_needs_refresh` treats a
  missing access token as needing refresh). Before, the request failed with
  "reauth required" while request preparation silently used an
  environment token.
- SM-62: when a task PR fails after its feature branch was created (commit,
  push or PR creation), the repository is checked out back on the branch it
  started from. Committed work stays on the feature branch. A successful PR
  still leaves the feature branch checked out, as before.
- SM-66: the ActionXML `process_*` tags now run on the same
  `ProcessRuntime` as the native process tools (the process name is its
  id), instead of the legacy `ProcessManager`. Their reply text changed
  slightly. `process_exit` leaves the session but keeps the process and its
  input open, reusing a name is refused instead of orphaning the running
  process, and `process_enter` no longer waits forever for a silent process.
  `utils/process_manager.py` is now used only by `utils/plugin_parser.py`,
  which nothing imports; both are deletion candidates for Maximus.
- SM-71: environment precedence is now shell-exported variables, then the
  project `.env`, then the user-level `~/.config/penguin/.env`. Before, the
  project `.env` overrode keys exported in the shell for a run. The project
  `.env` is still found the same way as before (python-dotenv's
  `find_dotenv`, which starts from Penguin's own source directory rather than
  the current directory, despite the old comment).
- SM-40: when the session gate cannot be taken before the run deadline, the
  goal run now fails with a conflict before any claim is recorded. Before,
  it recorded the claim and then recorded a `timeout` result.
- SM-75: `ProjectManager` no longer caches the task DAG. `build_dag` reads
  the tasks on every call; its `force` argument and `invalidate_dag` are
  removed (no callers outside the manager, none in docs). Before, stats and
  the DOT export showed the graph from the first build until a blueprint
  sync. A runtime job in `completed`, `failed` or `cancelled` now ignores
  later upserts with a different status. `penguin/project/resilience.py`
  (`CircuitBreaker`, retry helpers) is deleted: its one import, in
  `git_manager.py`, used none of it. `PenguinState` (exported from
  `penguin.system`) has no callers in the repo; it is fixed, not deleted,
  and is a deletion candidate for Maximus.
- SM-84: pending steering gets another model turn only when the iteration
  limit and the token budget both allow one. Otherwise a finish signal in
  that turn stands (a task ends `pending_review`, as it would without the
  message) and the message stays queued for the agent's next run. Before,
  such a run ended `iterations_exceeded` or `budget_limited`;
  `test_late_steering_does_not_extend_token_budget` pinned `budget_limited`
  and now expects `pending_review` (it still checks one provider call).
- SM-94: `PENGUIN_RUNTIME_EVENT_LEDGER_MAX_EVENTS=0` (or `off`, `none`,
  `disabled`) now means no count limit, as `0`/`off` already did for the
  size limit and a zero age limit did for age. Before, `0` emptied the ledger
  on every cleanup. `RuntimeEventLedgerPolicy.max_events` accepts `None`.
- SM-108: `penguin/server/ws_server.py` and
  `penguin/memory/providers/milvus_provider.py` are deleted: neither could be
  imported (missing `new_core` and `base_provider`) and nothing imported
  them. `penguin/cognition/` has no importers either but holds an empty
  `placeholder.md`, which reads as a planned subsystem, so it is left as a
  deletion candidate for Maximus.
- SM-107: approval requests now carry `agent_mode`, `approval_policy` and
  `permission_mode`, so an ACP "remember for this saved session" grant is
  bound to them as its key always intended. Grants saved before this change
  were keyed with those fields empty, so they stop matching and the user is
  asked once more.
- SM-111: at the message limit, the live session keeps its id and its recent
  history, and the older history moves to an archive session with a new id.
  Before, the continuation got the new id, so `continued_from` now points
  from the live session to the archive (checkpoint lineage still follows it).

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
  - Disposition (2026-11-17, for review): partly fixed. Deferred to a
    follow-up, not done in PR #164: the session-ownership check on permission
    replies, the two endpoints' disagreement on resolved requests and scopes,
    and the dead `_approval_ws_manager`. The ownership check is a security
    boundary and needs the reviewer's decision on the client API change.
  - (2026-11-19, decided by Maximus: add it) Session ownership is checked: `penguin/web/services/permission_replies.py` (`authorize_permission_reply`) runs before all three reply endpoints resolve a request. A reply names its session in the body (`sessionID` on `/permission/{id}/reply`, `session_id` on `/approvals/{id}/approve` and `/deny`) or in the `X-Penguin-Session-Id` header; a reply naming another session gets 403 and the request stays pending. A reply naming no session is still accepted, so Link (which posts none) keeps working; `PENGUIN_PERMISSION_REPLY_REQUIRE_SESSION=true` refuses those with 400. The TUI sends the header. The session is a client claim, not an authenticated identity: all clients share one credential. Still open: the two endpoints differ on an already-resolved request (`True` versus 404) and on scopes offered; `_approval_ws_manager.connect()` is never called; Link should send `session_id`, after which the requirement can become the default.
  - Earlier state: event delivery is fixed. Was on hold: neither reply endpoint checks
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
- [x] **SM-09 Session load, recovery and index consistency** (b)
  - `penguin/system/session_manager.py:126-178,341-479,669,818`
  - A backup-only state never tries the backup. A recovery session with a new
    id is reported as a successful load of the requested id. Delete and
    continuation update the index and the files in the unsafe order.
  - Correction: explicit load result (loaded, restored, recovered, missing);
    files before index on create, index before files on delete.
  - State: the backup-only case is fixed. On hold: a recovery session with a
    new id is still reported to the caller as a successful load of the
    requested id (changing that changes what `conversation.load` returns);
    the index/file ordering on delete and continuation is unchanged.
- [x] **SM-10 `process()` retry envelope** (b)
  - `penguin/core_runtime/process_runtime.py:42-310`
  - A failure in the error emit after the engine ran tools may re-run the
    whole turn, re-adding the user message and re-running tools.
  - Correction: retry only before the engine has started.
  - State: (fixed, 2026-11-19) reproduced: `process` handles its own errors, so only a failure in `handle_process_error` (its UI emit) or in the `finally` cleanup reaches the retry wrapper, and the whole turn then ran three times, saving the user message and running tools each time. An exception that escapes after the user message is saved is now marked and not retried; `process_with_retry` returns it, as it does on retry exhaustion. Failures before the turn starts are still retried.
- [x] **SM-11 GitHub webhook delivery** (b/c) [security]
  - `penguin/web/integrations/github_webhook.py:30-81,269,286-343,455,647`
  - No sender filter, and the bot's own completion comment contains an
    `@Penguin` mention. Dedupe is in memory and marks a delivery seen before
    the work runs. Handlers swap the global current session.
  - Correction: ignore the bot's own comments; mark seen after success;
    stop mutating the global session.
  - State: the self-trigger is fixed. On hold: dedupe is still in memory and
    marks a delivery seen before the work runs (retry semantics are a product
    choice); handlers still swap the global current session.

## Tier 1: wrong output, hung or stuck sessions

- [x] **SM-12 Stream-end outcome, seven copies** (b → a) [confirmed, bend, design]
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
  - State: the OpenAI HTTP swallow and the Anthropic unrecorded timeout are
    fixed. Still open: one shared classifier for all seven copies;
    `response.incomplete`; OpenRouter finalising tool calls before its error
    check; LiteLLM's `finally: return`; Anthropic's 30 s hard cap and its
    error text returned as the response string; the Bend model.
  - State: (2026-11-13) one rule, `classify_stream_end` in `penguin/llm/stream_end.py`, now decides the outcome in the OpenAI (Codex, SDK, HTTP), OpenRouter (SDK, direct) and Anthropic stream ends. Fixed with it: `response.incomplete` handled; OpenRouter discards a partial tool call on a mid-stream error; LiteLLM no longer returns a failed or cancelled stream as a short answer; Anthropic's 30 s cap removed and its stream errors no longer sent as assistant text. Bend model in `prototypes/bend_stream_end` (draft laws await review). Not exercised by a test: the Codex and SDK `response.incomplete` branches, and OpenRouter's SDK path. See "Decisions taken while away" for what was kept as is.
- [x] **SM-13 Pending tool-call accumulation, four adapters** (waits on the SM-12 consolidation) (c)
  - `penguin/llm/adapters/openai.py:143-158,451-565`,
    `penguin/llm/adapters/openrouter.py:91,709-814,2552`,
    `penguin/llm/adapters/anthropic.py:78,422-498`,
    `penguin/llm/providers/link/provider.py:132,334,422`
  - Each adapter promotes a call to pending at a different point. Error paths
    do not clear. The drained shape differs for Link. Id-less dedup merges
    identical calls.
  - Correction: one accumulator class with one promotion rule.
  - Blocked by: SM-12
  - State: (partial, 2026-11-13) one `ToolCallAccumulator` (`penguin/llm/tool_call_accumulator.py`) with one rule (runnable only once closed; merged only on a shared id; never without a name) now backs the OpenAI, OpenRouter, Anthropic, Modal and RunInfra adapters. Fixed: an Anthropic tool call was runnable from its first fragment, and an id-less one was recorded once per fragment with partial JSON; OpenAI merged identical id-less calls. Still open: Link keeps its own list and drains a different shape (the runtime accepts both).
  - State: (done, 2026-11-14) Link now records its calls in the same accumulator and drains the same shape as the other adapters (`item_id`, `call_id`, `name`, `arguments`). Its two tests that asserted or replayed the old chat shape were updated.
- [x] **SM-14 Retry and replay layering** (re-read 2026-11-13: the unbounded Link loop is deliberate connection backoff, covered by `tests/llm/test_link_runtime_recovery.py`; the rest waits on the SM-12 consolidation) (b) [bend]
  - `penguin/llm/runtime.py:329-347,599-757`,
    `penguin/llm/providers/link/provider.py:205-246`,
    `penguin/llm/adapters/openai.py:920-929`
  - Three independent retry layers. The OpenAI SDK-to-HTTP fallback can emit
    text twice. The Link loop is unbounded. Error sentinels differ by layer.
  - Correction: one retry owner (the runtime); adapters never re-request.
  - Blocked by: SM-12
  - State: (done, 2026-11-14) the runtime's `call_with_retry` is the only layer that replays a failed attempt. The OpenAI SDK-to-HTTP fallback now runs only when the SDK fails before its first event (`_SdkStreamUnavailable`), so it can no longer stream an answer twice; a mid-stream transport failure is a retryable network error and also drops partial tool calls. Link's loop is connection backoff before any output and stays. The differing error sentinels are SM-33's.
- [x] **SM-15 Turn-loop termination, two copies** (a in b) [bend, design]
  - `penguin/engine.py:1679-2060,2306-2451`
  - The task loop and `run_response` disagree on stop, finish-tool status and
    empty responses. The `LENGTH` and malformed-action continues have no
    counter. `CancelledError` skips save and stream abort.
  - Correction: one `LoopOutcome` reducer both loops call; bound every
    continue.
  - State: (partial, 2026-11-13) the output-limit continuation is bounded at 8 consecutive turns in both loops; the task loop then reports `iterations_exceeded`. Still open: the single `LoopOutcome` reducer; the stop, finish-tool and empty-response differences between the two loops; the malformed-action repair continue, which is still unbounded without an iteration cap; `CancelledError` skipping save and stream abort.
  - State: (done, 2026-11-14) one loop: `run_response` now runs `Engine._iteration_loop` like `run_task`, and its own copy of the loop (about 200 lines) is deleted, so stop, finish-tool and empty-response handling no longer differ between the two (results listed under "Decisions taken while away"). Every recovery continue is bounded with no iteration cap: output-limit turns at 8 and malformed-syntax repair turns at 3, both counters reset only by an ordinary turn, so alternating them still ends within 12 turns. A cancelled run saves the conversation before re-raising; the provider step already discarded the uncommitted stream on any failure. Bend model in `prototypes/bend_loop_termination` (draft laws await review) matches Python on all 4825 sequences checked. No separate `LoopOutcome` reducer: with one loop there is nothing left to keep in agreement. Unblocks SM-38.
- [x] **SM-16 Session abort, request accounting and busy/idle** (c) [design]
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
  - State: (partial, 2026-11-13) `process_lifecycle` is now the only writer of the task set and the abort marker (`track_session_task`, `untrack_session_task`, `mark_session_aborted`, `consume_session_abort`) and the only reader of "is a request in flight" (`session_has_active_request`, `active_request_session_ids`); routes, stream events, session view and goal runtime call it. Fixed: a crashed stream no longer leaves the session busy forever; a stale abort marker cancels at most one untracked chunk. Still open: the task set, counter and marker are still three attributes, not one run record (71 test references read them directly); a stale marker can still cancel one later untracked stream; every cancellation still returns as a normal 200; the stream-state and adapter busy sources are unchanged.
  - State: (done apart from one question, 2026-11-14) one `SessionRun` record per session (`tasks`, `requests`, `abort_requested`) in `owner._opencode_session_runs` replaces the three attributes; only `process_lifecycle` reads or writes it, and a record is dropped once nothing is in flight. Busy comes from `process_lifecycle.busy_session_ids` only, which marks a session busy if any live source says so. Fixed with it: a session whose stream was active read as idle when its TUI adapter said idle. Decided by Maximus (2026-11-14): a cancelled `/api/v1/chat/message` keeps returning HTTP 200 with `aborted: true`. Known limits kept: the abort marker is per session, so a second request registering during an abort clears it; with no tracked request, a marker left behind can still cancel one chunk of a later stream.
- [x] **SM-17 Stream scope lifecycle** (c)
  - `penguin/core_runtime/stream_events.py:193-216,604-986`,
    `penguin/core_runtime/process_streaming.py:114`,
    `penguin/engine.py:3363-3532,3847`
  - The scope key is derived three ways with different precedence, and
    `_llm_step` aborts the stream only on `LLMProviderError`.
  - Correction: compute the key once per request and pass it; abort in
    `finally`.
  - State: (partial) `_llm_step` now discards the uncommitted stream on every failure, including cancellation. Still open: the scope key is derived three ways with different precedence (chunks, finalize, abort); duplicate suppression compares the last message's content.
- [x] **SM-18 Engine `_llm_stream` sentinel** (c) [confirmed]
  - `penguin/engine.py:3952-3989`
  - The producer task is never awaited, so an exception leaves the consumer
    waiting forever. Chunks are queued through `create_task` and can land
    after the sentinel.
  - Correction: queue the sentinel in `finally`, put chunks directly, await
    the producer.
- [x] **SM-19 Task status × phase** (b) [confirmed, bend]
  - `penguin/project/models.py:33-79,554,586-681,805-818`,
    `penguin/orchestration/native.py:536`,
    `penguin/web/routes.py:5460`, `penguin/cli/cli.py:3593`
  - `mark_pending_review` and `approve` set `phase = DONE` and then ignore a
    rejected status transition, leaving ACTIVE + DONE. Phase writes are
    unguarded. Web and CLI bypass the manager.
  - Correction: one transition over the (status, phase) pair that either
    applies both or neither and raises on rejection. Law: DONE pairs only with
    PENDING_REVIEW or COMPLETED.
  - State: `mark_pending_review` and `approve` are fixed, and the native
    workflow moves ACTIVE to RUNNING first. Left open: `set_phase`,
    `advance_phase` and the direct `self.phase =` writes are still unguarded;
    web and CLI still call `task.approve` and storage directly. Bend model
    deferred.
- [x] **SM-20 Workflow orchestrator** (b)
  - `penguin/project/workflow_orchestrator.py:104-329`
  - The PR result status is never inspected. `if not success` branches are
    dead. The except handler raises again. Cancellation leaves the task
    RUNNING.
  - Blocked by: SM-19
  - State: the failure handler no longer raises when the FAILED mark is rejected, and a cancelled run returns the task to ACTIVE. Left as is: a failed PR step still ends in PENDING_REVIEW (validation passed; failing the task because GitHub is not configured would be wrong for local use), with the PR result in the workflow result. A non-terminal executor status still leaves the task RUNNING.
- [x] **SM-21 Native and Temporal workflow backends** (c)
  - `penguin/orchestration/native.py:53-56,158-290`,
    `penguin/orchestration/temporal/workflows.py:95,250`,
    `penguin/orchestration/temporal/backend.py:160`
  - A pause saved by `signal_workflow` is overwritten by the runner's next
    save. Cancelling a completed workflow rewrites it. No recovery of RUNNING
    rows after restart.
  - State: pause and cancel no longer rewrite a finished workflow. Still open: a pause saved by `signal_workflow` can be overwritten by the runner's next save of its own in-memory state; RUNNING rows are not recovered after a restart; the Temporal twin is untouched.
- [x] **SM-22 Checkpoint lifecycle** (c)
  - `penguin/system/checkpoint_manager.py:112-300,749`,
    `penguin/system/conversation.py:231-246`
  - The id is returned before the file exists. The live session is
    serialised at dequeue time. Workers can start in a throwaway loop with
    `_workers_started` left True. An index load error resets the index.
  - State: (done, 2026-11-15) a returned checkpoint id now names a file that exists: `create_checkpoint` snapshots the session when called, writes the file on a worker thread (under a temporary name, renamed when complete) and returns the id only after that, or None if the write failed (the web route already turns None into a 500). Automatic checkpoints from `ConversationSystem.add_message` go through `checkpoint_in_background`, which snapshots before returning, so a checkpoint holds the conversation as of its triggering message. The queue and workers are deleted, so there is nothing left to start in a throwaway loop. An unreadable index is set aside and rebuilt from the checkpoint files; a bad entry is skipped. `tests/system/test_log_inspired_checkpoint_lifecycle.py` tested the deleted workers and is removed; its two cases (a manager reused on a new event loop, a failed write) are covered by the new tests.
- [x] **SM-23 Session boundary rollover** (b) (was on hold: re-read 2026-11-13. `add_tool_result` attaches `tool_calls` to the last assistant message only when the result arrives, so at rollover time nothing marks the assistant message as awaiting results. Deferring rollover needs a new signal from the engine that a tool group is open; that is a design change.)
  - `penguin/system/conversation.py:256-269,677`,
    `penguin/system/session_manager.py:578-625`,
    `penguin/system/context_epoch.py:136`
  - Rollover can fire between a tool call and its result.
  - Correction: defer rollover while a tool group is open.
  - State: (fixed, 2026-11-19, a different correction) since SM-111 the continuation keeps the session id and carries recent history, so a rollover after an assistant message no longer loses the message its tool results attach to. One case was left and is fixed here: in a long tool run with no user message in the carried window, the window could open on a tool result whose call stayed in the archive. The window now walks back to the assistant message that made the call (or, with no room, skips the orphaned results).
- [x] **SM-24 Managed process lifecycle** (c)
  - `penguin/tools/process_runtime.py:45-651`
  - `completion_reason` is written from two threads. `stop` can signal a
    reaped pid. `cleanup` holds the lock across blocking stops and drops
    receipts. Lookups race with `_retire`.
  - State: (done, 2026-11-15) the completion reason has one writer rule: `ManagedProcess.claim_completion_reason` sets it under the record's lock only while the process runs and nothing has claimed it, so a stop's `cancelled` is no longer overwritten by a deadline that fires during the stop. `_signal` no longer sends to the group of a reaped shell whose pid is in use again. `cleanup` collects the records under the lock, stops them without it, then retires each one (a record whose receipt cannot be written is kept, so its id cannot be rerun). A retired record is marked, and a poll that finds it retired answers from the receipt, so a request and its retry get the same answer.
- [x] **SM-25 Process completion notice and idempotent start** (c)
  - `penguin/tools/process_tools.py:47-267`,
    `penguin/tools/async_dispatch.py:187-204`
  - Exactly-once delivery depends on the consumer acknowledging. Listeners
    are never unbound. The cancel wait is unbounded.
  - Blocked by: SM-24
  - State: (done, 2026-11-15) a completion notice is claimed, not peeked: `ProcessTools.take_pending` hands each notice out once under the lock, and `prepare_process_step` returns any it could not persist with `restore_pending`, so two steps for one session cannot both persist it and a failed persist is retried. A listener now has a lifetime: `bind` counts a step, `release` (called by `process_session_scope` when the step ends) drops the listener unless the owner still has a running process, and a completion event drops it once nothing can emit to it; a listener on a closed loop is dropped. The cancel wait is bounded (decision recorded).
- [x] **SM-26 Durable chat-request receipt** (c)
  - `penguin/web/services/chat_requests.py:36,85-347`,
    `penguin/web/services/a2a.py:74-248`, `penguin/web/app.py:211`
  - Rows whose owner died stay "recovering" forever. Fingerprints differ by
    caller. Shutdown neither awaits nor cancels in-flight tasks. The A2A
    repair mapper disagrees with the execute mapper.
  - State: (partial, 2026-11-15) fixed: shutdown now stops in-flight durable requests (`stop_chat_requests`, called from the web app's lifespan) so their receipts record a stopped result; the A2A executor and the receipt repair on lookup use one mapping, `settled_task_state`, so a stored `error` result no longer reads as completed after a restart and a stored `provider_error` no longer stays open. Kept as is: the two callers' fingerprints (separate stores; see decisions). Open, needs Maximus: a row whose owner process died without shutting down (a crash or SIGKILL) still stays accepted, so Link and A2A see `recovering` forever. The module docstring makes that deliberate (never replay possibly executed tools). The fix would record an owner heartbeat and report such a row as a final `interrupted` (not replayed) result once the heartbeat is stale, which changes what Link sees.
- [x] **SM-27 WebSocket chat stream** (c)
  - `penguin/web/routes.py:4434-5047`
  - One queue is shared across messages, so a stale sentinel ends the next
    reply early. The socket is not read during processing. Handlers have no
    session filter.
  - State: (done, 2026-11-15) each message on `/api/v1/chat/stream` gets its own queue, and its stream callback is bound to that queue when created, so a chunk a previous reply emits late is dropped instead of opening (or ending) the next reply. The socket is read while a message is processed: a disconnect cancels the processing; a new message is kept and handled next. The tool-event handler forwards only events of the request's session. Not changed: `core.notify_progress` has no callers, and it would call the route's async progress callback without awaiting it, so WebSocket progress events are never sent; left for a later item.
- [x] **SM-28 SSE connection and ledger batch** (c)
  - `penguin/web/sse_events.py:124-461`
  - A full queue drops events silently. The batch is not flushed at shutdown.
  - State: (done, 2026-11-15) a full live queue no longer drops events silently: the connection is marked lagging, stops queueing live events (the ledger already holds them), and once its queue drains the generator replays everything after its last delivered event from the ledger, then replays once more for events emitted during the first replay before resuming live delivery. The reconnect replay and this catch-up share one `replay_after`. The web app's lifespan flushes the pending ledger batch last at shutdown (`flush_runtime_event_ledger`).
- [x] **SM-29 In-process code execution** (c)
  - `penguin/tools/tool_manager.py:342,4967-5024`
  - A timed-out execution keeps running and keeps the lock, so later calls
    queue behind it.
  - State: after a timeout, later calls return `code_execution_busy` at once while the abandoned run is alive, and resume when it ends. The abandoned code itself still runs to completion; in-process Python cannot be stopped. `active_directory` is still restored only when the previous value was truthy.
- [x] **SM-30 RunMode continuous loop and result vocabulary** (b)
  - `penguin/run_mode.py:79-101,444,657-981,1427-1563`
  - Several engine failure statuses fall through as success. The
    empty-response retry has no counter. `start()` checks a status the task
    engine never returns.
  - Blocked by: SM-15
  - State: repeated empty responses now end continuous mode after 5 in a row; the model's emergency stop ends it; the retry branch no longer crashes on a missing `MessageCategory.WARNING`. (2026-11-19) Also fixed: engine statuses `stopped`, `budget_limited` and `provider_error` now end continuous mode, and `error` / `provider_recoverable_error` pause, then end it after 5 failed tasks in a row whatever the completion type; before, they fell through every branch and the loop started the next task at once, without yielding (a hot loop of provider calls on, say, a 402). Still open: `start()` checks a status the task engine never returns; `waiting_input` is not handled in the continuous loop.
- [x] **SM-31 `utils` event bus subscription liveness** (c) [confirmed]
  - `penguin/utils/events.py:79,117,128`
  - Handlers are stored as `weakref.ref`, which is dead immediately for bound
    methods. `publish` mutates the list it iterates and holds a lock across
    handler awaits.
  - Correction: `weakref.WeakMethod` for bound methods, or strong references
    with explicit unsubscribe.

## Tier 2: drift, leaks, duplicated truth

- [x] **SM-32 `LLMRequestLifecycle.status`** (b) [bend]: `penguin/llm/contracts.py:72,194`; update helper copy-pasted in three adapters; no terminal guard; `RETRYING` never written. Blocked by SM-12.
  - State: (done, 2026-11-14) one guarded transition, `next_request_status` in `penguin/llm/contracts.py`, applied by `LLMRequestLifecycle.advance` and `finish`. The three copied `_update_request_lifecycle` / `_finish_request_lifecycle_from_state` helpers now delegate to it, and Link no longer writes `status` directly. Link marks its reconnect wait `RETRYING`, so cancelling it no longer overwrites a finished attempt. Bend model in `prototypes/bend_request_lifecycle` (draft laws await review).
- [x] **SM-33 Call outcome classification** (a) [bend]: `penguin/llm/api_client.py:535-992`, `penguin/llm/runtime.py:286`; computed twice with different rules. Blocked by SM-12.
  - State: (done, 2026-11-14) one rule, `classify_call_outcome` in `penguin/llm/contracts.py`, used by `APIClient._build_response_result` and by the runtime's fallback for clients without typed results; the fallback now also reads the lifecycle from the client or its handler. Fixed: that fallback reported a cancelled request, or a failed one with no recorded error, as completed. Bend model added to `prototypes/bend_request_lifecycle` (`outcome.bend`). Not changed: the text-prefix checks for error strings (`[Error:`) in `APIClient.get_response` and `runtime._is_provider_error_response`, which format and gate retries rather than classify.
- [x] **SM-34 Tool-replay adjacency repair, three copies** (a): `openai.py:1342-1519`, `openrouter.py:1201-1366`, `anthropic.py:1341-1418`; each provider treats orphans differently; OpenRouter rewrites `call_…` tokens in plain content.
  - State: (partial) the OpenRouter rewrite of `call_…` tokens in plain content is limited to tokens that look like call ids, so code such as `call_api` is no longer mangled. Still open: the three providers treat orphaned tool calls and results differently; OpenAI drops a call whose output text is empty.
- [ ] **SM-35 Per-request `last_*` state on the adapter** (on hold 2026-11-15: needs a design choice, see State) (c) [design]: resets at `openai.py:820`, `openrouter.py:1404`, `anthropic.py:700`; Link resets a subset; `prepare_native_tool_kwargs` flips `interrupt_on_tool_call` permanently (`runtime.py:424`). See `model-config-mutation-state-leak.md`.
  - State: (on hold, 2026-11-15) re-read: every adapter keeps about seven per-request fields on itself (`_last_error`, `_last_finish_reason`, `_last_usage`, `_last_reasoning`, `_last_request_lifecycle`, `_tool_calls`, Link's `_last_provider_data`), and one adapter instance serves every session. Two sessions streaming at once can read each other's finish reason or drain each other's pending tool calls. Choices for Maximus: (a) scope those fields to the request with a context variable set when `get_response` starts (small change, but values set inside a provider call that runs in another task or thread would not reach the engine); (b) return them in one per-request result object that the engine reads instead of `get_last_*` (larger, explicit); (c) one adapter instance per session. The `interrupt_on_tool_call` flip in `prepare_native_tool_kwargs` is harmless today (every reader also needs a tool call) and belongs to the ModelConfig ownership decision in `context/tasks/model-config-mutation-state-leak.md`.
- [x] **SM-36 Reasoning-variant override** (b): `penguin/web/routes.py:1063-1091,4191,4418,4796`; the REST restore may write a deep-copied config's snapshot onto the global config. Unconfirmed.
  - State: confirmed and fixed: the override snapshot now records which config it changed, and the restore uses that. The WebSocket path applies its override outside its `try/finally`; not changed.
- [x] **SM-37 Model switch propagation** (b): `penguin/core_runtime/model_runtime.py:107-375`; multi-step, non-atomic, failures downgraded to warnings.
  - State: (done, 2026-11-15) a model switch is all or nothing: `apply_new_model_config` builds and prepares the new API client first and only then switches the core, conversation manager, context window and engine together; if the client cannot be built (missing credential, unknown provider) the error reaches `load_model_for_core`, which reports failure with nothing changed. Before, the core already named the new model while requests still went to the old client. `refresh_api_client` and the switch share one wiring helper; the try/except-and-warn wrappers around plain attribute assignments are gone.
- [x] **SM-38 Stall / empty / repeat guard** (a) [bend]: `penguin/engine.py:304-418,1376-1602`; counters reset in four places; recovery never re-arms; a kill in response mode looks like `completed`. Blocked by SM-15.
  - State: (partial, 2026-11-15) fixed: a guard stop is no longer reported as a finished run; it carries its reason (`repeated_response`, `tool_result_echo`, `empty_responses`) in both modes, and a plain answer still ends with the default status. Needs Maximus: "recovery never re-arms" is what the human-owned law `recovery_at_most_once` in `prototypes/bend_loop_recovery/LAWS.bend` requires; re-arming after progress would need that law changed (and a cap on recoveries per run, or alternating stall and progress never ends). Not done: the guard's counters still reset in four places (each guard resets its own counter on progress); folding them into one pure decision, which the Bend lane would model, is left for a later pass.
- [x] **SM-39 Per-session stream state dict** (c): `penguin/core_runtime/stream_events.py:68-85,448,1247-1349`; `active` with no message id exists across an await; adapter map entries leak. Blocked by SM-16.
  - State: (done, 2026-11-15) `handle_tui_stream_chunk` no longer marks a new stream active before its message exists: the state is set inactive (keeping the previous message as the session's latest) while `on_stream_start` runs, then active, stream id, message id and part id are set together. A stream that this module ends (switching streams, the final chunk, or an abort that force-finalizes) now removes its entry from `_opencode_message_adapters`; usage arriving later falls back to the session's cached adapter, which is the same instance. `test_handle_tui_stream_chunk_starts_tracks_and_finalizes_stream` asserted the leaked entry and now asserts its removal.
- [x] **SM-40 Session-goal run claim** (c): `penguin/core_runtime/session_goal_runtime.py:741-1079`; gate checked at 844 and acquired at 883; orphan test assumes one process per workspace.
  - State: (done, 2026-11-15) the session gate is taken in the run's own task before the claim is recorded (an unlocked gate is taken without waiting), so no other request can hold the session while the goal record says the goal is running; if saving the claim fails the gate is released. Orphan recovery no longer assumes one process per workspace: a claim whose owner is a live process on this host is refused with a conflict; only claims whose owner process is gone, or that come from another host or an older owner-id format, are recovered.
- [x] **SM-41 RunMode singleton lifecycle** (b): `penguin/core_runtime/runmode_lifecycle.py:29-92`; no re-entrancy guard.
  - State: (done, 2026-11-15) `start_run_mode` refuses to start while another RunMode is active on the same core, raising `RunModeBusyError` (a `PenguinError`, code `RUNMODE_BUSY`) before touching any shared state. Before, a second start overwrote the running RunMode's stream callback, UI callback and `run_mode`, and the first run's cleanup then cleared them under the second.
- [ ] **SM-42 MCP connection lifecycle** (on hold 2026-11-13: retrying discovery after every failure changes how often servers are contacted; needs a retry policy decision) (b): `penguin/tools/providers/mcp.py:22-115`, `penguin/integrations/mcp/manager.py:71-503`; a failed discovery is sticky; (FAILED, session set) is representable; `_ensure_actor` is unlocked; `list_changed` is never consumed.
- [x] **SM-43 Plugin lifecycle** (b): `penguin/plugins/plugin_manager.py:52-483`; parallel load looks like a deadlock (not run); action unregistration compares the wrong name.
  - State: action unregistration now compares against the plugin name. Not examined: the reported deadlock in parallel `load_all_plugins`, tool-name collisions, and the LOADING/ERROR status moves.
- [x] **SM-44 Streaming action-tag stripper** (b): `penguin/tui_adapter/part_events.py:112,181-267`; an unterminated tag drops all later text; reasoning and content share one parser state. Blocked by SM-02.
  - State: (done, 2026-11-15) the stripper is now `ActionTagFilter` (`penguin/tui_adapter/action_tag_filter.py`), one per channel, so reasoning and assistant text no longer share parser state. It holds back the text from an opening action tag onward and drops it when the tag closes; when the stream ends first, `on_stream_end` emits the held text into its part, so an unterminated tag no longer hides the rest of the reply.
- [ ] **SM-45 Message / part / tool lifecycle** (re-read 2026-11-13: `on_assistant_error` emits a separate, already-completed error message; whether it should also end the active stream depends on who calls it and in what order, so it is left for a decision) (c): `penguin/tui_adapter/part_events.py:97-769`; the error path leaves `_stream_active` set; two sources of truth for active tools.
- [x] **SM-46 Headless CLI streaming display** (c): `penguin/cli/streaming_manager.py:27-80`, `penguin/cli/streaming_display.py:53-201`, `penguin/cli/cli.py:3763-4617`, `penguin/cli/event_manager.py:151-291`; stopping the spinner leaves the stream id set; five copies of the cleanup.
  - State: (done, 2026-11-15) one reset, `StreamingManager.reset_stream_state`, now forgets a stream (id, streaming flag, both buffers) and replaces the copies in `finalize_streaming`, the event manager's final-chunk path and the chat loop's per-turn reset. `safely_stop_progress` calls it when it stops a live streaming display, so stopping the display no longer leaves the stream id set; and the event manager now stops old displays before it records the new stream's id. Before, the next stream in the same turn was ignored as a foreign stream. Left as is: `cli.py` still carries its own unused `_active_stream_id` and `_streaming_session_id` fields, which `_finalize_streaming` clears.
- [x] **SM-47 CLI event bus delivery and dedup** (c): `penguin/cli/events.py:107-234`; events without `content` share a dedup key; sync handlers mutate display state from a worker thread.
  - State: events without `content` are deduplicated on their whole payload. Still open: sync handlers run on a worker thread and mutate display state unlocked; `PenguinCLI` never unsubscribes.
- [x] **SM-48 Launcher web-server ownership** (b): `penguin/cli/opencode_launcher.py:205-276,964-1054`; a foreign server on the port counts as ours; no SIGTERM handler.
  - State: (done, 2026-11-15) `_is_server_running` requires Penguin's health payload, not just HTTP 200; `_wait_for_server` checks that the launcher's own child is still running before it accepts a healthy answer, so a server that took the port after the child exited is not taken for the launcher's own. `main` installs a SIGTERM handler for the launcher's run that exits normally (status 143), so the web server it started is stopped by the existing `finally` and `atexit` cleanup, and restores the previous handler afterwards.
- [x] **SM-49 Provider OAuth pending flow** (c): `penguin/web/services/provider_auth.py:40-512,1023-1227`; one slot per provider, popped by provider and not by state; four TODOs already name the gaps.
  - State: (partial, 2026-11-15) fixed: each pending authorization gets a `flow_id`, and a completed callback (browser listener or explicit callback) removes the provider's pending entry only if it still holds that flow, so a newer authorization started meanwhile keeps working; the recent-completion fast path now applies only to a caller waiting for the browser flow (no code), so a pasted stale code fails instead of reporting success. Kept: one pending slot per provider (a new authorize replaces the old one by design). Still open: the browser-callback listener binds one host (its TODO), so a `localhost` redirect can miss a `127.0.0.1` listener.
- [x] **SM-50 OpenAI OAuth resolve and refresh** (b): `penguin/llm/adapters/openai.py:1019-1145`; resolve and peek duplicate env parsing; refresh writes process-wide state unlocked.
  - State: (done, 2026-11-15) request preparation and the request read OAuth credentials the same way: a stored OAuth record wins, otherwise the environment, parsed once by `_oauth_record_from_env`. Before, preparation skipped a stored record without an access token and routed on an environment token, while the request used the stored record and failed. Not changed: `_apply_oauth_record_to_runtime` still writes `os.environ` and `model_config.api_key`; on one event loop a read that needs no refresh is applied without awaiting, so a stale token cannot overwrite a newer one, and `refresh_provider_oauth` already refreshes once under a lock. Writing to shared config belongs to the ModelConfig ownership decision (SM-35).
- [x] **SM-51 ACP session turn** (closed as stale, 2026-11-19; stale since 2026-11-13: `cancel` on main now captures `session.task` before awaiting, so the `None.cancel()` path is gone) (c): `penguin/integrations/acp/server.py:39-187`; `cancel` can call `.cancel()` on a task already set to None.
- [x] **SM-52 Run-mode task WebSocket** (b): `penguin/web/routes.py:6682-6886`; `core._temp_ws_callback` is a single slot.
  - State: (partial, 2026-11-15) fixed: the run-mode task WebSocket's event callback is now an argument of `start_run_mode` (`websocket_event_callback`); the RunMode lifecycle installs it in `_temp_ws_callback` after its busy check and clears it in its own cleanup. Before, the route set the slot before starting, so a second socket took over the running task's events (its own start then failed with `RunModeBusyError`) and either socket's exit deleted the slot. (2026-11-17) Also fixed: the stream finalizer sends a finalized message to the RunMode socket only from inside that run (a context variable set by `start_run_mode` and inherited by the run's tasks); before, it forwarded every session's finalized messages while the slot was set, a cross-session data leak.
- [x] **SM-53 Sub-agent registry** (b): `penguin/system/conversation_manager.py:224-240,340,501-582,1598`; removing the current agent leaves three "current" pointers stale.
  - State: (done, 2026-11-15) removing the current agent now calls `set_current_agent("default")`, which moves the conversation, session manager, checkpoint manager, context window and context loader together. Before, only `current_agent_id` and `conversation` moved, so session saves, checkpoints and context trimming kept using the removed agent's objects. The no-op context-loader block in `remove_agent` is gone.
- [x] **SM-54 AgentExecutor task state** (c): `penguin/multi/executor.py:212-443`, `penguin/multi/coordinator.py:309`; PAUSED is a label only; `cancel()` overwrites a finished state.
  - State: `cancel()` keeps an outcome the agent reached while the cancel was in flight. Still open: PAUSED is a label only; finished ids block respawn until `cleanup()`; three places track agent liveness with no reconciliation.
- [x] **SM-55 Context window trimming and epoch** (a) [bend]: `penguin/system/context_window.py:272-1220`, `penguin/system/context_epoch.py:24-155`; total over budget with every category under its own budget trims nothing. Keep the category-priority trimming model; do not introduce compaction.
  - State: (done, Bend lane added 2026-11-15) `trim_session` now trims, while the session is over the window, categories that are within their own budget too: lowest priority first, oldest message first, down to each category's minimum, never SYSTEM. The default category budgets (10/30/40/20 percent plus 5 percent for each other category) add up to more than the window, so a session could exceed it with every category within budget, and nothing was trimmed; the request then went out over the window. Category-priority trimming is kept; nothing is summarised. `test_context_window_trim_preserves_non_primary_categories` set a 1-token window and relied on the old behaviour; it now uses a window the session fits. Bend lane: `prototypes/bend_context_trim/` models SYSTEM, DIALOG and SYSTEM_OUTPUT in a 6-token window; its laws (draft, awaiting review) say the session fits unless both trimmable categories are at their minimums, an in-budget session is untouched, the lower-priority category goes first, and a category at its minimum is kept. The minimum is a target, not a floor: whole messages are removed, so a category can end below it by part of one message.
- [x] **SM-56 Edit commit and rollback** (b): `penguin/tools/editing/service.py:507-533`, `penguin/tools/editing/legacy_multifile.py:164-262`; the snapshot is appended after the write.
  - State: the snapshot is recorded before the write, so a file that fails part way through is restored. Still open: writes are not atomic; there is no check that the file is unchanged since `old_content` was read; the legacy multi-file path.
- [x] **SM-57 File-root / execution mode** (b): `penguin/tools/tool_manager.py:4030-4166`, `penguin/config.py:532,597`; three writers disagree on env vars and the notebook directory.
  - State: (done, 2026-11-15) one method, `ToolManager._use_file_root`, now sets the active file root, `PENGUIN_WRITE_ROOT`, `PENGUIN_CWD`, the notebook executor's directory and the file map; `set_execution_root` and every RuntimeConfig change (project root, workspace root, execution mode) go through it. Before, a root change from RuntimeConfig left the notebook executor in the old directory. `RuntimeConfig.set_project_root` and `set_workspace_root` now set `PENGUIN_CWD` to the active root; before, a project-root change in workspace mode pointed it at the project root, and a workspace-root change did not update it.
- [x] **SM-58 PyDoll browser session** (b): `penguin/tools/pydoll_tools.py:14-201`; (browser set, not initialized) is reachable; a dead cleanup task blocks the idle timer.
  - State: a finished idle-timer task no longer blocks a new one. (2026-11-19) Also fixed: a failed `start()` left (browser set, not initialized), which the next `initialize` took for a running browser and reported success; the half-made browser is now stopped and dropped, so the next call starts again. Still open: the idle worker awaits its own cancellation in `close()`; no lock around `initialize`.
- [x] **SM-59 Browser-harness daemon identity** (c): `penguin/tools/browser_harness_tools.py:24,264-426`, `penguin/tools/browser_harness_ownership.py:81`; cleanup runs without the helpers lock.
  - State: (done, 2026-11-15) `BrowserHarnessAdapter.cleanup` now holds `_HELPERS_LOCK` like every other harness call. It reloads the harness modules for its target daemon and rewrites `BU_NAME` in the process environment, so without the lock it could repoint a helper call in progress at another daemon, and its ownership-file read-modify-write could interleave with `record_started`. Not changed: the ownership file is still shared between Penguin processes without a file lock.
- [x] **SM-60 Lazy tool loading** (b): `penguin/tools/tool_manager.py:278,2231-2907,6355`; check-then-set with no lock on worker threads.
  - State: (done, 2026-11-15) every synchronous lazy tool property (task, skill, memory note, grep, file map, summary notes, notebook, Perplexity, browser, browser-harness and PyDoll tools) now re-checks its flag under one per-manager `RLock` before building, so two tool calls on worker threads build a tool once and get the same object. Before, both could build it and one was silently replaced (two notebook executors, or two browser managers). Not changed: the async `ensure_memory_provider` (a thread lock does not help across its awaits).
- [x] **SM-61 Memory incremental index** (c): `penguin/memory/indexing/incremental.py:47-142`, `penguin/memory/indexing/metadata.py:38-108`; re-index duplicates entries; non-atomic metadata write.
  - State: (done, 2026-11-15) the index metadata now records the memory id that holds each file, and re-indexing a changed file adds the new memory and then deletes the previous one (added first, so a failed delete leaves a duplicate rather than no memory). Before, every edit left another copy. `IndexMetadata._save_metadata` writes to a `.partial` file and replaces the real one only when complete; before, a failed write left a corrupt file that loaded as empty, so every file was indexed again. Not changed: `remove_from_index` (a deleted file) still removes only metadata, because it is synchronous and the provider's delete is async; and a file queued twice can still be processed by two workers at once.
- [x] **SM-62 Git PR flow** (b): `penguin/project/git_manager.py:153-308`; no checkout back to base on failure.
  - State: (done, 2026-11-15) `create_pr_for_task` records the current branch before creating the feature branch and, if committing, pushing or opening the PR fails, checks that branch out again (new `GitIntegration.checkout`). Before, the repository stayed on the feature branch and the next task branched from it. Not changed: a successful PR leaves the feature branch checked out; a detached or unknown starting point is not restored.

## Tier 3: minor, legacy, or probably deletable

Check for callers first. If there are none, delete.

- [x] **SM-63 Interrupt flags** (a): `penguin/engine.py:765`, `penguin/run_mode.py:81,479,757`, `penguin/core_runtime/core_state.py:56`; `Engine._interrupted` is never read; `core._interrupted` is never set True.
  - State: `Engine._interrupted` is deleted; nothing read it. Left in place: `core._interrupted` (read by the continuous loop and exposed by `process_facade`, though nothing sets it to True) and `RunMode._interrupted` (set by the MCP run-mode tool); removing those changes a public attribute and an MCP tool's behaviour.
- [x] **SM-64 Legacy `get_response` retry** (b): `penguin/core_runtime/response_generation.py:31-114`; swallows cancellation and persists an apology string.
  - State: (done, 2026-11-15) kept, not deleted: `core.get_response` is still called by `process_runtime` when no engine is present and by `interfaces/web.py`. A cancelled provider call now re-raises instead of being logged and retried, and after empty answers the apology is returned for display (with `error: empty_response`) but no longer saved into the conversation as the assistant's own message. `test_get_response_uses_fallback_after_empty_response_retries` asserted the saved apology and now asserts it is not saved.
- [x] **SM-65 Legacy `local_task` status strings** (b): `penguin/local_task/manager.py:137-182` and bypass sites; handlers are unreachable until SM-31 is fixed. Still imported by `utils/parser.py:22`.
  - State: (done, 2026-11-15) kept, not deleted: `ProjectManager` from `local_task` is still imported by `utils/parser.py` and `utils/plugin_parser.py`, and SM-31 made its bus handlers live. Every status change now goes through `Task.transition_to`: the completion and failure event handlers, `complete`, `complete_task`, the execution-record fallbacks and project completion used to assign `task.status` directly, so a cancelled or archived task could be marked completed. `transition_to` treats a same-state move as a no-op and no longer forces the new state when it hits an error. `complete_task` returns an error and `complete` raises `ValueError` when the table refuses the move.
- [x] **SM-66 Legacy process attach** (b): `penguin/utils/parser.py:1112,2015-2038`, `penguin/utils/process_manager.py:13-160`.
  - State: (done, 2026-11-15) the ActionXML process tags (`process_start`, `stop`, `status`, `list`, `enter`, `send`, `exit`) in `ActionExecutor` now run on `ToolManager.process_runtime` with the execution context's owner, the same runtime and ownership as the native tools; `ProcessRuntime.list_processes` is added for `process_list`. The legacy `ProcessManager` overwrote a running process when a name was reused, blocked the event loop while stopping, let unread output pipes fill and hang the child, closed the child's stdin on `process_exit`, and `process_enter` waited forever for output from a silent process (the old code hung the new test). Left for Maximus: `utils/process_manager.py` and `utils/plugin_parser.py` (no importers) can be deleted.
- [ ] **SM-67 Legacy Textual TUI stream** (on hold 2026-11-15: deletion is Maximus's call) (c): `penguin/cli/tui.py:1473-2614`; referenced only from `misc/` and a prototype.
  - State: (on hold, 2026-11-15) not deleted: `penguin/cli/tui.py` (3,708 lines) is still imported by `penguin/cli/tui_prototype_mock.py`, which backs the packaged `penguin-tui-proto` script, and the `legacy_tui` extra installs Textual for it. Deleting it means dropping that script and extra; that is a packaging decision for Maximus.
- [ ] **SM-68 Legacy `BrowserManager`** (on hold 2026-11-15: removal is Maximus's call) (b): `penguin/tools/browser_tools.py:42,181`; `initialize` always returns False.
  - State: (on hold, 2026-11-15) not removed: `browser_manager` is exported from `penguin.tools` and imported by `ToolManager`, and the legacy `browser_navigate`, `browser_interact` and `browser_screenshot` tools are still advertised to the model, although `BrowserManager.initialize` always returns False, so they always answer "Failed to initialize browser". Choices for Maximus: stop advertising them, route them to the PyDoll tools, or delete the legacy module and its exports.
- [x] **SM-69 REPL interrupt and turn loop** (b): `penguin/cli/cli.py:4103-4602`, `penguin/cli/session_manager.py:52`; Ctrl-C during processing never cancels the core; `/exit` sets a flag nothing checks.
  - State: (partial, 2026-11-15) fixed: `/exit` now ends the headless REPL. The interface returned `status: exit` and marked itself inactive, but the chat loop checked neither and prompted again; it now leaves the loop when a command returns `status: exit`. Not verified, so not changed: whether Ctrl-C during processing reaches `core.process`. The loop awaits the core in the same task, so asyncio's SIGINT handling should cancel it, but `process_runtime` turns that cancellation into an aborted result, and confirming this needs an interactive terminal.
- [x] **SM-70 CLI message dedupe** (a): `penguin/cli/cli.py:3754-4151`, `penguin/cli/event_manager.py:130-189`; keyed on the first 50 characters, never pruned.
  - State: (partial) a reply in a later turn that opens with the same 50 characters is no longer hidden; the key is a duplicate only within the turn that recorded it. Left as is: user messages keep the session-wide check, because the turn only advances on a user message and a repeated `continue` cannot be told from a double delivery by content alone; the sets are still never pruned.
- [x] **SM-71 Config root and env precedence** (b): `penguin/config.py:30-831`; module-level `config` never reloads; a project `.env` overrides shell-exported keys.
  - State: (partial, 2026-11-15) fixed: `_ensure_env_loaded` no longer lets the project `.env` override keys exported in the shell; it loads the project file and then the user-level file, both without override, so the order is shell, project, user. Not changed: the module-level `config` is still loaded once at import and never reloaded; and `find_dotenv` still searches from Penguin's own source directory, not the user's working directory (changing that could break development setups that keep keys in the repository's `.env`).
- [x] **SM-72 Sidecar binary cache** (b): `penguin/cli/opencode_launcher.py:531-717`; a partial copy passes the existence check.
  - State: the binary is copied to a sibling temporary file and renamed into place. No failing-first run: the helper is new; the old code copied straight to the final path. Still open: no lock between concurrent launchers; the marker is trusted with only an existence check.
- [x] **SM-73 First-run setup marker** (b): `penguin/setup/wizard.py:123-354`; the marker file is written and never read.
  - State: (done, 2026-11-15) deleted: `mark_setup_complete` and `_setup_complete_path`. The `.penguin_setup_complete` marker (holding the user name and host name) was written after setup and never read; `check_first_run` deliberately reads the saved workspace config instead. Marker files already on disk are left alone. `tests/test_setup_wizard.py` asserted the marker and now asserts `check_first_run()` is false after setup.
- [x] **SM-74 Skills activation, QuestionManager, ProcessWaitGuard** (b): `penguin/skills/manager.py:21-112`, `penguin/security/question.py:73-257`, `penguin/tools/process_wait.py:17`; unpruned sets and no expiry.
  - State: (partial, 2026-11-15) fixed: `QuestionManager` keeps at most 1000 resolved questions (`MAX_RESOLVED_QUESTIONS`), dropping the oldest, like approval history (SM-04); before, every answered or rejected question stayed for the life of the process. Checked and left: `ProcessWaitGuard` progress is cleared at the start of every run (`LoopState.reset`). Left: `SkillManager` keeps one small set of activated skill names per session ever seen; it has no session-end hook to prune from.
- [x] **SM-75 Small singletons and slots**: `CircuitBreaker` string state (`penguin/project/resilience.py:97`), `RuntimeJobRecord.status` upsert (`penguin/project/storage.py:488`), `PenguinState._previous_state` (`penguin/system/state.py:471`), DAG cache invalidation (`penguin/project/manager.py:1340`), MessageBus drop (`penguin/system/message_bus.py:92`), VCS watcher slot (`penguin/web/services/system_status.py:20`), title refresh tasks (`penguin/web/routes.py:963`), `events_ws` (`penguin/web/routes.py:2367`), connection pool `close_all` (`penguin/llm/api_client.py:164`), core/app singletons (`penguin/web/app.py:36,212`).
  - State: (2026-11-15) fixed: a runtime job upsert no longer changes a terminal status (`completed`, `failed`, `cancelled`) unless the new status is the same, so a late cancel request cannot reopen a finished job; `PenguinState` keeps one previous state per system, so resuming one system no longer restores another system's state; the task DAG is rebuilt on every call instead of cached until a blueprint sync (other modules write tasks straight to storage, so no cache could stay in step); pending `vcs.branch.updated` emits are kept in a set until done (the single slot let the garbage collector destroy a pending emit when two scopes changed together); `events_ws` reads the socket, so a client that leaves ends the handler and unsubscribes it from both event buses (before, each one stayed subscribed until shutdown); `ConnectionPoolManager.close_all` takes the clients out of the pool before closing them, so `get_client` never returns a closing client and a client made meanwhile is not dropped unclosed. Deleted: `penguin/project/resilience.py` (`CircuitBreaker`), unused. Checked and left: `MessageBus.send` already returns `False` and logs when no handler takes a message; title refresh tasks are deduped per session and hold strong references (a cancelled one logs noise from its done callback); the app core is one lazily made instance per process.
- [x] **SM-76 Second sweep** of the directories listed as not opened, and of any file touched since `36e32f623`.
  - State: (2026-11-15) done: three read-only readers covered the never-opened modules, `penguin/integrations/acp/`, and the rest of the code `main` changed after `36e32f623`. Their 32 findings are SM-77 to SM-108 under "Second sweep (SM-76)"; three side notes are under "Seen in passing". Reported clean: `multi/admission.py`, `multi/routing.py`, `security/tool_capabilities.py`, `security/scoped_paths.py`.

## Second sweep (SM-76), 2026-11-15

Three read-only readers covered the directories the first sweep never opened,
`penguin/integrations/acp/`, and the rest of the code `main` changed after
`36e32f623`. Line numbers are from `3988ba33c`. Every entry is a reader's
claim from code until step 2 of the loop reproduces it; **[confirmed]** marks
the ones re-read against the code. SM-79 was found by two readers
independently.

### Tier 0

- [x] **SM-77 Runtime security mode never reaches enforcement** (a) [security]: `penguin/config.py:605-650` notifies observers, but `ToolManager.on_runtime_config_change` (`penguin/tools/tool_manager.py:4277-4301`) handles only roots and execution mode; the enforcer's mode is fixed at first use (`:2404-2443`) and `_permission_enabled` comes only from `PENGUIN_YOLO` (`:356-358`). `PATCH /api/v1/security/config {"mode":"read_only"}` reports success while writes stay allowed; `/security/yolo` reports checks off while they stay on. Correction: rebuild the enforcer and permission flag from RuntimeConfig on change.
  - State: (2026-11-15) fixed: `ToolManager.on_runtime_config_change` now applies `security_mode` and `security_enabled`, and a mode, enabled or root change drops the permission enforcer so the next check rebuilds it from the current mode and roots. Before, a runtime mode or YOLO change was reported by the API but not enforced, and the workspace boundary kept the roots of its first build. Left: `security.enabled: false` in config makes `RuntimeConfig` (and the API) report checks as off while the tool manager still enforces them (only `PENGUIN_YOLO` turns them off); making enforcement follow the config would turn checks off, so it is Maximus's call.
- [x] **SM-78 Runtime event ids reused after a restart** (c) [confirmed]: `penguin/system/runtime_events.py:56-57,169-175,620-626` count each stream from 1 per process; the ledger (`penguin/system/runtime_event_ledger.py:238`, `INSERT OR IGNORE` on `event_id`) outlives the process and resolves replay cursors by id (`:335-341`). After a restart, new events with old ids are dropped from the ledger and a reconnect replays the previous run's events. The docs promise a stable replay id and a monotonic per-stream sequence. Correction: start each stream's counter after the ledger's highest sequence for it.
  - State: (2026-11-15) fixed: opening the runtime event ledger now sets a sequence floor, so each stream new to the process continues after the highest sequence the ledger holds for it (`RuntimeEventLedger.last_sequence`, `set_runtime_event_sequence_floor`), and the web app opens the ledger before it builds its core. The id format is unchanged. `reset_runtime_event_sequences` (tests only) also clears the floor. Left: two processes writing the same stream of one ledger at the same time can still collide; Penguin runs one web server per workspace. `_SEQUENCE_COUNTERS` still keeps one small entry per stream seen.
- [x] **SM-79 Steering messages stranded when the recipient's session changes** (c): `penguin/multi/mailbox.py:21-58` keys the queue by `(agent, session)` at send time (`penguin/engine.py:1063-1072`); a continuation session (`penguin/system/conversation.py:233-247`) or a session switch gives the agent a new id, so `deliver`/`has_pending` never see the message while `send_message` reported it delivered and `status()` counts it forever. Correction: key pending messages by agent.
  - State: (2026-11-15) fixed: the mailbox treats a continuation session as the same conversation as the session it continues (`continued_from`). `deliver` moves steering queued for the previous session to the front of the current one, and `has_pending` takes the session object (the engine now passes it) and sees both. Steering stays bound to its conversation: a switch to an unrelated session still does not receive it. Left: only one continuation step is followed, and a session switched away from keeps its queue until the agent returns to it or is removed.
- [x] **SM-80 Session eviction drops a session whose save failed** (b): `penguin/system/session_manager.py:425-435` deletes the oldest cached session whatever `save_session` returned (`:596-600` re-marks it dirty first). Correction: do not evict a session that failed to save.
  - State: (2026-11-15) fixed: when the session cache is full, the least recently used session that is saved is evicted; a modified session whose save fails, or that changed during the save, stays in memory and the next candidate is tried. If none can be evicted the cache briefly exceeds its limit rather than dropping unsaved messages.

### Tier 1

- [x] **SM-81 Runtime event ledger flush protocol** (c): `penguin/web/sse_events.py:432-491`. A failing flush requeues the whole batch with no bound, and past 256 events every new event re-flushes inline inside `EventBus.emit`; concurrent flushes (per-connection cadence, recorder, replay pre-flush, shutdown) take disjoint batches with no lock, so rowid order (`penguin/system/runtime_event_ledger.py:343-360`) can differ from emit order and a replay can miss events held by an in-flight flush. Also `event_handler` (`:249`) is sync, so it runs on a thread pool and calls `asyncio.Queue.put_nowait` off the loop. Correction: one flush lock per core held across take, write and requeue; a bounded requeue; no inline re-flush while one is failing.
  - State: (2026-11-15) fixed: ledger flushes run one at a time per core (an `asyncio.Lock` held across take, write and requeue), so rows commit in emission order and a replay or disconnect flush waits for one in progress. After a failed write, the streaming cadence and the full-batch flush inside `emit` skip for 5 s instead of retrying the whole backlog on every event; replay, disconnect and shutdown flushes still retry. The unsaved backlog is capped at 10 000 events (oldest dropped, with a warning; replay reports a gap). The SSE `event_handler` is now async, so the CLI EventBus runs it on the loop instead of a worker thread. Left: a backlog drop while the ledger is healthy but a flush is stuck leaves no gap marker for a cursor before the dropped events.
- [x] **SM-82 Ollama streaming and finish reason** (b): `penguin/llm/adapters/ollama.py:72-93` calls the adapted stream callback with one argument (`penguin/utils/callbacks.py:56` needs two), so streaming fails on the first token; `done_reason` is ignored, so a reply cut by `num_predict` reports as complete. Correction: pass `(text, "assistant")`, keep `done_reason`, expose the last finish reason.
  - State: (2026-11-15) fixed: `OllamaAdapter` normalises its stream callback with `adapt_stream_callback` and calls it as `(chunk, "assistant")`, so APIClient's callback no longer fails on the first token; it records `done_reason` from the final chunk (or the non-streamed reply) and exposes it through `get_last_finish_reason`, so a reply cut by `num_predict` reports `LENGTH` and a stream that never sent its final chunk reports `UNKNOWN`, not a normal stop; an empty stream returns nothing instead of raising. Left: no `get_last_usage` (Ollama reports `prompt_eval_count`/`eval_count`) and no `get_last_error`.
- [x] **SM-83 Two agent executors in a normal runtime** (c): `penguin/tools/tool_manager.py:6583-6594` uses its own `AgentExecutor` unless isolated, while ActionXML spawn, stop and delegate (`penguin/utils/parser.py:2454-2457,2820,3129-3132`) use the global one, and wait/status/shutdown read ToolManager's. An ActionXML background agent cannot be waited on, stopped or shut down. Correction: one executor per core.
  - State: (2026-11-15) fixed: outside an isolated runtime, `ToolManager._get_agent_executor` adopts the global executor when it serves the same core, and otherwise registers the one it creates as the global, so CLI commands that call `get_executor()` see the same agents. ActionXML spawn, stop and delegate go through `ActionExecutor._agent_executor`, which asks the tool manager. A background agent started by either path can now be waited on, stopped and shut down by the other. Left: with two cores in one non-isolated process, `get_executor()` callers outside the tool manager see the most recently registered core's executor.
- [x] **SM-84 A steering message in the last iteration drops the finish signal** (b): `penguin/engine.py:1888-1894` continues on a pending message before the termination check, so with `max_iterations=N` a `finish_task` in iteration N becomes `iterations_exceeded`. Correction: only continue when another iteration is allowed.
  - State: (2026-11-15) fixed: the steering `continue` in `Engine._iteration_loop` now also requires that another turn is allowed (iteration limit and token budget); otherwise the finish check runs, so a finish in the last allowed turn stands and the message stays queued. The three copies of the token-budget check are one local `budget_spent()`. See "Decisions taken while away".
- [x] **SM-85 Backup-load success becomes a recovery session** (b): `penguin/system/session_manager.py:393-416` caches the restored session, then a failing primary rewrite is caught as a backup-load failure and a new recovery session is returned; the next load of the same id returns the cached one. Correction: give the rewrite its own error handling.
  - State: (2026-11-15) fixed: in `SessionManager.load_session`, the rewrite of the primary file from a good backup has its own `OSError` handling, which logs a warning and still returns the restored session. Before, a failed rewrite fell through to a new recovery session while the restored one stayed cached under the same id. The primary stays broken until the next save replaces it.
- [x] **SM-86 ACP close has no closing state** (c): `penguin/integrations/acp/server.py:585-604` awaits four steps before popping the session; a `session/load` or prompt arriving in between installs or runs a session that the close then removes or closes under it. Correction: mark closing (or pop first) before the first await.
  - State: (2026-11-15) fixed: `close_session` marks the session `closing` before its first await, and `Session.busy` (a turn running or queued, or a close in progress) is the one busy test used by prompt, load, delete and the mode and config controls, so nothing starts on or replaces a closing session. The session is removed and its grants closed in a `finally`, and only if the open entry is still the same object. A second close of a closing session is refused.
- [x] **SM-87 ACP load does not re-check busy under the gate** (c): `penguin/integrations/acp/server.py:685-757` checks `task is None` before taking `_process_gate`, then replaces the `Session` object; a prompt queued meanwhile runs on the replaced object (events dropped, cancel ineffective). Correction: re-check under the gate, as `_idle_session` does.
  - State: (2026-11-15) fixed: `_restore_session` re-checks at the point where it installs the new `Session` (after its awaits under the gate) that the open session is the one it checked and is not busy; otherwise it closes the provider it just made and refuses with "Session is busy". It installs the new session before closing the old provider.
- [x] **SM-88 ACP process completions for closed sessions are ignored** (c): `penguin/integrations/acp/processes.py:81-85` returns before recording completion when the root is not open, so `unresolved` never clears (`penguin/integrations/acp/isolated.py:184-190`, `server.py:623-629`): isolated runtimes stay pinned (16 reach the limit) and delete keeps refusing. Correction: record the completion, skip only the update.
  - State: (2026-11-15) fixed: `ProcessTracker` records a completion for a session that was closed while its process ran (no update is sent to the closed session), and the "unresolved" decision is one method, `ProcessTracker.unresolved(root)`, used by `delete_session` and the isolated close. When a closed root's last process ends, the tracker calls the agent's `on_root_resolved` hook; `IsolatedACPAgent` uses it to release that root's runtime (under the allocation lock, only if the root is still closed and idle), so a pinned runtime no longer counts against the limit until a reload.
- [x] **SM-89 ACP `cancelled` outlives its turn** (b): `penguin/integrations/acp/server.py:874,1024,1057` reset it only when the next prompt starts, so background approvals and questions after a cancelled turn are silently denied. Correction: clear it when the turn ends.
  - State: (2026-11-15) fixed: a turn's `finally` in `PenguinACPAgent.prompt` clears `session.cancelled` after denying that turn's pending approvals, so the flag means "this turn is cancelled" only while the turn runs. Before, it stayed set until the next prompt, and approvals and questions from work that outlived a cancelled turn were silently denied. An answer to a permission prompt already in flight still cannot approve its request, which is DENIED by then.
- [ ] **SM-90 Windows stop cannot kill descendants after the shell exits** (on hold 2026-11-15: needs a Windows run to reproduce; this machine is macOS) (b) [inferred]: `penguin/tools/process_runtime.py:548` tree-kills on Windows only while `poll() is None`; POSIX still kills the group (`:580-592`). Correction: tree-kill the retained pid on Windows too. Needs a Windows run to confirm.
  - State: (still on hold, re-read 2026-11-19) the named correction cannot work. Windows never updates a process's parent id, so once the shell and the script it started have both exited, a surviving grandchild's parent id names a dead middle process: neither `taskkill /T` on the retained pid nor the psutil walk in `windows_process_tree.py` (a snapshot from a live root) can reach it. Reaching it needs ownership that outlives the root: a Job Object created at launch (`CreateJobObject` + `AssignProcessToProcessHandle`, terminate the job on stop), with a decision on nested jobs and `CREATE_BREAKAWAY_FROM_JOB` on hosts that already run Penguin inside a job. Needs a Windows machine to develop against, not only CI.
- [x] **SM-91 FAISS deletes and updates leave orphan vectors** (c): `penguin/memory/providers/faiss_provider.py:229-261` removes metadata only or appends a new vector; search drops orphan hits (`:169-182`), and the SM-61 re-index makes one orphan per edit, so a memory that exists stops being found. Correction: an id-mapped index with removal.
  - State: (2026-11-15) fixed: the FAISS provider keeps an id-mapped index (`IndexIDMap2`) with one vector per live memory, recorded as `vector_id` in its metadata. An update removes the memory's vector and adds the new one; a delete removes it; search maps result ids straight to memories instead of scanning positions. An index saved in the earlier positional format (or with orphans) is rebuilt once at initialise by re-encoding each stored memory's content.
- [x] **SM-92 SQLite FTS5 external-content triggers drift** (c) [inferred]: `penguin/memory/providers/sqlite_provider.py:101-133` inserts without `rowid` and deletes with a plain `DELETE`, which FTS5 external-content tables do not support. Correction: the documented `'delete'` command form, then a rebuild.
  - State: (2026-11-15) fixed: the FTS5 triggers use the documented external-content form (insert with `rowid`; remove with the `'delete'` command carrying the old values), so full-text hits resolve to the right memory after an update or delete. A database with the earlier triggers is detected at initialise, its triggers are replaced, and the index is rebuilt once.

### Tier 2

- [x] **SM-93 Memory provider readiness** (b): `penguin/web/routes.py:7708-7825`, `penguin/tools/tool_manager.py:2678-2721`, `penguin/memory/providers/sqlite_provider.py:76-156`; three paths create or initialise the provider and test different fields, so a failed initialise leaves a connection that accepts writes without FTS, and some routes 500 until a search has run.
  - State: (2026-11-15) fixed: the memory store, get and stats routes all take the provider from `ToolManager.ensure_memory_provider` (store and get through `_require_memory_provider`, 503 when memory is unavailable), so they no longer build their own provider or answer 500 until a search has created one. The stats route is declared before `/memory/{memory_id}`, which had matched `stats` as an id, so the stats route was unreachable. A SQLite provider whose initialise fails closes and clears its connection, so it refuses writes instead of storing rows without the full-text index, and a retry does not leak a connection.
- [x] **SM-94 `LEDGER_MAX_EVENTS=0` empties the ledger** (a): `penguin/system/runtime_event_ledger.py:89-92,473-475`; the other three ledger settings treat 0 as "no limit".
  - State: (2026-11-15) fixed: the event-count limit is optional like the size and age limits: `0`, `off`, `none` or `disabled` means no count limit, and `_cleanup_by_count` no longer deletes every row for a limit of 0. The docs table says so. The unused `_env_int` is deleted. See "Decisions taken while away".
- [x] **SM-95 Cross-process session index merge** (c): `penguin/system/session_manager.py:193-221` merges with a process-local lock and never rewrites entries it did not change, so two processes can lose an index entry until restart.
  - State: (2026-11-15) fixed: `SessionManager._save_index` reads, merges and writes the index while holding `interprocess_lock` on `session_index.json.lock` (`flock` on POSIX, `msvcrt.locking` on Windows), so a peer process saving between our read and write is no longer overwritten. The lock file stays next to the index. Left: `session_view.py` mutating `manager.session_index` without the store lock (noted by the reader) is not changed here.
- [x] **SM-96 Audit logger replaced by each isolated runtime** (c): `penguin/tools/tool_manager.py:2452-2476` rebinds the module-global logger in `penguin/security/audit.py:412-450`.
  - State: (2026-11-15) fixed: `get_audit_logger` and `configure_audit_logger` use the runtime's scoped service when a runtime is isolated, so each ACP root keeps its own audit logger and the process-wide one is untouched. The tool manager builds its permission enforcer (and configures the audit logger) once, under its lazy lock, in `_build_permission_enforcer`.
- [x] **SM-97 Request-scoped providers outlive the request** (b): `penguin/tools/providers/client.py:11-21` and `mcp.py:26-38` are context variables that background agents inherit (`penguin/multi/executor.py:179`) after the ACP session that set them closed.
  - State: (2026-11-15) fixed in part: a closed `MCPToolProvider` stays closed (tool calls return `mcp_provider_closed`; schemas, refresh and reconnect do nothing), so a background agent that inherited a closed ACP session's provider no longer reconnects and spawns servers that nothing closes. Checked and left: the context-variable inheritance itself is deliberate ("Bind MCP configuration to one tool manager and inherited request tasks"), so a child keeps using its session's client files and MCP servers while the session is open; after the session closes its client file tools fail with `client_session_closed`, which is correct since the client is gone.
- [x] **SM-98 ACP permission dialog for a resolved request** (c): `penguin/integrations/acp/server.py:1086-1106` shows the dialog if the request exists, even when it was already denied.
  - State: (2026-11-15) fixed: `_request_permission` shows the dialog only while the request is still PENDING; a request denied (by a cancel) or expired between the listener and the dialog task is skipped. Before, it checked only that the request existed.
- [x] **SM-99 ACP response tracking mixes request id spaces** (c): `penguin/integrations/acp/stdio.py:81-118` removes a pending `session/new` entry when the agent's own request reuses the id, so the new session never gets its commands.
  - State: (2026-11-15) fixed: `ProtocolTransport.send` treats a message as the answer to a tracked `session/new` only when it is a response (no `method`), so an agent request (permission, file, terminal) that reuses the id no longer clears the entry and the new session still gets its commands.
- [x] **SM-100 ACP load writes synthesized failures before validation** (b): `penguin/integrations/acp/sessions.py:200-215` records them even when the load is then rejected.
  - State: (2026-11-15) fixed: `SessionRegistry.history` no longer writes; `replay_history` returns the replay and, separately, the "never completed" failures it synthesized, and `_restore_session` records those only after the whole load has succeeded. A refused or failed load leaves the journal unchanged.
- [x] **SM-101 ACP load half-applied when replay fails** (b): `penguin/integrations/acp/server.py:743-786` installs the session and provider before a replay that can raise.
  - State: (2026-11-15) fixed: if any step after installing the session fails (closing the old provider, saving, restoring grants, replay, refresh), `_restore_session` removes the installed session, its replay state and grants, and closes the provider it made, then re-raises. The session is not open after a failed load, including one that was open before it.
- [x] **SM-102 ACP restore never resolves child-scoped records** (b): `penguin/integrations/acp/processes.py:144-165`, `sessions.py:189-199`.
  - State: (2026-11-15) fixed: `ProcessTracker` restores a child's process from either record form (`<child>:process:<pid>` in the root journal, or a native child envelope through `restore_raw`), keyed by the child and remembering its root; `refresh` covers every process whose root is the loaded session; a child known only from history is re-registered (`ChildTracker.adopt`, inactive) so its updates route to the client as before. The replay also closes a native child's unfinished tool calls with a synthesized failure envelope, recorded once the load succeeds.
- [x] **SM-103 ACP per-session maps never pruned** (b): `ChildTracker.children` and `replay_parents`, approval locks and task sets, `QuestionBridge.tasks`, `ProcessTracker.states`.
  - State: (2026-11-15) fixed: approval and question task sets drop their session key when their last task finishes, and `close_session` calls one `_forget_root` that removes the root's finished children (and their replay parents and approval locks) and empty per-session entries; `delete_session` also drops the root's process states. Active children that cannot be cancelled keep their records; process states stay while the session exists, since they decide unresolved background work. `test_cancel_rejects_waiting_form_and_late_answer` now reads the task set with `.get`.
- [x] **SM-104 ACP delete closes before a delete that can fail** (b): `penguin/integrations/acp/server.py:636-649`.
  - State: (2026-11-15) fixed: `delete_session` deletes the conversation before closing the ACP session (both under the process gate, after the busy checks), so a failed delete leaves the session open and usable, matching the error. Journal and assets are removed after the close, as before.

### Tier 3

- [x] **SM-105 Modal credential precheck order** (a): `penguin/core_runtime/model_runtime.py:37-49` accepts a generic `api_key` before the Modal check the adapter needs.
  - State: (2026-11-15) fixed: `provider_credential_available` checks the Modal rule (endpoint plus proxy token id and secret) before the generic `api_key` test, matching what the Modal adapter needs, so a Modal model with only `api_key` gets the missing-credential message instead of a later provider initialisation failure.
- [x] **SM-106 `SessionManager._revisions` never pruned** (b): `penguin/system/session_manager.py:88,906-907`.
  - State: (2026-11-15) fixed: `delete_session` and cache eviction drop the session's revision counter (under the dirty lock), so `_revisions` holds only sessions still in memory or modified since; a later change to an evicted session starts a new count.
- [x] **SM-107 ACP exact-grant policy and mode fields are constant** (a) [security]: `penguin/integrations/acp/grants.py:34-47`; no approval request carries those fields (`penguin/tools/tool_manager.py:2614-2623`).
  - State: (2026-11-15) fixed: `ToolManager._permission_response` copies `agent_mode`, `approval_policy` and `permission_mode` from the permission context into the approval request, so the ACP exact-grant key's policy hash and mode reflect them and a remembered grant stops auto-approving when either changes. See "Decisions taken while away" (older saved grants ask once more).
- [x] **SM-108 Dead modules** (b): `penguin/cognition/`, `penguin/server/ws_server.py` (imports a missing `new_core`), `penguin/memory/providers/milvus_provider.py` (imports a missing module); none has an importer. `penguin/dashboard/` is a standalone Streamlit tool whose ledger path ignores `PENGUIN_RUNTIME_EVENT_LEDGER_PATH`.
  - State: (2026-11-15) fixed in part: deleted `penguin/server/ws_server.py` and `penguin/memory/providers/milvus_provider.py` (neither importable nor imported). The dashboard's `get_event_db_path` uses the server's `default_ledger_path`, so it honours `PENGUIN_RUNTIME_EVENT_LEDGER_PATH` and the configured workspace. Left for Maximus: `penguin/cognition/` (no importers, but an empty `placeholder.md` suggests a planned subsystem).

### Found in manual testing (2026-11-17)

- [x] **SM-109 Runtime event ledger size cleanup empties the ledger** (b): `penguin/system/runtime_event_ledger.py` (`_cleanup_by_size`, `_incremental_vacuum`).
  - State: (fixed, 2026-11-17) `PRAGMA incremental_vacuum` frees one page per result row read, and the ledger never read them, so deleted rows left free pages and the file never shrank. Measured by file size, the ledger stayed over its 256 MB cap for good and every cleanup deleted all but one row: in the field, 13 rows in a 1.56 GB file (380,877 of 381,358 pages free), so reconnect replay had almost nothing. The vacuum now reads its results, and size cleanup reclaims free pages before measuring, so rows are deleted only for retained data.
- [x] **SM-110 VCS watcher polls every directory ever used, forever** (b): `penguin/web/services/system_status.py` (`_vcs_watch_loop`), `penguin/web/sse_events.py`.
  - State: (fixed, 2026-11-17) the watcher ran up to seven `git` commands every 2 s for the server's directory and every directory any session had used (`_opencode_session_directories` only grows), with or without a client; on macOS each spawn also prints a MallocStackLogging line, flooding the log. Each SSE connection now registers its directory while open (`watch_vcs_directory` / `unwatch_vcs_directory`), only watched directories are polled, and an unchanged directory backs off from the base interval up to 10 s, resetting on any change. An idle server runs no git.
- [x] **SM-111 Sessions past the message limit stop answering** (b) [design]: `penguin/system/conversation.py:233-247`, `penguin/system/session_manager.py` (`check_session_boundary`, `create_continuation_session`).
  - Found 2026-11-17 in a 5,002-message TUI session: each prompt loads the original session, adds the message, crosses `PENGUIN_MAX_MESSAGES_PER_SESSION` (5,000), creates a continuation holding only the system prompt and a "Continuing from" note, and builds the request from it, so it goes out with no input (OpenAI 400 `missing_required_parameter`) and the turn ends silently. The next prompt loads the original again and repeats. Needs a decision on what a long session should do.
  - State: (fixed, 2026-11-17, decided by Maximus: carry history over) `create_continuation_session` now returns a continuation that keeps the source session's id and carries the SYSTEM and CONTEXT messages, a transition marker and the most recent history (a tenth of the limit, starting at a user message, with the tool records those messages use). The full history is archived under a new id first (`continued_from` on the live session, `continued_to` and `archived_from` on the archive); if the archive cannot be written the session is left as it is. Clients that address the session by id keep working. The unused `_get_continuation_index` is deleted.
- [x] **SM-112 A denied finish action still ends the task** (c) [security]: `penguin/tools/runtime.py` (scheduler string branch), `penguin/core_runtime/action_execution.py`, `penguin/utils/parser.py` (`capability_denial`), `penguin/security/tool_capabilities.py`.
  - Review finding P2 on PR #164 (2026-11-14). With a tool allowlist that excludes `finish_task` / `finish_response`, the dispatcher returned the denial as JSON text, the scheduler recorded any text as `completed`, and the engine ends a task or response on a completed finish action. `process_response_actions` also decided to stop from the action's name before anything ran.
  - State: (fixed, 2026-11-19) the scheduler records a capability denial as `error` (`is_capability_denial`), which covers ActionXML and native tool calls; the core action paths check `ActionExecutor.capability_denial` first, record an error and do not exit continuation.

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

- (fixed, 2026-11-19) `run_agent_turn` passed `image_path=` but `run_single_turn` accepts only
  `image_paths`, so every call raised `TypeError`. It now passes `image_paths=[image_path]`.
- Test files live in source directories: `penguin/cli/test_tui_*.py`,
  `penguin/utils/test_*.py`, `penguin/local_task/test_manager.py`.
- Two `CommandRegistry` classes: `penguin/cli/commands.py:63` and
  `penguin/cli/command_registry.py:81`.
- (fixed, 2026-11-19) `penguin/security/mcp_isolation.py` accepted `http://127.0.0.1:1@other.host/`
  as local (prefix check, not a parsed hostname). Confirmed; the URL is now parsed and must have
  scheme `http`, host `127.0.0.1`, a port and no user info.
- `penguin/llm/adapters/modal.py:35-50` and `runinfra.py:44-60` copy
  `OpenRouterGateway`'s per-request fields by hand (next to SM-35).
- A root change rebuilds the tool manager's file map synchronously over the
  whole active root (`penguin/tools/tool_manager.py:_refresh_file_map`): 25 s
  for this repository, on the request that changed the root.
- A failed background indexing task leaves `_indexing_task` set, so indexing
  never retries (`penguin/tools/tool_manager.py:2704-2717`, next to SM-60).

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
- SM-09: partly fixed (2026-11-13). `load_session` now tries the backup
  whenever the primary is missing or unusable, not only when loading the
  primary raised.
  - `pytest -q tests/system`: 115 passed, 2 skipped, 3 xfailed; the new
    backup-only test was red before the fix.
  - Other files that load sessions: 170 passed, 12 skipped.
- SM-11: partly fixed (2026-11-13). `handle_issue_comment` ignores comments
  whose author or sender is a bot account (`type == "Bot"` or a `[bot]` login).
  - `pytest -q tests/api/test_github_webhook_self_trigger.py`: 4 passed; the
    three bot cases were red before the fix.
  - `tests/api/test_github_webhook_security.py`: 4 passed.
- SM-19: fixed (2026-11-13). `Task.mark_pending_review` and `Task.approve`
  check the status move first and raise `StateTransitionError` without
  changing anything if it is illegal.
  - `pytest -q tests/test_task_state_machine_contract.py`: 18 passed; 9 red
    before the fix.
  - Every test file mentioning task status, approval or orchestration: 287
    passed, 2 failed. Both failures are baseline:
    `test_cli_surface_audit_regressions` (click) and
    `tests/test_side_door_completion_semantics.py::test_api_complete_task_rejects_non_review_ready_task`,
    which matches text against an `HTTPException` whose string is empty with
    the installed FastAPI.
- SM-18: fixed (2026-11-13). The end marker is queued in `finally`, chunks are
  queued directly, and the producer is awaited so its error reaches the
  consumer. Worse than recorded: every chunk was lost, not only late ones,
  when the provider invoked the callback without yielding.
  - `pytest -q tests/test_engine_llm_stream_sentinel.py`: 2 passed; both red
    before the fix (one by hanging until its 2 s timeout).
  - `tests/test_engine*.py`: 129 passed.
- SM-31: fixed (2026-11-13). `subscribe` stores `weakref.WeakMethod` for bound
  methods, `unsubscribe` compares by equality, and `publish` rebuilds the
  handler list instead of removing from it while iterating. Left open:
  `publish` still holds its lock across handler awaits.
  - `pytest -q tests/test_event_bus_weak_methods.py`: 3 passed; the delivery
    test was red before the fix.
  - Every non-API test file touching the event bus, telemetry, `local_task`
    or run mode: 558 passed, 9 skipped, and the two known baseline failures.
- SM-12: partly fixed (2026-11-13).
  - OpenAI HTTP stream: `LLMProviderError` raised for an error event is no
    longer caught by the malformed-line handler.
    `pytest -q tests/llm/test_openai_http_stream_errors.py`: 2 passed; the
    error-event test was red before the fix.
  - Anthropic stream: a timeout is recorded as a retryable TIMEOUT `LLMError`
    and pending tool calls are cleared.
    `pytest -q tests/llm/test_anthropic_stream_timeout_error.py`: 1 passed;
    red without the fix.
  - `tests/llm` and `tests/test_openai_adapter_streaming.py`: 439 passed.
- SM-03 follow-up (2026-11-13): three cases of
  `tests/integrations/test_bend_permissions.py::test_python_boundary_characterization`
  recorded the old fail-open behaviour and are updated to fail-closed; the
  prototype README says so.
- Known red baseline, Bend lane: 14 tests in
  `tests/integrations/test_bend_permissions.py` fail on `origin/main` too. The
  native `runner` and `scoring` binaries exit with status 2 under Bend 2.0.37
  as installed here. Not investigated.
- Branch check (2026-11-13, 13 commits): every new test plus `tests/system`,
  `tests/llm`, `tests/tools`, `tests/core_runtime` and the touched single
  files: 1423 passed, 22 skipped, 3 xfailed.
  `tests/integrations/test_bend_tool_status.py` and `test_bend_runtime.py`:
  8 passed.
- SM-20: fixed (2026-11-13). `pytest -q tests/test_workflow_orchestrator_failure_paths.py`: 2 passed, both red before the fix; the three existing orchestrator test files: 6 passed.
- SM-29: fixed (2026-11-13). `pytest -q tests/tools/test_code_execution_timeout_state.py`: 2 passed, the busy test red before the fix; `tests/tools`: 230 passed, 20 skipped.
- SM-30: partly fixed (2026-11-13). `pytest -q tests/test_runmode_continuous_termination.py`: 2 passed, both red before the fix (the first by crashing on `MessageCategory.WARNING`); other run-mode tests: 34 passed.
- SM-15: partly fixed (2026-11-13). `pytest -q tests/test_engine_task_finish_contract.py`: 49 passed, including two new unbounded-LENGTH tests; engine, finish and core-runtime suites pass.
- SM-21: partly fixed (2026-11-13). `pytest -q tests/test_orchestration_terminal_signals.py`: 7 passed, 6 red before the fix; `tests/test_orchestration.py` passes.
- SM-43: partly fixed (2026-11-13). `pytest -q tests/test_plugin_action_unregister.py`: 1 passed, red before the fix.
- SM-54: partly fixed (2026-11-13). `pytest -q tests/test_agent_executor_cancel_race.py`: 2 passed, the race test red before the fix.
- SM-47: partly fixed (2026-11-13). `pytest -q tests/test_cli_event_dedup_key.py`: 3 passed, 2 red before the fix.
- SM-56: partly fixed (2026-11-13). `pytest -q tests/tools/test_edit_commit_rollback.py`: 1 passed, red before the fix (file left truncated); editing suites: 95 passed, 1 skipped.
- SM-58: partly fixed (2026-11-13). `pytest -q tests/tools/test_pydoll_cleanup_timer.py`: 2 passed, the restart test red before the fix.
- SM-36: fixed (2026-11-13). `pytest -q tests/api/test_reasoning_variant_restore_target.py`: 2 passed, the first red before the fix (the request copy's settings were written onto the core config); variant tests: 88 passed.
- SM-63: partly done (2026-11-13). Deleted the unread `Engine._interrupted`; engine and core-runtime suites pass.
- Process note (2026-11-13): the SM-47 commit `c08714616` was committed and
  pushed with its new tests failing on an incomplete fixture; `c624eb3b5`
  completed the fixture. Commits are now gated on the item's tests passing.
- Branch check (2026-11-13, 27 commits): the suites listed in the PR
  description: 1623 passed, 23 skipped, 3 xfailed. One of the SM-05 tests
  failed in this combined order until its fixture cleared leftover listeners.
- Items ticked `[x]` whose State line lists what is still open are only
  partly fixed: SM-05, SM-09, SM-11, SM-21, SM-30, SM-43, SM-47, SM-54, SM-56, SM-58,
  SM-63. Not started: every unticked item without an "on hold" note.
- SM-17: partly fixed (2026-11-13). Two new cases in `tests/test_engine_initialization.py` (unexpected error, cancellation) were red before the fix; engine and core-runtime suites: 564 passed.
- SM-72: partly fixed (2026-11-13). `pytest -q tests/test_sidecar_install_atomic.py tests/test_opencode_launcher.py`: 28 passed.
- SM-34: partly fixed (2026-11-13). `pytest -q tests/llm/test_openrouter_call_reference_rewrite.py`: 8 passed, 4 red before the fix; `tests/llm` and `tests/test_openrouter_fixes.py`: 437 passed.
- SM-70: partly fixed (2026-11-13). `pytest -q tests/test_cli_message_dedupe_turns.py`: 2 passed, the later-turn test red before the fix; CLI test files: 144 passed and the known click baseline failure.
- Branch check (2026-11-13, at `0199c737a`): the suites listed in the PR
  description: 1667 passed, 23 skipped, 3 xfailed. 27 items ticked, 49 open.
- SM-12: done (2026-11-13). Shared stream-end rule wired into four adapters; 11 deterministic tests, 5 opt-in Bend tests.
- SM-16: partly fixed (2026-11-13). One owner for session run tracking; busy-forever after a crash and the unbounded abort marker fixed.
- SM-13: partly fixed (2026-11-13). Shared tool-call accumulator in five adapters; Link not yet moved.
- SM-13: done (2026-11-14). Link moved onto the shared accumulator.
- SM-14: done (2026-11-14). The OpenAI fallback no longer re-requests after output.
- SM-32: done (2026-11-14). Guarded lifecycle transitions; RETRYING now written by Link.
- SM-33: done (2026-11-14). One call-outcome rule. Flaky under full-suite load, passes alone 3/3: tests/tools/test_log_inspired_process_faults.py::test_callback_exceptions_do_not_fake_failure_or_leak_child.
- SM-16: run record done (2026-11-14). Cancellation response status on hold for a decision.
- SM-16: decision (2026-11-14) from Maximus: a cancelled chat request keeps returning HTTP 200 with `aborted: true`. Nothing left open on SM-16 apart from the known limits in its State line.
- SM-15: fixed (2026-11-14). `pytest -q tests/test_engine_loop_termination.py`: 14 passed, 10 red before the fix; `PENGUIN_TEST_BEND=1 pytest -q tests/integrations/test_bend_loop_termination.py`: 5 passed (laws, 4096 + 729 sequences against Python, two mutations rejected); engine, core-runtime, A2A, task, agent, web and API suites: 158 files pass apart from the known `test_resolve_request_runtime_uses_runtime_helper` baseline failure.
- SM-22: fixed (2026-11-15). `pytest -q tests/system/test_checkpoint_lifecycle.py`: 7 passed, all 7 red before the fix; `tests/system`, checkpoint, conversation, phase-1, CLI-integration and package-export tests: 29 files, 230 passed.
- SM-24: fixed (2026-11-15). `pytest -q tests/tools/test_process_runtime_races.py`: 6 passed, 5 red before the fix (the sixth guards that children outliving their shell are still killed); 3 runs stable. All 40 test files that use the process runtime or tools: 565 passed.
- SM-25: fixed (2026-11-15). `pytest -q tests/tools/test_process_notice_delivery.py`: 5 passed, 4 red before the fix (the fifth guards that a failed persist is retried). Process, engine and ACP suites: 69 files, 757 passed.
- SM-26: partly fixed (2026-11-15). `pytest -q tests/web/test_chat_request_lifecycle.py`: 3 passed, all 3 red before the fix; every test file using the receipt store, A2A, task cancellation or the app lifespan: 12 files, 186 passed.
- SM-27: fixed (2026-11-15). `pytest -q tests/web/test_chat_stream_websocket.py`: 4 passed, 3 red before the fix (the fourth guards that a message sent mid-reply is answered next); `tests/web`, `tests/api` (without the auth-hardening file that hangs on main) and the web-route files: 61 files, 506 passed.
- SM-28: fixed (2026-11-15). `pytest -q tests/api/test_sse_lag_recovery.py`: 2 passed, both red before the fix; 3 runs stable. Every SSE, ledger and app-lifespan test file: 29 files, 467 passed.
- SM-35: on hold (2026-11-15); see its State.
- SM-37: fixed (2026-11-15). `pytest -q tests/test_model_switch_atomic.py`: 2 passed, the failed-switch test red before the fix; model runtime, facade, provider-resolution and route model tests: 9 files pass apart from the known `test_resolve_request_runtime_uses_runtime_helper` baseline failure.
- SM-38: partly fixed (2026-11-15). `pytest -q tests/test_engine_loop_termination.py`: 18 passed, the 4 new guard-stop cases red before the fix; engine, run-mode, goal and engine-caller test files: 35 files, 385 passed.
- SM-39: fixed (2026-11-15). `pytest -q tests/core_runtime/test_stream_state_lifecycle.py`: 2 passed, both red before the fix; `tests/core_runtime` and every stream-state test file: 65 files, 914 passed after updating the one test that pinned the leak.
- SM-40: fixed (2026-11-15). `pytest -q tests/core_runtime/test_session_goal_claim.py`: 2 passed, both red before the fix; every session-goal test file: 9 files, 200 passed.
- SM-41: fixed (2026-11-15). `pytest -q tests/test_core_runmode_cleanup.py`: 3 passed; the new re-entrancy test hung before the fix (the second start took over the first run). Every RunMode test file: 33 files, 375 passed apart from the two known `test_cli_surface_audit_regressions.py` baseline failures.
- SM-44: fixed (2026-11-15). `pytest -q tests/test_part_event_action_tags.py`: 3 passed, 2 red before the fix (the third guards that a closed action split across chunks stays hidden); every part-event and streaming test file: 34 files, 506 passed.
- SM-46: fixed (2026-11-15). `pytest -q tests/test_cli_stream_state.py`: 2 passed, both red before the fix; CLI test files: 27 files, 169 passed apart from the two known `test_cli_surface_audit_regressions.py` baseline failures.
- SM-48: fixed (2026-11-15). `pytest -q tests/test_opencode_launcher_ownership.py`: 4 passed, 3 red before the fix (the fourth guards that a Penguin server is still recognised); launcher and CLI test files: 28 files, 173 passed apart from the two known `test_cli_surface_audit_regressions.py` baseline failures.
- SM-49: partly fixed (2026-11-15). `pytest -q tests/web/test_provider_oauth_pending.py`: 3 passed, 2 red before the fix (the third guards that waiting for a just-completed flow still succeeds); every OAuth and provider-auth test file: 21 files, 278 passed.
- SM-50: fixed (2026-11-15). `pytest -q tests/llm/test_openai_oauth_record_source.py`: 2 passed, the first red before the fix; every OAuth, provider-credential and OpenAI adapter test file: 24 files, 285 passed.
- SM-52: partly fixed (2026-11-15). `pytest -q tests/test_core_runmode_cleanup.py`: 4 passed, the new WebSocket-slot test red before the fix; RunMode and route test files: 29 files, 350 passed apart from the two known `test_cli_surface_audit_regressions.py` baseline failures.
- SM-53: fixed (2026-11-15). `pytest -q tests/system/test_remove_current_agent.py`: 1 passed, red before the fix; every conversation-manager and sub-agent test file: 45 files, 751 passed.
- SM-55: fixed (2026-11-15). `pytest -q tests/system/test_context_window_total_budget.py`: 1 passed, red before the fix (1005 tokens kept in a 1000-token window); every context-window test file: 43 files, 561 passed apart from the known `test_resolve_request_runtime_uses_runtime_helper` baseline failure, after updating the one test that relied on the old behaviour.
- SM-57: fixed (2026-11-15). `pytest -q tests/test_execution_root_sync.py`: 3 passed, all 3 red before the fix; config, runtime-config and tool-manager test files: 13 files, 168 passed.
- SM-59: fixed (2026-11-15). `pytest -q tests/test_browser_harness_cleanup_lock.py`: 1 passed, red before the fix (cleanup ran while a helper call held the lock); `tests/test_browser_harness_tools.py`: 32 passed. No browser is started; the harness modules are fakes.
- SM-60: fixed (2026-11-15). `pytest -q tests/tools/test_lazy_tool_loading.py`: 1 passed, red before the fix (two executors built); every test file that uses the tool manager: 72 files, 950 passed apart from the known baseline failures.
- SM-61: fixed (2026-11-15). `pytest -q tests/memory/test_incremental_index_reindex.py`: 2 passed, both red before the fix; every memory test file: 3 files, 48 passed.
- SM-62: fixed (2026-11-15). `pytest -q tests/test_git_pr_flow_restore.py`: 1 passed, red before the fix (real temporary repository, push fails for lack of a remote); git and workflow-orchestrator test files: 6 run, 11 passed; three workflow files are deselected by the repo's pytest configuration, as before.
- SM-64: fixed (2026-11-15). `pytest -q tests/core_runtime/test_legacy_get_response.py`: 2 passed, both red before the fix; response-generation and core-process test files: 27 files, 373 passed after updating the one test that pinned the saved apology.
- SM-65: fixed (2026-11-15). `pytest -q tests/test_local_task_status_transitions.py`: 2 passed, both red before the fix; parser and local_task test files: 30 files, 404 passed; `test_tool_timeout_structured_errors` failed once under load and passes alone (known flaky).
- SM-66: fixed (2026-11-15). `pytest -q tests/test_actionxml_process_runtime.py`: 2 passed; on the old code the run hung in `process_enter`; parser and process test files: 42 files, 478 passed.
- SM-67: on hold (2026-11-15); see its State.
- SM-68: on hold (2026-11-15); see its State.
- SM-69: partly fixed (2026-11-15). `pytest -q tests/test_cli_exit_command.py`: 1 passed, red on the old `cli.py` (prompted twice); CLI test files: 86 passed apart from the two known `test_cli_surface_audit_regressions.py` baseline failures.
- SM-71: partly fixed (2026-11-15). `pytest -q tests/test_env_file_precedence.py`: 1 passed, red before the fix (the project file replaced the shell value); config test files: 21 files, 147 passed apart from the two known `test_cli_surface_audit_regressions.py` baseline failures.
- SM-73: fixed (2026-11-15). `pytest -q tests/test_setup_wizard.py`: 12 passed after replacing the marker assertion with the real completion check.
- SM-74: partly fixed (2026-11-15). `pytest -q tests/test_question_history_bound.py`: 1 passed, red before the fix; question-manager test files: 29 passed.
- SM-75: fixed (2026-11-15). Six new tests, each red before its fix: `tests/test_runtime_job_terminal_status.py`, `tests/system/test_penguin_state_resume.py`, `tests/test_project_dag_freshness.py`, `tests/api/test_vcs_emit_tasks_kept.py`, `tests/web/test_events_ws_disconnect.py`, `tests/llm/test_connection_pool_close_race.py`. Related test files: 41 files, all passed (marker-deselected files excluded).
- SM-55 Bend lane (2026-11-15). `bend prototypes/bend_context_trim/PROOF.bend`: all 5 laws check by evaluation over 338 sessions. `PENGUIN_TEST_BEND=1 pytest -q tests/integrations/test_bend_context_trim.py`: 2 passed; the table test fails on the pre-SM-55 `context_window.py`, and a model with the pre-SM-55 rule fails `trimmed_session_fits_unless_at_minimums`.
- SM-76: done (2026-11-15). Second sweep by three read-only readers; 32 new items, SM-77 to SM-108. Nothing executed.
- SM-77: fixed (2026-11-15). `pytest -q tests/test_runtime_security_mode.py`: 3 passed, all 3 red before the fix; permission, tool-manager, ACP permission and startup test files: 23 files, all passed.
- SM-78: fixed (2026-11-15). `pytest -q tests/api/test_runtime_event_ids_across_restart.py`: 2 passed; the first was red before the fix (sequence 1 after a restart), the second fails on the old `app.py`. Every runtime-event, ledger, SSE and event-service test file in one process: 205 passed, in both file orders.
- SM-79: fixed (2026-11-15). `pytest -q tests/multi/test_mailbox_continuation.py`: 1 passed, red before the fix (the steering never got a turn); engine, run-mode, multi-agent and message-bus test files: 29 files, all passed.
- SM-80: fixed (2026-11-15). `pytest -q tests/system/test_session_eviction_unsaved.py`: 1 passed, red before the fix (the unsaved session was evicted); session, conversation, checkpoint and ACP session test files: 36 files, all passed.
- SM-81: fixed (2026-11-15). `pytest -q tests/api/test_sse_ledger_flush_protocol.py`: 3 passed; the two flush tests were red before the fix (replay skipped two events; a failing ledger was retried 27 times for 30 events) and the handler test fails on a sync handler. Every runtime-event, ledger, SSE and event-service test file in one process: 208 passed; chat stream, web server and CLI integration files pass.
- SM-82: fixed (2026-11-15). `pytest -q tests/llm/test_ollama_stream_contract.py`: 3 passed, all 3 red before the fix (TypeError on the first chunk, UnboundLocalError on an empty stream, finish reason UNKNOWN for a stop); provider contract, client and stream-end test files: 8 files, all passed.
- SM-83: fixed (2026-11-15). `pytest -q tests/multi/test_one_executor_per_core.py`: 3 passed, all 3 red before the fix (separate executors); every executor, sub-agent, parser, ACP isolation and CLI test file: 52 files, all passed apart from the known `test_resolve_request_runtime_uses_runtime_helper` baseline failure.
- SM-84: fixed (2026-11-15). `pytest -q tests/test_engine_steering_last_turn.py`: 2 passed, both red before the fix (`iterations_exceeded`, `budget_limited`); `test_late_steering_does_not_extend_token_budget` updated to expect `pending_review`; engine, run-mode, session-goal and completion test files: 21 files, all passed.
- SM-85: fixed (2026-11-15). `pytest -q tests/system/test_session_backup_restore.py`: 1 passed, red before the fix (a `recovery_` session was returned); session storage, recovery, dirty-tracking, eviction, autoload and session route test files: 10 files, all passed.
- SM-88: fixed (2026-11-15). `pytest -q tests/integrations/test_acp_closed_session_processes.py`: 2 passed, both red before the fix (completion not recorded; runtime kept); every ACP test file: 24 files, all passed.
- SM-89: fixed (2026-11-15). `pytest -q tests/integrations/test_acp_cancel_scope.py`: 1 passed, red before the fix (the approval was denied without asking); every ACP test file: 25 files, all passed.
- SM-86: fixed (2026-11-15), with SM-87 in one commit. `pytest -q tests/integrations/test_acp_close_load_races.py`: 2 passed, both red before the fix (a load and a prompt went through during a close; a load queued behind a prompt replaced its session); every ACP test file: 26 files, all passed.
- SM-87: fixed (2026-11-15), in the SM-86 commit; see SM-86.
- SM-92: fixed (2026-11-15). `pytest -q tests/memory/test_sqlite_fts_sync.py`: 2 passed, both red on the old provider (a search for updated text returned a different memory; an old database stayed wrong); memory and diagnostics test files: 7 files, all passed (one is fully marker-deselected).
- SM-91: fixed (2026-11-15). `pytest -q tests/memory/test_faiss_vector_lifecycle.py`: 3 passed; the first two were red before the fix (a memory updated back and forth was not found; the index kept every old vector) and the third fails on the old provider (a positional index with an orphan was kept). Memory test files: 9 passed. Uses a deterministic fake encoder, not a downloaded model.
- SM-94: fixed (2026-11-15). `pytest -q tests/api/test_runtime_event_ledger_limits.py`: 4 passed; `0` was red before the fix (the ledger was emptied). Every runtime-event, ledger, SSE and event-service test file in one process passes.
- SM-98: fixed (2026-11-15). `pytest -q tests/integrations/test_acp_resolved_approval.py`: 1 passed, red before the fix (the dialog was shown for a denied request); every ACP test file: 27 files, all passed.
- SM-99: fixed (2026-11-15). `pytest -q tests/integrations/test_acp_response_tracking.py`: 1 passed, red before the fix (the session was never announced); every ACP test file: 28 files, all passed.
- SM-103: fixed (2026-11-15). `pytest -q tests/integrations/test_acp_session_maps_pruned.py`: 2 passed, both red before the fix (an empty task set and a finished child stayed); every ACP test file: 29 files, all passed after updating one assertion that indexed the removed key.
- SM-104: fixed (2026-11-15). `pytest -q tests/integrations/test_acp_delete_failure.py`: 1 passed, red before the fix (the session was gone after a failed delete); every ACP test file: 30 files, all passed.
- SM-100: fixed (2026-11-15), with SM-101 in one commit. `pytest -q tests/integrations/test_acp_load_atomic.py`: 2 passed, both red before the fix (a refused load added a failure record; a failed replay left the session open); every ACP test file: 31 files, all passed.
- SM-101: fixed (2026-11-15), in the SM-100 commit; see SM-100.
- SM-96: fixed (2026-11-15). `pytest -q tests/test_audit_logger_isolation.py`: 1 passed, red before the fix (the second runtime replaced the first's logger); permission, tool-manager and every ACP test file: 50 files, all passed.
- SM-97: partly fixed (2026-11-15). `pytest -q tests/test_mcp_provider_closed.py`: 1 passed, red before the fix (the closed provider called its manager); MCP and ACP MCP, session and isolation test files: 9 files, all passed.
- SM-93: fixed (2026-11-15). `pytest -q tests/memory/test_memory_provider_readiness.py`: 2 passed, both red before the fix (the failed provider kept its connection; reading a memory gave 500); memory, tool-manager and memory-route test files pass.
- SM-108: partly fixed (2026-11-15). `pytest -q tests/test_dashboard_ledger_path.py`: 1 passed, red before the fix (the dashboard used the workspace path); `import penguin` and the memory provider factory still import.
- SM-105: fixed (2026-11-15). `pytest -q tests/test_modal_credential_precheck.py`: 1 passed, red before the fix; model runtime, Modal adapter, provider resolution and model switch test files pass apart from the known `test_resolve_request_runtime_uses_runtime_helper` baseline failure.
- SM-106: fixed (2026-11-15). `pytest -q tests/system/test_session_revisions_pruned.py`: 1 passed, red before the fix; session storage, dirty-tracking, eviction, backup and ACP session test files: 8 files, all passed.
- SM-107: fixed (2026-11-15). `pytest -q tests/test_approval_context_binding.py`: 1 passed, red before the fix (the fields were missing); ACP grant, permission-wire, child-approval and approval lifecycle test files: 9 files, all passed.
- SM-95: fixed (2026-11-15). `pytest -q tests/system/test_session_index_cross_process.py`: 1 passed, red before the fix (a peer process's stale write dropped our new session); session storage, view, route and ACP session test files: 15 files, all passed. The Windows lock path is exercised by the ACP Windows CI jobs, not locally.
- SM-102: fixed (2026-11-15). `pytest -q tests/integrations/test_acp_child_restore.py`: 3 passed, all 3 red before the fix (a child's process stayed unresolved after reconnect, in native and non-native mode; a native child's open tool call stayed in progress); every ACP test file: 32 files, all passed.
- SM-52: completed (2026-11-17). `pytest -q tests/test_runmode_ws_session_scope.py`: 1 passed, red before the fix (another session's message reached the RunMode socket); RunMode, streaming, execution-context and run-mode route test files: 24 files, no failures.

- SM-109: fixed (2026-11-17). `pytest -q tests/api/test_runtime_event_ledger_vacuum.py`: 2 passed, both red before the fix (free pages kept; a bloated file lost its events); ledger and SSE test files: 32 passed.
- SM-110: fixed (2026-11-17). `pytest -q tests/api/test_vcs_watcher_bounds.py`: 3 passed, all red before the fix; two watcher tests in `test_vcs_status_service.py` updated to register a watching client; every SSE, status and VCS test file: 143 passed.
- SM-111: fixed (2026-11-17). `pytest -q tests/system/test_session_rollover_history.py`: 2 passed, both red before the fix; session, conversation, checkpoint, multi-agent, engine and ACP session test files: 55 files, no failures. Replayed on a copy of the 5,003-message session: 488 live messages under the same id, request has input.
- SM-112: fixed (2026-11-19). `pytest -q tests/test_denied_control_actions.py`: 6 passed (denied and allowed, ActionXML `finish_task` / `finish_response` and native `finish_task`); the three denied cases red before the fix. Two new cases in `tests/core_runtime/test_action_execution.py`. Tool, engine, permission and action test files: 443 passed.
- SM-23: fixed (2026-11-19). `pytest -q tests/system/test_session_rollover_history.py`: 6 passed; the long-tool-run case over four alignments, two red before the fix.
- SM-10: fixed (2026-11-19). `pytest -q tests/core_runtime/test_process_retry_after_turn_start.py`: 2 passed; the after-turn-start case red before the fix (turn ran three times). `tests/core_runtime`: 449 passed.
- SM-30 (rest): fixed (2026-11-19). `pytest -q tests/test_runmode_continuous_termination.py`: 8 passed; the six new cases hung before the fix (the loop never yielded, so the test timeout could not fire). RunMode test files: 67 passed.
- SM-58 (failed start), MCP loopback check, `run_agent_turn`: fixed (2026-11-19). `pytest -q tests/tools/test_pydoll_failed_start.py tests/test_mcp_isolation.py tests/test_engine_loop_termination.py`; the new cases red before each fix.
- SM-05 (ownership): fixed (2026-11-19). `pytest -q tests/api/test_permission_reply_session_ownership.py`: 7 passed, 6 red before the fix (the seventh is the over-HTTP check). Approval and route test files: 419 passed, plus the 2 known CLI audit failures. TUI `tsgo --noEmit` passes.
