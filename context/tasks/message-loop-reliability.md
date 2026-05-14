# Message Loop Reliability

Goal: make provider/network failures impossible to confuse with successful
assistant turns, using Codex's `response.completed`-driven loop as the reference.

## File-by-file Checklist

- `penguin/llm/contracts.py`
  - [x] Add typed `LLMCallStatus` and `LLMCallResult` for one provider attempt.
  - [ ] Extend lifecycle metadata with terminal-event and retry-attempt grouping.

- `penguin/llm/api_client.py`
  - [x] Populate `LLMCallResult` for successful, retryable, fatal, and cancelled
        provider attempts while preserving legacy string responses.
  - [ ] Stop formatting provider failures as assistant text on Engine-owned paths.

- `penguin/llm/runtime.py`
  - [x] Drive retry/failure decisions from `LLMCallResult`, not text prefixes.
  - [x] Raise structured provider errors when retryable/fatal failures remain.
  - [x] Log native tool-call batch size, names, argument chars, duration, and
        result statuses.
  - [ ] Add provider-specific retry budgets/backoff and reconnect notices.

- `penguin/llm/adapters/openai.py`
  - [x] Treat Codex/OpenAI stream transport closes before `response.completed` as
        retryable disconnects, including incomplete chunked reads.
  - [x] Record terminal-event presence explicitly in lifecycle/provider data.
  - [x] Log Codex SSE event breakdown: first event/text/tool-args timing,
        largest event gaps, text deltas, function-call argument chars, and event
        counts.

- `penguin/engine.py`
  - [x] Return `provider_recoverable_error` / `provider_error` instead of
        `completed` when provider attempts fail.
  - [x] Log provider-attempt waterfall timing, context snapshot, tool-schema
        count, stream finalization timing, tool phase timing, and per-iteration
        loop summaries.
  - [ ] Split transient stream chunks from committed assistant messages.
  - [x] Abort or discard uncommitted stream buffers on failed attempts.

- `penguin/system/context_window.py`
  - [x] Log context-window snapshots with total/adjusted tokens, category
        totals, over-budget flags, and largest message previews.
  - [x] Log trim results with removed message count and tokens freed.

- `penguin/tools/runtime.py`
  - [x] Log normalized tool execution start/done/error with request/session,
        source, argument chars, duration, output bytes/lines, truncation, and
        artifact metadata.

- `penguin/tools/tool_manager.py`
  - [x] Log canonical edit parse diagnostics for `write_file`, `patch_file`,
        and `patch_files`.
  - [x] Log canonical edit execution timing, timeout, success/failure, touched
        files, and backup paths.

- `penguin/tools/editing/service.py`
  - [x] Log edit apply start/done/error with before/after file shape, payload
        shape, deltas, touched files, and backup paths.
  - [x] Emit suspicious zero-change warnings for successful line insertions that
        do not change file line count.

- `penguin/core.py`
  - [x] Add a scoped stream-abort helper so failed attempts do not finalize partial
        assistant text as dialog.
  - [ ] Emit explicit recoverable provider-failure events for TUI/web clients.

- `penguin/web/routes.py`
  - [x] Include process `status`, `recoverable`, and structured `error` in chat
        responses when present.
  - [ ] Ensure web/SSE clients render recoverable provider failures distinctly
        from normal assistant messages.

- `tests/test_engine_initialization.py`
  - [x] Cover retryable provider failures through typed attempt results.
  - [x] Cover partial streamed output followed by provider failure as non-success.

- `tests/test_tool_runtime_ir.py`
  - [x] Cover normalized tool scheduler timing diagnostics.

- `tests/tools/test_edit_service.py`
  - [x] Cover file edit before/after shape diagnostics.

- `tests/llm/test_openai_oauth_subscription_flow.py`
  - [x] Cover Codex stream breakdown lifecycle data for function-call argument
        deltas.

- `tests/llm/test_provider_contract_matrix.py`
  - [ ] Add incomplete-stream fixtures for completed/failed/cancelled/interrupted
        provider-native replay.

- `tests/api/`
  - [ ] Add route contract tests for recoverable provider failure payloads.

- `tests/system/`
  - [ ] Add long-run fault-injection loop tests: intermittent disconnects must not
        persist partial assistant text as completed turns and must release next turn.

## Deferred Follow-up

- File edit reliability is the next major track and is now detailed as Phase 7.5
  in `context/tasks/tool-call-runtime-architecture.md`: replace the current edit
  surface with exact `old_string`/`new_string` edits plus a Codex-style
  `apply_patch` tool, remove in-repo `.bak` creation, preflight all edits, and
  retire unsafe line-coordinate edit paths.
