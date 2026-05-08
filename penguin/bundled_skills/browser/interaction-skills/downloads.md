# Downloads

Distinguish browser-triggered downloads from direct HTTP fetches. Use the browser
path when the file is produced by UI state, auth, redirects, or a generated blob.
Use direct `http_get(...)` when the URL is stable and authenticated headers are
not required.

## Direct Fetch

Use direct fetch when an anchor exposes a real downloadable URL:

```python
href = js("document.querySelector('a.download')?.href")
response = http_get(href)
```

Signals that direct fetch is enough:

- URL is absolute and stable.
- Response has expected `Content-Type` or `Content-Disposition`.
- Byte size is plausible and non-zero.
- Auth is not tied to transient browser-only state.

## Browser-Triggered Download

Use browser interaction when clicking starts the download:

```python
click_at_xy(x, y)
wait_for_network_idle(timeout=10)
```

Minimal proof that a browser download started:

- network response with expected MIME type or `Content-Disposition`;
- browser download directory receives a new file;
- UI state changes to downloaded/exported;
- file size stops growing before reading it.

## Edge Cases

- Blob URLs (`blob:`) usually require browser context.
- Export buttons may generate files after background jobs; wait for the UI ready
  state, not just network idle.
- Some sites open a new tab for the file; check tabs after clicking.
- Do not assume a click downloaded a file unless you can point to a file path,
  response headers, or a stable UI confirmation.
