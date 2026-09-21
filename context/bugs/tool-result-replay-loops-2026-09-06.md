# Tool-heavy sessions stall in repetitive inspection/result loops

Reported: September 6, 2026
Priority: High — blocks engineering work and creates uncertainty around mutations.

## Complaint and impact

A Link authorization-boundary task spent approximately 2–3 hours in repeated check-ins and resume attempts without reaching implementation.

The user observed: “It seems more likely that you're running in loops due to issues with tools in the Penguin harness.”

The initial disk-space blocker was resolved, but productive execution did not resume. The assistant reported that the isolated worktree and dependencies were ready, but no new regression tests, fixes, commit, or follow-up PR were completed.

## Observed behavior

- Numerous assistant turns contained only identifiers such as `msg_session_20260904_190400_fa7b582b_1788665009990_00`, rather than useful output.
- The assistant reported issuing an oversized batch of overlapping inspections, including identical status commands and source reads.
- Across network interruptions and subsequent user resume messages, the conversation repeatedly returned to inspections without implementation progress.
- Repeated requests to resume did not recover productive execution.
- The assistant repeatedly announced tests and fixes as the next step without reaching them.
- Earlier PR merge operations also appeared stuck. Later assistant responses claimed delayed results confirmed successful merges, making it unclear to the user whether retrying was safe.

The uncertainty after a potentially successful mutation is particularly concerning: retrying could repeat an operation that already completed.

## Established facts versus hypotheses

The visible non-substantive responses and failure to make progress are established by the conversation. Duplicate tool execution or a harness replay defect is not yet established.

The transcript alone cannot distinguish queued results, duplicate delivery, repeated context injection, incorrect call association, rendering issues, or model-generated repetition. Claims about delayed tool results and redundant batches must be checked against raw execution logs rather than accepted solely from assistant summaries.

The assistant also contributed by continuing inspections instead of stopping and reporting the failure promptly. Investigation must separate model orchestration mistakes from harness defects.

## Relevant context

- Penguin repository: `/Users/maximusputnam/code/penguin/penguin`
- Link worktree: `/Users/maximusputnam/Code/Link/Link-session-auth`
- Branch: `fix/session-authorization-boundaries`
- Last assistant-reported state: clean worktree, dependencies installed; verify before resuming.
- Visible message identifiers reference `session_20260904_190400_fa7b582b`; correlate with raw session logs.
- The user reported network interruptions during resume attempts.
- The assistant initially reported that writing this complaint was permission-denied. The user then explicitly authorized writing it through Python/shell. Treat permission issues separately from the suspected replay problem.

## Investigation

- [ ] Correlate provider response IDs, tool-call IDs, batch child IDs, execution IDs, persisted event sequence numbers, and displayed messages.
- [ ] Determine whether repetition happens during execution, persistence, context injection, rendering, or model generation.
- [ ] Trace pending batches across interruption, reconnect, and resume; confirm old results cannot be attached to the wrong invocation.
- [ ] Inspect any loop detector's definition of result identity: identical output must not be confused with identical execution.
- [ ] Check successful commands with empty stdout specifically.
- [ ] Determine why message identifiers or empty continuations reach the user instead of a useful status or actionable error.
- [ ] Verify whether new user messages cancel, interrupt, or merely queue behind pending work, and make that behavior explicit.

## Regression checks

- [ ] A tool invocation executes once and retains its result association across interruption and reconnect.
- [ ] Duplicate result delivery cannot repeatedly append context or trigger another execution.
- [ ] Different successful commands with empty stdout are not falsely classified as replay of one invocation.
- [ ] Each interrupted batch child exposes a clear queued, running, completed, failed, cancelled, or unknown state.
- [ ] Reproduce delayed results and a user message arriving before batch completion using small read-only commands.
- [ ] Use a synthetic counter mutation to verify that result redelivery cannot execute a mutation twice.
- [ ] Broken continuation state produces an actionable diagnostic and recoverable state, not repeated identifiers, empty messages, or generic resumes.
- [ ] Recovery can inspect a mutation's outcome without automatically repeating it.

## Safety constraints

Do not automatically retry mutations because their results were delayed. Do not impose arbitrary task-duration or iteration limits as a workaround, or infer execution failure merely from observation loss.

Use lifecycle identifiers and metadata for diagnostics, not secret values or environment dumps. Preserve working trees and pending-operation state.

## Temporary workaround

Stop tool-heavy work in the affected session and continue through a fresh session/tool connection with an explicit handoff. This is a proposed workaround, not evidence that the root cause is fixed.
