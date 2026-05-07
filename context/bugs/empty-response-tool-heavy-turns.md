# Empty Assistant Response After Tool-Heavy Turns

## Summary

During browser-harness Phase 3 implementation, the assistant repeatedly returned an empty final/assistant response after several tool-heavy turns. The issue appeared when a turn combined multiple large file reads, greps, diffs, and test outputs. It was not tied to a specific tool like `read_file`; it correlated with high-volume/noisy tool output and multi-tool batching.

Observed symptom in transcript:

- User asked to resume Phase 3.
- Assistant emitted normal commentary, invoked tools, then produced `[Empty response from model]` as the assistant final/continuation several times.
- User correctly flagged: "this is the third time there's an empty response, what's going on? I'm going to assume it's related to the read file tool?"
- Switching to smaller patches/results and avoiding large combined tool outputs stabilized the session.

## Environment / Context

- Branch: `feature/browser-harness`
- Work area: Penguin browser-harness integration, Phase 3
- Files commonly involved:
  - `penguin/tools/browser_harness_tools.py`
  - `penguin/tools/tool_manager.py`
  - `penguin/utils/parser.py`
  - `tests/test_browser_harness_tools.py`
  - `context/tasks/browser.md`
- Runtime date observed in session: 2026-05-07
- Model/provider path in session: OpenAI/Codex-style tool-using runtime

## Reproduction Pattern

The problem happened after turns like:

1. Assistant reads several large file slices and greps broad patterns.
2. Assistant invokes multiple tools in one turn, sometimes via `multi_tool_use.parallel`:
   - `read_file` with large/truncated files
   - `execute_command` with `sed` ranges and test outputs
   - `grep_search` over files/conversation
   - `code_execution` for deterministic script edits
3. Tool results include:
   - long snippets from `tool_manager.py` (~6,466 lines total file; truncated but still noisy)
   - grep results polluted by prior conversation/tool outputs
   - pytest failures/warnings
   - diff/stat output
4. Next assistant message sometimes becomes empty:
   - no summary
   - no tool call
   - displayed as `[Empty response from model]`

A concrete local sequence around the issue:

- `grep_search` for browser harness tool names returned many results from current files plus earlier tool-output text in conversation history.
- `execute_command` printed mixed sections from `tool_manager.py`, including unrelated nearby code.
- Assistant tried to continue and received `[Empty response from model]`.
- After reducing output volume and using more targeted `sed`, `grep`, and small `code_execution` patches, the session recovered.

## Important Observation

This did **not** appear to be caused by `read_file` alone.

Likely contributors:

- High output volume from multiple tools in one turn.
- Grep searching conversation history and files, causing recursive/noisy matches from previous tool output.
- Large snippets of Python files with duplicated/irrelevant context.
- Possibly context-window pressure or malformed/overlarge assistant planning state after tool results.
- The model/runtime may fail to produce a continuation instead of surfacing a structured error.

## User Impact

High annoyance and loss of trust during implementation:

- User saw repeated empty assistant responses.
- User had to repeatedly say "resume".
- The assistant did not automatically diagnose or recover until directly challenged.
- This makes tool-heavy coding workflows feel flaky, especially during large refactors.

## Expected Behavior

If the model/runtime cannot continue after tool results, Penguin should do one of:

1. Return a structured error message explaining why generation failed.
2. Automatically retry with compressed/summarized tool output.
3. Ask the model to continue with a reduced context/tool-output summary.
4. At minimum emit a non-empty recovery message such as:
   - "Tool output was too large/noisy; retrying with targeted reads."

Empty assistant messages should never be silently surfaced to the user as the main response.

## Suspected Root Causes

### 1. Tool Result Volume / Context Pressure

Large tool results may push the conversation into a bad context state. Even when individual tool outputs are truncated, several parallel calls can create enough noise to degrade or break the next model turn.

### 2. Recursive Grep Noise

`grep_search` appears to search both files and conversation history by default. When searching for strings that appeared in previous tool outputs, it can return prior diagnostic text rather than source truth. That recursively pollutes context.

Potential fix:

- For code investigation, default `grep_search(search_files=true)` should maybe not search conversation history unless explicitly requested.
- Or expose clearer controls and make the assistant default to `search_files=true` with conversation off for source-code queries.

### 3. No Guardrail For Empty Model Response

The runtime appears to accept/emit an empty assistant continuation. There should be a guardrail:

- Detect empty assistant content with no tool calls.
- Retry once with a compact system note:
  - "Previous model response was empty after tool output. Continue with a concise next action."
- If retry fails, surface structured diagnostic.

### 4. Parallel Tool Output Aggregation

`multi_tool_use.parallel` can aggregate several large outputs into one result burst. This is efficient but risky for context pressure.

Potential fixes:

- Apply per-call and aggregate output caps.
- Summarize large outputs before injecting into the next model turn.
- Warn or auto-disable parallel batching when expected outputs are large.

## Workaround Used

The session stabilized after:

- Stopping broad `read_file`/grep combinations.
- Using focused `sed -n` ranges.
- Using small `code_execution` script edits instead of huge patch diffs.
- Running focused pytest commands with limited output.
- Avoiding broad `grep_search` over conversation history.
- Responding with a human-visible diagnosis before continuing.

## Suggested Developer Fixes

### A. Add Empty-Response Recovery

In the engine/API client response path:

- If assistant response has:
  - empty text/content
  - no native tool calls
  - no ActionXML/tool calls
- Then retry once with a compact recovery instruction.
- If retry still empty, return a structured error with diagnostic ID.

Pseudo behavior:

```python
if response_is_empty(response):
    compact_recent_tool_results()
    retry_response = model.complete(
        messages + [{"role": "system", "content": "Previous response was empty. Continue with the next concrete step, or explain the blocker."}]
    )
    if response_is_empty(retry_response):
        return "Generation failed: model returned empty response after tool results. Try narrower tool calls."
```

### B. Cap Aggregate Tool Output Per Turn

Independent of per-tool truncation, enforce an aggregate cap for all tool results in a single assistant cycle. If exceeded:

- preserve full raw output in a file/artifact/log
- inject a summarized version into conversation
- include a path/reference to raw output

### C. Make `grep_search` Safer For Code Search

Add or use a flag to prevent conversation-history matches during source-code search. Recommended default for code tasks:

```json
{
  "search_files": true,
  "search_conversation": false
}
```

Current behavior makes it too easy to match previous tool-result text instead of actual files.

### D. Add Tool Output Quality Metadata

Tool results should include metadata such as:

- `truncated: true/false`
- `raw_output_path` when output is large
- `line_count`
- `byte_count`
- `source`: `files` vs `conversation` for grep results

This would help both the model and the developer understand what happened.

### E. Improve Assistant Self-Recovery Policy

Prompt/runtime should require:

- If an assistant notices repeated empty-response recovery or tool-output instability, it should explicitly tell the user and reduce tool-output volume.
- It should not keep repeating the same broad tool calls.

## Acceptance Test Ideas

1. Synthetic large-output test:
   - Tool returns 100k+ chars split across several results.
   - Model should not emit empty final response.
   - Runtime should summarize or return structured recovery.

2. Recursive grep test:
   - Put a search term only in conversation history and not in files.
   - Run code-search style grep.
   - Verify results clearly label conversation vs file source, or can exclude conversation.

3. Empty-response retry test:
   - Mock model returns empty message first, valid message second.
   - Engine retries once and surfaces the valid second response.

4. Empty-response hard-fail test:
   - Mock model returns empty twice.
   - User receives structured diagnostic, not blank output.

## Severity

Medium-high for coding UX.

It does not corrupt files by itself, but it interrupts flow, confuses the user, and can cause repeated/resume loops. In long-running autonomous tasks it could be worse because an empty response may stall progress without a clear failure mode.

## Related Notes

The user explicitly asked for this bug to be documented after repeated empty responses during Phase 3 browser-harness work.

The practical workaround is to keep tool calls narrower, avoid broad conversation grep, and prefer compact targeted file reads/commands until runtime guardrails exist.
