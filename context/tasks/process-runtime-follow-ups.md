# Process runtime: review scope and follow-up PRs

PR #98 fixes output capture, cursor reuse, bounded waiting, resumable execution,
and process lifecycle delivery. Its review follow-up also fixes two regressions:

- Both launch tools receive ToolManager's resolved execution root, including
  when request context has a missing, null, or invalid directory. An explicit
  tool `cwd` override remains supported.
- Natural nonzero exits have `status: error` and `error: command_failed` in
  immediate results, resumed polls, and completion events. The shared runtime
  determines the outcome, with timeout/capture errors retaining their causes.

These are required correctness fixes within the original PR. They do not
require a permission-policy redesign. Existing permission checks remain in
place before dispatch; session/agent ownership checks remain in the service.

## Separate PR: permission contracts for process lifecycles

This is proposed follow-up work, not a vulnerability established by this review.
Define and test the permission contract for a process that outlives a tool call:

- How start approval applies to subsequent stdin writes and stop requests.
- What happens when a session changes mode or permissions while a process runs.
- Consistent policy for explicit `cwd`, resolved execution roots, and retained
  log access across command and process tools.
- Scope and expiry of approvals, including delegation and ownership changes.

Keep policy decisions in the permission subsystem and shared dispatcher. Do not
add a parallel permission implementation to ProcessRuntime or weaken existing
checks to make lifecycle operations work. The acceptance gate should use fake
process/approval contracts covering allow, deny, approval-required, mode changes,
and cross-session requests.

## Separate PR: restore goal continuation contracts

The base commit `a2a4f7ba9e18b8c4aa50ea7b7dd8464244fd57be` already fails these
four tests in `tests/test_engine_task_finish_contract.py`:

- `test_unbounded_task_continues_once_from_persisted_length_partial`
- `test_unbounded_response_continues_from_persisted_length_partial`
- `test_length_continuation_respects_explicit_iteration_limit`
- `test_length_continuation_checks_explicit_stop_before_next_provider_call`

Both the base and reviewed PR produce the same failure signatures in Python
3.10/Pydantic 1 and Python 3.12/Pydantic 2 CI. A local detached-base comparison
also produced **4 failed, 28 passed** on both base and the review-fix worktree.
Fix continuation, iteration-budget, and explicit-stop behavior in the goal/
reasoning-loop workstream rather than combining it with process polling.

## Separate PR: restore the TUI goal typecheck

Both CI runs report TS2345 at `session-family.ts:66` and `:67`, where
`string | undefined` is passed to a string parameter. The entire `penguin-tui/`
tree and CI workflow are unchanged by PR #98. Fix the narrowing in the TUI
session-family workstream and rerun the pinned Bun typecheck and goal tests.

## CI evidence

- [Base CI run 34287849367](https://github.com/Maximooch/penguin/actions/runs/34287849367)
- [Reviewed PR CI run 34453786439](https://github.com/Maximooch/penguin/actions/runs/34453786439)

This establishes that the reported failures predate the process PR. It does not
make the checks green or waive branch-protection requirements. Keep the failures
visible and link the follow-up fixes when available.
