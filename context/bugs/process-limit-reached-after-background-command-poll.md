# Process limit reached after background command poll (September 23, 2026)

During work in `/Users/maximusputnam/Code/Link/Link-lk-task-management`, `functions.execute_command` started a PostgreSQL migration with `yield_time_ms: 1000` and returned a `proc_*` process ID. A subsequent `functions.process` poll returned success (`migrations applied successfully`). After that, attempts to run a focused Vitest command returned `process_limit_reached; run cleanup` without starting the command. This happened repeatedly, including for a trivial `echo ping` invocation. The runtime tool name surfaced as `functions.process` even though the exposed developer tool schema lists `execute_command` and `process_poll`/`process_stop`, not `functions.process`. Earlier calls also sometimes printed `[Empty response from model]` before the tool result.

Impact: cannot run the pending database regression suite; no claim of passing database tests for this resumed session. The last successful command was the migration. No evidence of changed files or data loss from the error. The command target database was a freshly created disposable `lk_task_management_*` database on the local PostgreSQL instance; no live Link task operations were attempted.

Likely recovery investigation: enumerate outstanding processes in the harness and whether exited `proc_*` handles count toward the limit; check cleanup semantics and whether tool alias translation from `execute_command` to `functions.process` contributes. Root cause not established. Do not conflate this with the previously recorded repetitive-git-inspection loop.

## Repeat on September 29, 2026

During PR #479 Phase 3/4 work in `Link-cicd-phase3-preview`, after several `execute_command` calls completed and their retained results were read, another `execute_command` attempt to inspect GitHub checks returned `process_limit_reached; run cleanup` instead of a process. `functions.code_execution` running a bounded Python `subprocess.run` with the same read-only `gh run view` command succeeded (exit 0). No source edit or host mutation was involved in the failed command. This supports a command-harness process accounting issue but does not establish its cause. No process was intentionally left running by this check; review retained process handles before attempting cleanup.


## Local fix and verification (September 29, 2026)

A regression using ProcessTools reproduced the error with a two-record runtime:
start a background command, wait for exit, read it with an explicit cursor, and
repeat across sessions. Explicit final polls did not set completion_observed;
notification acknowledgment only updated ProcessTools._observed, not the runtime
flag. The previous patch changed the syntax of the eviction scan without changing
its eligibility condition, and its added test also passed against the original
scan. It did not address exhaustion by completed, unobserved records.

The runtime now treats explicit final reads as observation and can retire unread
exited records when needed, preferring observed completions. It saves owner-scoped
retry receipts before eviction, retains logs, and reports process_result_expired
with a log path for expired reads. A retired launch ID cannot execute again.
Active/draining commands stay protected; genuine capacity failures report counts
and recovery guidance. An archive write failure leaves the handle intact.

Verification: 72 tests passed across test_process_tools, test_process_runtime,
test_process_waiting, and test_process_poll_empty_loop; targeted Ruff checks passed.
This confirms the reproduced lifecycle defects, not the exact historical mix of
128 records in the live backend. Restart the backend to load the changed code;
no running backend was restarted during this work.
