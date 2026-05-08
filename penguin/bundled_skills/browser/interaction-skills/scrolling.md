# Scrolling

Before scrolling, identify which element consumes wheel events. Page scroll,
nested containers, dropdown menus, and virtualized lists can all behave
differently.

## Page Scroll

Use viewport wheel scrolling when the document itself scrolls:

```python
scroll(x=600, y=500, dy=700)
```

Verify progress with `page_info()` or JavaScript:

```python
js("({y: window.scrollY, max: document.documentElement.scrollHeight})")
```

## Nested Containers

If a panel owns scrolling, wheel over the panel or set its scrollTop:

```python
js("document.querySelector('.results').scrollTop += 600")
```

Signals for nested scroll:

- `window.scrollY` does not change;
- panel has `overflow: auto` or `scroll`;
- content moves inside a fixed viewport.

## Dropdowns And Virtualized Lists

Dropdowns often consume wheel events. Open the menu, find the menu container,
scroll that container, then re-measure options.

```python
js("document.querySelector('[role=listbox]').scrollTop += 400")
```

Virtualized lists only render visible rows. After each scroll, re-query DOM text
and geometry. Stop when the target appears or scrollTop stops changing.

## Best Practices

- Avoid blind repeated page-downs.
- Log before/after scroll positions when debugging.
- Re-measure clickable coordinates after every scroll.
- If wheel events do nothing, inspect the element under the cursor and nearest
  scrollable ancestors.
