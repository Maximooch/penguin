# Repetitive Git inspection / tool-orchestration loop

Recorded: September 23, 2026
Status: observed; root cause unconfirmed
Scope: Penguin agent execution and tool orchestration, not an established Git defect

## Summary

While asked to implement Link CLI task/project management in a separate worktree,
Penguin repeatedly issued successful inspection commands without progressing to
code changes. The user interrupted: “seems like you're looping in git commands?
is it a problem with the tool system?”

The visible transcript establishes an execution failure: redundant tool dispatch,
improper parallel batching, and failure to turn sufficient inspection into a
concrete implementation step. It does **not** establish whether the model,
provider adapter, tool-result handling, session replay, or a combination caused
that behavior. The assistant's attribution to its own orchestration was an
acknowledgment of responsibility, not a verified runtime diagnosis.

## Requested work and actual progress

The user requested:

- Implement `context/todo/lk-task-project-management.md` in Link.
- Use an isolated worktree, commit as needed, and open a PR.
- Keep the implementation narrow and avoid overlap with related open PRs.

Confirmed progress before interruption:

- Worktree: `/Users/maximusputnam/Code/Link/Link-lk-task-management`.
- Branch: `penguin/lk-task-management`.
- Copied the implementation document into the worktree.
- Inspected PM read authorization, existing mutation services, middleware,
  test configuration, and relevant PR listings/file lists.
- No implementation changes, commits, or PR were produced.

The task document remained an untracked file. Successful inspection output was
repeatedly available; there was no demonstrated need to re-establish the working
directory or Git status each time.

## Observed sequence

1. An assistant parallel-tool wrapper contained a large batch of calls, including
   repeated `pwd; git status --short` commands and repeated reads of the same PM
   source/documentation.
2. That same batch mixed independent inspection with dependent/mutating steps:
   `git fetch`, writing a temporary PR-list file, reading that file, creating a
   worktree, copying the task document, and inspecting the new worktree.
3. Execution results arrived as separate tool messages. Some commands initially
   returned `status=running`, a process ID, and a retained log path; subsequent
   system notes reported their completion.
4. Numerous distinct process IDs returned the same successful result: the
   expected worktree directory and the untracked task document.
5. No patch or meaningful test run followed. The user noticed and interrupted.
6. The assistant acknowledged the loop, reported the limited actual progress,
   and proposed a read-authorization foundation slice. That proposal was not an
   implemented fix and would not itself deliver the requested CLI writes.
7. The user requested this incident report instead of further implementation.

Some large outputs were truncated with retained log paths. Some inspection
commands returned nonzero because a searched path did not exist or a `grep`
found no match. Neither observation explains the repeated successful Git calls.

## Representative evidence

Repeated command:

```sh
pwd; git status --short
```

Repeated result:

```text
/Users/maximusputnam/Code/Link/Link-lk-task-management
?? context/todo/lk-task-project-management.md
```

Examples of distinct completed process IDs with this result:

- `proc_de92e7acd8b088cbc6da3ae4`
- `proc_4c308ef3a0dc9d67cc899ca3`
- `proc_3036f91fcd6ecc6a2fe4d53d`
- `proc_1444868e0cc51b888eaa3c51`
- `proc_ba7fc7b20655a5a96712dfd8`
- `proc_1e199b7c30b32f6a660046ad`

Representative retained logs from this session:

- `/Users/maximusputnam/penguin_workspace/process-logs/process-a6l6o0mn.log`
- `/Users/maximusputnam/penguin_workspace/process-logs/process-ajyukao_.log`
- `/Users/maximusputnam/penguin_workspace/process-logs/process-2bzaab3o.log`
- `/Users/maximusputnam/penguin_workspace/process-logs/process-rwtk1uei.log`

These references identify local evidence, not durable attachments. Retain the
original conversation/tool event stream if investigating after logs rotate.
The visible history also contains `[Empty response from model]` markers and
delayed tool results around earlier work; a causal connection is unproven.

## Expected versus actual behavior

Expected:

- Inspect repository instructions and current state once.
- Sequence prerequisite operations; confirm worktree creation before using it.
- Parallelize only independent read-only inspection.
- Use results to select a scoped change, edit, then run targeted tests.
- Poll an already-running process when its result is needed instead of issuing
  redundant commands to recover context.
- Explain a specific blocker if execution cannot advance.

Actual:

- Many commands provided no new information and did not reduce uncertainty.
- Parallel dispatch included ordering dependencies and mutations.
- Execution activity looked like progress but yielded no implementation.
- The user had to interrupt to expose the stalled workflow.

## Impact

- Wasted tool calls, context, user attention, and elapsed time.
- Delayed the requested implementation and PR.
- Made asynchronous results harder to associate with the current decision.
- Introduced avoidable ordering hazards: reads could race worktree creation or
  temporary-file writes. No resulting data corruption was demonstrated.
- Reduced trust in progress reporting and in the agent's ability to stop
  unproductive inspection.

There is no evidence here of lost user changes, unauthorized commits, a Git
failure, or an actual cross-workspace data exploit.

## Investigation plan

Separate model-generated repetition from runtime duplication before fixing it.

1. Preserve the raw provider response, normalized assistant messages, native tool
   call IDs, wrapper child calls, dispatch IDs, process IDs, and completion events
   for the incident. Redact credentials and unrelated sensitive output.
2. Determine whether all duplicate commands were already present in one model
   response. The visible wrapper suggests this occurred, but compare raw events
   before excluding transcript assembly or replay effects.
3. Check whether any single tool-call ID was dispatched more than once. Distinct
   process IDs alone cannot distinguish intentional repeated calls from duplicate
   dispatch of one logical call.
4. Verify each child result was delivered exactly once and associated with the
   correct call, including `running` results and later completion notifications.
5. Inspect continuation scheduling: did one batch result or process completion
   trigger multiple concurrent model continuations? Were old pending calls replayed?
6. Check context truncation/category handling for lost recent results or task
   intent. Do not assume it happened solely because outputs were long.
7. Compare adjacent reports in `context/bugs`, especially
   `process-poll-empty-loop.md`, `read-tool-empty-loop.md`, and `looping-error.md`.
   Similar symptoms are leads, not proof of one shared cause.

## Candidate fixes, contingent on evidence

- If dispatch replay is confirmed, enforce exactly-once dispatch per logical
  tool-call identity and preserve result adjacency through retries/resumption.
- If continuation races are confirmed, serialize ownership of the active turn
  while still allowing independent background processes to finish.
- If repetition originates in model output, surface redundant unchanged reads
  and missing prerequisites before executing a large batch; require a concrete
  reason to repeat them rather than silently running an entire redundant batch.
- Use ordered execution for dependent/mutating operations and reserve parallel
  batches for independent reads. Do not equate a shell command's success with
  progress on the user's objective.
- Preserve a compact factual state: established worktree, inspected paths,
  pending process IDs, unresolved question, and next edit/test. Avoid regenerating
  it through repeated Git checks.

Any repetition detection should be advisory or evidence-based: legitimate polls,
changed workspaces, and intentionally repeated regression tests must remain
possible. Do not add arbitrary turn/time/tool-call budgets that silently terminate
valid long-running work.

## Regression and acceptance criteria

Use deterministic fake-provider, dispatcher-contract, and fault-injection tests
before live-provider smoke tests, following `context/tasks/testing-pyramid.md`.

- [ ] Replay one logical tool call after a simulated provider retry; prove it is
  not executed twice, while distinct intentional calls remain valid.
- [ ] Feed a batch with delayed/out-of-order process results; prove correct
  association and no duplicate active-turn continuation.
- [ ] Simulate a running command followed by a completion notification; retain
  its result without reissuing the original command to recover state.
- [ ] Exercise repeated identical successful reads with no intervening change;
  verify any redundancy signal does not fabricate progress or stop valid work.
- [ ] Verify ordered prerequisites: create worktree before inspecting/editing it,
  write PR-list output before reading it, and do not run these in parallel.
- [ ] Test truncated tool output and retained logs without losing the latest
  confirmed task state or repeatedly fetching the same irrelevant output.
- [ ] Preserve user interruption/cancellation and accurately report partial work.
- [ ] A controlled end-to-end coding scenario advances from inspection to a real
  patch and targeted test, or reports a specific reproducible blocker.

## Current disposition

Documented only. Root cause has not been diagnosed and no runtime fix has been
implemented. Link CLI implementation remains unfinished; this report must not be
used as completion evidence for that task.
