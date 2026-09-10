# Bug: process_poll Returns Empty Output and Agent Enters Empty-Tool-Turn Loops

## Status
Fixed — continuous capture, reusable cursors, bounded polling, and live-process
wait policy implemented in stage 1; command unification, cancellation, timeout,
and scoped completion delivery implemented in stage 2.

## Summary
During a long disk-usage investigation (2026-08-19), `process_start` + `process_poll`
repeatedly returned empty stdout for processes that were still running and had already
produced output. The agent then emitted successive tool-only turns with no assistant
text, and the runtime's stale-loop guard forcibly stopped the turn with:

> Stopping because empty tool-only turns repeated the same tool result identity...
> Repeated tool result: process status=completed output=e3b0c44298fc

(`e3b0c44298fc` is the SHA-256 of the empty string, i.e. every poll returned an empty
result body.) The only reliable workaround was to abandon `process_start`/`process_poll`
entirely and use `execute_command` with shell backgrounding (`(cmd &)`) writing to
`/tmp` files, then `cat` those files.

## Observed Behavior
- `process_start` launched a command and returned a `process_id`.
- `process_poll` on that id returned `status=running` with **empty stdout**, even after
  the process had printed output (verified by reading the `/tmp` file it was writing).
- Polling again yielded the same empty result identity, so the agent kept re-polling.
- The harness stopped the turn with the stale-loop message above instead of surfacing
  the actual process output.
- `execute_command` also has a hard ~60s timeout: long-running `du` / `find` commands
  (e.g. `du -x -d1 ~`) were killed with `{"error": "timeout"}`. There was no way to
  raise the timeout or opt into a background runner from the tool call itself.

## Expected Behavior
- `process_poll` should return buffered stdout/stderr since the last sequence number,
  and should distinguish "no new output yet" from "process finished with empty output".
- Tool-only turns should not loop; if a poll returns no new data, the runtime should
  either wait properly or return a structured "no change" result that the model can
  consume without re-issuing identical calls.
- `execute_command` should support an explicit timeout/background mode so long scans
  don't have to be hand-rolled with `&` + polling `/tmp` files.

## Suspected Area
- `process_poll` buffering / sequence-number handling: output produced before the first
  poll may be dropped, or the `since_sequence` default (0) may not actually replay
  buffered output.
- The stale-loop guard keying on the *result body hash*: an empty body for a still-running
  process is treated as a terminal loop condition rather than a transient "no new data".
- `execute_command` timeout handling returns a generic `timeout` error with no way to
  configure it.

## Reproduction Notes
Reliable trigger: start any command that prints immediately then keeps running, e.g.

```
process_start: sh -c 'echo hello; sleep 30'
process_poll  (first/only poll)  -> status=running, empty stdout
```

The `echo hello` output was never delivered in this session. The same pattern occurred
with `du` scans and a Python script that printed a header then streamed results.

## Impact
High for long-running, exploration-heavy workflows (exactly the disk/storage and repo
survey tasks this agent is used for). It forced a manual workaround (background `&` +
`/tmp` files) and produced several empty assistant turns before the guard stopped it.

## Suggested Investigation
1. Add a tiny integration test: `process_start` a command that prints a line then sleeps;
   poll once and assert the line is returned.
2. Verify `since_sequence` semantics — does sequence 0 mean "from start" or "after 0"?
3. Make the stale-loop guard ignore still-running processes, or include process state
   (running vs exited) in the loop key so empty-but-running polls don't trip it.
4. Add a `timeout` (or `background`) parameter to `execute_command` so long commands
   don't require manual `&` backgrounding.

## Notes
Workaround that worked reliably this session:

```
execute_command: cd ~ && (du -x -d1 ~ > /tmp/home.txt 2>/dev/null &)
execute_command: cat /tmp/home.txt
```

Do not confuse this with the older `read-tool-empty-loop.md` bug; that one was about
`read_file`-heavy turns. This one is specific to `process_start`/`process_poll` and
long-running shell commands.

## Investigation (2026-09-05)

Scope: current working tree at `0d341d29a`, local subprocesses and offline runtime
tests. The original August session's raw calls/results were not supplied, so the
findings below distinguish reproduced defects from unverified incident details.
This investigation adds tests and documentation only.

### Confirmed: returned cursor skips output

`ManagedProcess.next_sequence` starts at 1 and identifies the next event to be
allocated. `_collect_output()` returns that value, but selects events with
`event.sequence > since_sequence`. `_snapshot()` also returns the next unused
value in the start result.

Consequently:

| Step | Returned cursor / event | Result |
| --- | --- | --- |
| Start a process blocked on stdin | `next_sequence=1` | No output yet |
| Release it to print `first` | Event 1 | Bytes become available |
| Poll with the start cursor, `since_sequence=1` | Returns cursor 2 | Event 1 excluded; empty output |
| Poll with `since_sequence=0` | Returns cursor 2 | `first` is present |
| Release a second output chunk, then poll with cursor 2 | Event 2 | Second chunk also excluded |

This is cursor-based omission, not deletion from the buffer. Tests synchronize
with pipe readiness and use stdin gates, so startup scheduling cannot explain
the failures. Existing process tests predominantly poll from sequence 0 and do
not exercise incremental cursor reuse.

Relevant code: `penguin/tools/process_runtime.py`, `ManagedProcess.append_output`,
`ProcessRuntime._collect_output`, and `ProcessRuntime._snapshot`.

### Confirmed: three unchanged live-process polls trip the guard

A process waiting on `read done` produces empty output and remains running.
Passing three polls to `LoopState.check_empty_tool_only()` with no assistant text
returns `repeated_empty_tool_only_iterations` on the third call.

Top-level `status=completed` means the poll tool call completed;
`process_status=running` means the child is still alive. The guard does not
interpret the latter. Polling is nonblocking and has no wait/yield parameter,
so nothing at this layer prevents immediate repeated model/tool iterations.

Adding the process state to the identity alone would not solve this: three
unchanged running polls would still have the same identity. Nor is making each
poll hash unique a solution; that would merely hide an unbounded busy loop.

Relevant code: `penguin/engine.py:LoopState.check_empty_tool_only`,
`penguin/tools/runtime.py:tool_loop_signature`, and
`penguin/tools/process_runtime.py:ProcessRuntime.poll`.

### Not reproduced: loss from a default poll or empty-string result hash

With `printf 'hello\n'; read line`, a first poll after stdout becomes readable
returns `[stdout] hello` while the process is running. Repeating a default poll
replays that buffered output. An immediate poll can legitimately arrive before
the child writes anything; the tool does not wait for output.

Even when `output` is empty, `_snapshot()` sets a nonempty `result` containing
the process id, state, and return code. The serial scheduler preserves that text
and process metadata; its output hash is not `e3b0c44298fc…`. A contract test
covers this path. The reported hash therefore remains unexplained by this
current-code reproduction. It does not, by itself, prove stdout was never
captured. Raw original tool arguments/results and the running revision would
be needed to attribute that specific incident to a wrapper or older code path.

Also, output in a redirected `/tmp` file does not establish that the child wrote
the same bytes to captured stdout; the original command matters.

### Confirmed by code inspection: command timeout API gap

`ToolManager.execute_command()` passes a timeout of 60 seconds by default to
`subprocess.run`. `PENGUIN_TOOL_TIMEOUT` can override it for the server process;
it is not an immutable limit. However, the tool schema exposes only `command`,
and dispatch forwards no per-call timeout or background option. The timeout
response includes `error`, `tool`, and `timeout_seconds`; partial output from
`TimeoutExpired` is discarded. This is separate from the polling defects.

### Recommended implementation follow-up

1. Define a reusable cursor contract. With the documented exclusive
   `since_sequence`, return the last captured sequence (initially 0), with an
   explicit compatibility decision for the existing `next_sequence` field.
   Verify start-to-first-poll and poll-to-poll reuse before removing the xfails.
2. Add bounded waiting for output or exit, and teach the guard to distinguish
   legitimate process waiting from a stale terminal result. Retain a bounded
   no-progress policy; do not exempt running processes indefinitely. Verify
   the assembled engine with a fake provider and a process that eventually
   produces output/exits, plus a process that never progresses.
3. Expose per-call command timeout and consider the existing process runtime
   for background execution, consistent with Phase 9/10 of
   `context/tasks/tool-call-runtime-architecture.md`.

### Executable evidence

`tests/tools/test_process_poll_empty_loop.py` contains two passing controls and
three strict expected failures (two cursor cases and one guard case). Strict
xfails keep known defects explicit without marking them fixed; `--runxfail`
turns them into ordinary failing assertions.

```sh
uv run --no-sync pytest -q tests/tools/test_process_poll_empty_loop.py --runxfail
uv run --no-sync pytest -q tests/tools/test_process_poll_empty_loop.py tests/tools/test_process_runtime.py tests/test_engine_responses_tool_calls.py
uv run --no-sync ruff check tests/tools/test_process_poll_empty_loop.py
```

The focused suites completed with **44 passed, 3 xfailed**, with existing
Pydantic deprecation warnings. No live provider or server was needed. Child
processes in the new reproductions are cleaned up by a fixture.

## Stage 1 implementation

The diagnosis above is historical. Both cursor cases and the live-process guard
reproduction now pass without xfails. Additional contracts cover independent
consumers, retry replay, log retention beyond pipe capacity, quiet waits,
process-group cancellation, and inherited output descriptors.

## Stage 2 implementation

`execute_command` now delegates to the process runtime. Yield and execution
timeout are separate; partial output survives timeout. Native call IDs support
retry replay, and process access is scoped by session and agent. Completion
events notify the UI and queue one lifecycle notice for the owning conversation
without creating a competing model turn. See `docs/docs/tools/processes.md`
for API semantics, retention limits, and shutdown behavior.
