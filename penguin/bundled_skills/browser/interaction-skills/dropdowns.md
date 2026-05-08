# Dropdowns

Dropdowns are not one thing. Identify the implementation before interacting.
Always open the dropdown first, then re-measure option geometry because many
menus render lazily, animate, or virtualize options after the click.

## Native Selects

Native `<select>` elements expose options directly:

```python
js("""
const select = document.querySelector('select[name=country]');
select.value = 'US';
select.dispatchEvent(new Event('change', {bubbles: true}));
""")
```

Prefer DOM value setting for native selects; coordinate clicks can be OS/browser
specific.

## Custom Overlays

Custom menus often render in portals outside the trigger element. Workflow:

1. click the trigger;
2. wait for `role=listbox`, menu container, or visible option text;
3. re-measure option coordinates;
4. click the option.

```python
click_at_xy(trigger_x, trigger_y)
wait_for_element("[role=listbox], .menu, .popover", timeout=5)
options = js("[...document.querySelectorAll('[role=option]')].map(o => o.textContent)")
```

## Searchable Comboboxes

Comboboxes usually need focus + text input + selection:

```python
click_at_xy(input_x, input_y)
type_text("California")
wait_for_element("[role=option]", timeout=5)
```

Use accessibility roles when available: `combobox`, `listbox`, `option`.

## Virtualized Menus

Virtualized lists render only visible options. If the target is absent:

- scroll the menu container, not the page;
- re-query options after each scroll;
- stop when option text appears or the scroll position stops changing.

Re-measure after opening, after filtering, and after every menu scroll. Geometry
from before opening is stale by definition.
