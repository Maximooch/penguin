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
