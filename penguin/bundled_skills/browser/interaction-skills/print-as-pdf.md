# Print As PDF

Prefer CDP PDF generation when the page can be printed directly. Use UI-driven
print flows only when the site requires clicking a visible Print/Export button to
prepare printable content.

## CDP `Page.printToPDF`

Use Chrome DevTools Protocol for deterministic PDF output:

```python
pdf = cdp(
    "Page.printToPDF",
    printBackground=True,
    landscape=False,
    scale=1.0,
    marginTop=0.4,
    marginBottom=0.4,
    marginLeft=0.4,
    marginRight=0.4,
)
```

The response contains base64 PDF data. Verify page count, file size, and whether
CSS print media rules were applied.

## Site Print Button Flow

Some sites generate printable content only after a button click:

1. use `browser_click` on the visible Print/Export button;
2. intercept or neutralize `window.print` if needed;
3. wait for the printable DOM/route/tab;
4. use `Page.printToPDF` on that final page.

```python
js("window.__penguinPrintCalled=false; window.print=()=>{window.__penguinPrintCalled=true}")
browser_click(print_x, print_y)
browser_wait(mode="network_idle", timeout=10)
```

Avoid OS print dialogs in automation. If a headful dialog appears, prefer closing
it and using CDP rather than trying to click native UI.

## Testing Tips

- Check headers/footers if the site expects them.
- Verify pagination and page breaks.
- Confirm `@media print` CSS is active.
- Compare visible page content with PDF content before declaring success.
