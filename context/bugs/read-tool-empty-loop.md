# Bug: Read Tool Can Trigger Empty Assistant Loops

## Status
Open

## Summary
During MCP implementation work on 2026-05-01, repeated `read_file` / read-heavy tool usage appeared to correlate with assistant turns returning `[Empty response from model]` instead of normal tool-call/result continuation. The issue looked like a runtime/tool-loop handling bug, not a filesystem permission failure.

## Observed Behavior
- Assistant emitted short preambles and attempted read/exploration tool calls.
- Runtime returned `[Empty response from model]` for multiple turns.
- Later `patch_file` worked successfully, confirming writes were not globally blocked.
- A unified diff failed only because of stale context; line insert succeeded immediately afterward.

## Expected Behavior
Read tools should return a tool result or a structured error. The assistant loop should not advance into empty model responses without exposing the failed tool call/result state.

## Suspected Area
Likely one of:
- native tool-call adjacency / transcript replay handling after read results
- read result truncation or serialization path
- provider adapter handling for tool-only turns
- engine loop termination behavior when the model emits no content after a tool result

## Reproduction Notes
Not yet deterministic. The observed pattern happened during a read-heavy repo survey using multiple `read_file` and shell read commands in sequence.

## Impact
Medium-high for coding workflows. Exploration is foundational; empty loops make the agent appear stuck and can hide whether tools actually ran.

## Suggested Investigation
1. Add logging around read tool dispatch, tool-result insertion, and the next model request payload.
2. Capture whether the next assistant message has tool calls, text, or neither.
3. Add a regression test for read-heavy multi-tool sequences followed by normal continuation.
4. Verify tool-result adjacency rules for OpenAI/Codex/native tool-call adapters.

## Notes
Do not confuse this with permission failure. A subsequent `patch_file` succeeded in the same session.
