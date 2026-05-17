# browser_* Regression: Imgur Page Opens but Verification Tools Are Unreliable

## Summary

`browser_*` tooling appears regressed compared with the Chrome DevTools MCP path. On the same Imgur URL, Chrome MCP produced deterministic navigation, title/URL evaluation, image metadata, and screenshot capture. The `browser_*` path opened the page and captured screenshots, but `browser_wait` timed out and `browser_js` reported success without returning evaluated values.

This makes the browser harness hard to trust for page verification: it can claim actions succeeded while withholding the data needed to validate state.

## Environment

- Date observed: 2026-05-08
- Workspace: `/Users/maximusputnam/Code/Penguin/penguin`
- Target URL: `https://imgur.com/a/tn8MIFb`
- Page title reported by browser harness: `Imgur: The magic of the Internet`
- Working comparison path: `chrome-devtools-mcp@latest` via Penguin MCP provider configured in `~/.config/penguin/config.yml`

## Expected Behavior

Using `browser_*` tools should support a reliable workflow:

1. `browser_open_tab` navigates to a URL.
2. `browser_wait` reliably waits for load/network/page readiness or reports a useful failure.
3. `browser_page_info` returns current URL/title.
4. `browser_js` returns the evaluated JavaScript result, not only an acknowledgement.
5. `browser_harness_screenshot` captures the rendered page for visual inspection.

## Actual Behavior

Observed during the Imgur test:

- `browser_open_tab` opened `https://imgur.com/a/tn8MIFb` and returned title `Imgur: The magic of the Internet`.
- `browser_wait` timed out despite the page having enough rendered content for screenshot capture.
- `browser_page_info` returned URL/title successfully.
- `browser_harness_screenshot` created screenshots under `.tmp/browser-tools-imgur/`.
- `browser_js` returned only `JavaScript evaluated` with no actual expression result for multiple expressions, including:
  - `document.title`
  - `location.href`
  - `document.body && document.body.innerText.slice(0, 500)`
  - `document.images.length`
  - image source extraction via `Array.from(document.images)`

Because `browser_js` does not surface values, the agent cannot verify DOM state through the tool even when evaluation ostensibly succeeds.

## Evidence

### Chrome MCP Control Test Passed

A separate test using Penguin's MCP provider and Chrome DevTools MCP succeeded against the same URL:

```json
{
  "status": "ok",
  "title": "\"Imgur: The magic of the Internet\"",
  "url": "\"https://imgur.com/a/tn8MIFb\"",
  "screenshot": ".tmp/chrome-mcp-imgur/imgur-tn8MIFb.png",
  "bytes": 2736904
}
```

It also extracted rendered image metadata, including the main Imgur asset:

```text
https://i.imgur.com/pe7X6N3_d.webp?maxwidth=760&fidelity=grand
```

### browser_* Test Was Inconclusive / Degraded

Representative browser harness observations:

```text
browser_open_tab:
url: https://imgur.com/a/tn8MIFb
title: Imgur: The magic of the Internet
loaded: False
```

```text
browser_wait:
Wait timed out
```

```text
browser_page_info:
url: https://imgur.com/a/tn8MIFb
title: Imgur: The magic of the Internet
```

```text
browser_js:
JavaScript evaluated
```

The last response is the core regression signal: the expression apparently runs, but no return value is exposed.

## Reproduction Steps

1. Open the Imgur album with browser harness:

```python
browser_open_tab({
    "url": "https://imgur.com/a/tn8MIFb",
    "wait": true,
    "timeout": 20
})
```

2. Wait for page load:

```python
browser_wait({
    "mode": "load",
    "timeout": 20
})
```

3. Inspect page info:

```python
browser_page_info()
```

4. Evaluate simple JavaScript:

```python
browser_js({
    "expression": "document.title",
    "target_id": ""
})
```

5. Evaluate richer DOM state:

```python
browser_js({
    "expression": "JSON.stringify({title: document.title, href: location.href, imageCount: document.images.length})",
    "target_id": ""
})
```

## Suspected Regression Area

Likely candidates:

- `browser_js` wrapper drops the CDP/runtime evaluation result and returns only a generic success message.
- Browser harness result normalization may be discarding `result.value`, `result.description`, or serialized JSON payloads.
- `browser_wait(mode="load")` may be waiting on an event/state that is inappropriate for SPAs or pages with long-lived requests such as Imgur.
- `browser_open_tab(wait=true)` reports `loaded: False` while the page is still usable, suggesting load-state semantics may be inconsistent.

## Impact

High for browser-based validation.

If screenshots are captured but JavaScript evaluation cannot return data, the agent must rely on visual inspection alone. That is weaker, slower, and easy to misreport. In this case, Chrome MCP provided a stronger control path, so the regression is likely in `browser_*`, not the target page.

## Notes

One earlier test incorrectly batched stateful browser operations in parallel. That result should not be used as primary evidence. The serial follow-up still showed the problematic behavior: page info and screenshots worked, while `browser_wait` timed out and `browser_js` failed to expose values.

## Acceptance Criteria for Fix

- `browser_js({"expression": "document.title"})` returns the actual page title string.
- `browser_js({"expression": "location.href"})` returns the actual URL string.
- `browser_js` can return JSON/stringified objects for DOM inspection.
- `browser_wait` behavior is documented and/or adjusted so SPA pages do not produce misleading timeouts when render is available.
- A regression test covers at least one static page and one SPA/image-heavy page.
