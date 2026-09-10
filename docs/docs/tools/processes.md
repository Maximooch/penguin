# Managed shell processes

`process_start` launches a command and returns a `process_id`. Penguin captures
stdout and stderr continuously, even when no client polls the process.

`process_poll` waits up to `wait_ms` (default 5000, maximum 60000) for new output
or completion. Omit `since_sequence` for incremental reads by the current agent.
Pass `since_sequence: 0` to replay retained output. Pass a prior `next_sequence`
to resume an explicit read: the cursor is exclusive and starts at zero. This
corrects the previous off-by-one meaning of `next_sequence`.

Tool-call completion (`status`) is separate from child lifecycle
(`process_status`: `running`, `draining`, or `exited`). A quiet wait returns
`no_new_output: true`; it does not terminate the child. The reasoning loop allows
quiet process waits for up to 120 seconds without new output before returning a
still-running notice. Ordinary iteration limits also remain in force.

`process_write_stdin` sends input. `process_stop` interrupts, terminates, or kills
the owned process group, escalating when necessary. Processes use pipes, not a
PTY. The local implementation requires POSIX shell and pipe support.

Memory is bounded to 256,000 output characters and 10,000 chunks per process.
Large reads report `truncated` and `history_lost`. The `log_path` points to captured
output under `${PENGUIN_WORKSPACE:-~/penguin_workspace}/process-logs`; logs remain
after cleanup. Each log retains up to 32 million characters, after which
`log_truncated` is true. Logs may contain command output that is sensitive;
files are created with private permissions. Explicit replay reads are independent
of automatic consumer cursors. A zero-size read does not advance a cursor.

An exited shell can leave descendants holding its pipes. Penguin drains final
output for a bounded grace period and reports `streams_closed: false` if those
pipes did not reach EOF. Stop/cleanup still target the owned process group.

## Short and long commands share one runtime

`execute_command` now uses the same managed processes as `process_start`:

```json
{"command": "du -x -d1 ~", "yield_time_ms": 1000, "timeout_seconds": 600}
```

The tool waits up to `yield_time_ms` (default 1000, maximum 60000) and returns
bounded output. If the command is still running, use the returned `process_id`
with `process_poll`. The yield deadline does not terminate the command.
`timeout_seconds` is an independent termination deadline which remains active
in the background. If omitted, `PENGUIN_TOOL_TIMEOUT` supplies the deadline when
set; otherwise there is no execution deadline. Timeout and cancellation preserve
partial output and the log path. A nonzero exit is an error result.

The command schema also accepts `cwd`, `env`, and `max_chars`. The direct Python
`ToolManager.execute_command(command, cwd)` compatibility method returns text
for a short successful command and JSON metadata for a yielded or failed command.
The tool API always returns structured metadata. Automatic process polls enforce
a minimum five-second wait when quiet, even if `wait_ms: 0` is requested. Explicit
cursor reads may use zero wait for UI/log inspection.

Process access is scoped to the launching session and agent. Model-supplied
arguments cannot override that ownership. Provider call IDs identify retried
launches and reads; cached read responses are replayed without advancing the
cursor twice. Retry responses are retained for the most recent 128 calls per
process. Completed processes whose output was consumed can be evicted when the
128-process registry is full; their logs remain available. Handles and retry
state do not survive server restart.

## Completion notices

A command that yields, or one launched with `process_start`, queues one completion
notice for its owner. The UI event stream receives scoped `tool.process.output`
snapshots and `notification.process.completed` events, plus a completion toast.
Output snapshots contain a bounded tail; the log is the retained output source.
At the owner's next reasoning step, Penguin adds a lifecycle notice to its
conversation. A final poll acknowledges the notice without consuming another
reader's output. Output text is never inserted as a system instruction.

Completion does not start an overlapping model turn or automatically restart an
idle conversation. The UI can notify while idle; the model sees its notice on
its next step. This keeps completion delivery inside the existing session turn
ownership rules. A server restart does not restore in-memory notices.

Cancelling an active `execute_command` wait terminates its process group.
Cancelling a `process_poll` ends the wait and leaves the background process
available. Use `process_stop` to terminate that process. Web shutdown and normal
interpreter exit clean up owned processes. Force-killing the interpreter cannot
run cleanup hooks.
