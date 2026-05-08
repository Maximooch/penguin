# Browser Tool Timeout Not Applied

## Summary

During manual browser-harness testing on 2026-05-07, the agent repeatedly called
`browser_open_tab` with an explicit timeout argument (for example `timeout=15` or
`timeout=20`), but the runtime behavior suggested the timeout was not reliably
constraining the browser operation or the higher-level tool loop.

This is separate from the now-fixed opaque tool-result issue. After native tool
results were enriched with model-visible page metadata, the browser workflow made
progress, but the timeout behavior remains suspicious and should be investigated.

## Observed Behavior

Manual web-server run:

```bash
HOST=127.0.0.1 PORT=8080 DEBUG=true uv run penguin-web
```

Prompt:

```text
using your browser tools, go to this url, take a screenshot, then describe to me the image:
https://500px.com/photo/1123067335/the-battle-by-tom-kruissink
```

Earlier bad loop included repeated calls similar to:

```text
browser_open_tab {url=https://500px.com/photo/1123067335/the-battle-by-tom-kruissink, wait=true, timeout=20}
browser_open_tab {url=https://500px.com/photo/1123067335/the-battle-by-tom-kruissink, wait=true, timeout=20}
browser_open_tab {url=https://500px.com/photo/1123067335/the-battle-by-tom-kruissink, wait=true, timeout=15}
```

The agent choosing custom timeouts was also a bad strategy; it should have opened
once, inspected page state, then captured a screenshot instead of repeatedly
retrying navigation.

## Suspected Causes

Potential root causes to verify:

1. `browser_open_tab` schema accepts `timeout`, but the argument may not be
   propagated through every execution path consistently.
2. browser-harness `wait_for_load(timeout=...)` may not enforce total wall-clock
   timeout for all page states / SPA loads.
3. Tool-loop timeout and browser helper timeout are different layers; one may
   expire while the other keeps retrying or vice versa.
4. The model may be using timeout changes as a retry strategy because previous
   tool outputs did not give enough state to proceed.
5. Web server request/task cancellation may not interrupt an in-flight browser
   helper call cleanly.

## Why This Matters

Browser tools must not hang a Penguin web request or encourage repeated tab
creation. Browser operations need predictable wall-clock behavior and should
return actionable partial state on timeout.

## Suggested Fixes

- Add a unit test that verifies `browser_open_tab(..., timeout=N)` passes `N` to
  `helpers.wait_for_load(timeout=N)`.
- Add an integration/fake-helper test where `wait_for_load` raises a timeout and
  confirm Penguin returns a structured tool error with page info if available.
- Consider a separate `operation_timeout` wrapper around the full tool execution,
  not just browser-harness wait helpers.
- Add prompt/tool guidance: do not vary timeout and retry open-tab; inspect
  `browser_page_info` or capture a screenshot after the first open attempt.
- Log actual requested timeout and elapsed time in `browser_open_tab` diagnostics.

## Acceptance Criteria

- `browser_open_tab` timeout propagation is covered by tests.
- Timeout failures return structured output containing:
  - requested timeout
  - elapsed time
  - current URL/title if available
  - next recommended step
- Aborting a web request does not leave the engine in a stuck in-flight browser
  operation when the browser helper is blocked.
