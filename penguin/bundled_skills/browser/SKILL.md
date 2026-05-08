---
name: browser
description: Browser automation through Penguin's browser-harness-backed tools. Use for web-app testing, visual verification, authenticated browser workflows, dynamic pages, and browser-specific scraping when static HTTP/doc scripting is insufficient.
allowed-tools:
  - browser_open_tab
  - browser_page_info
  - browser_harness_screenshot
  - browser_click
  - browser_type
  - browser_key
  - browser_fill
  - browser_wait
  - browser_js
  - browser_list_tabs
  - browser_switch_tab
  - read_image
---

# Browser Skill

Use this skill when a task requires an actual browser: web-app testing, visual verification, authenticated workflows, dynamic/SPA pages, screenshots, coordinate interaction, iframe/shadow-DOM-heavy UIs, downloads/uploads, or browser-specific debugging.

For ordinary documentation lookup and static scraping, prefer scriptable approaches first: official docs, HTTP fetches, search, or page JavaScript extraction. A real browser is most valuable when you need to verify software Penguin built, interact with stateful UI, or inspect dynamic pages that do not expose useful static HTML.

## Penguin Tool Workflow

1. Open a new tab with `browser_open_tab`; do not clobber a user's active tab.
2. Check `browser_page_info` to confirm URL/title/tab state.
3. Capture `browser_harness_screenshot` before and after meaningful visible actions.
4. Use `read_image` for arbitrary local screenshots/artifacts that did not originate from the browser tool.
5. For web-app testing, prefer screenshot -> coordinate click/type/key -> screenshot verification.
6. For docs/data extraction, prefer `browser_js` or non-browser scripting over repeated manual clicking.
7. Use DOM/CDP-style inspection only when screenshots/coordinates are the wrong tool: hidden nodes, data extraction, virtual DOM state, network ambiguity, or precise selector reads.

## Interaction References

Progressively load references from `interaction-skills/` only when the mechanic appears:

- `screenshots.md` - image sizing, devicePixelRatio, and max dimensions.
- `tabs.md` - tab selection and stale/internal target recovery.
- `connection.md` - local Chrome/CDP connection troubleshooting.
- `dialogs.md` - browser dialogs and modal handling.
- `dropdowns.md` - native/custom dropdown strategy.
- `iframes.md` and `cross-origin-iframes.md` - iframe caveats.
- `shadow-dom.md` - shadow DOM caveats.
- `network-requests.md` - ambiguous SPA/network completion.
- `profile-sync.md` - remote/profile workflows when supported.
- `downloads.md`, `uploads.md`, `drag-and-drop.md`, `scrolling.md`, `viewport.md`, `cookies.md`, `print-as-pdf.md` for specific mechanics.

Do not bulk-load every reference. Pick the smallest reference that matches the current failure mode.

## Domain Skills

Browser domain skills live under `domain-skills/<hostname>/` inside this browser skill directory. They are opt-in site playbooks, not global prompt content.

When domain skills are enabled, look for host-specific notes before inventing a site-specific approach. If no host skill exists, continue normally and only add a new domain skill when you discover a durable site behavior worth reusing.

Use the domain skill template and redaction policy in `domain-skills/README.md`. Domain skills must describe stable public mechanics, not private task diaries.

## Safety Rules

- A real browser may be logged into real accounts. Treat it as user state, not a disposable sandbox.
- Do not enter credentials, payment details, secrets, or 2FA codes from screenshots or memory. Ask the user to perform sensitive entry.
- Confirm before purchases, posting, account changes, destructive admin actions, legal/medical/financial submissions, or sending messages.
- Redact secrets before saving learned domain skills. Store selectors, URL patterns, public API shapes, waits, and stable quirks; never store cookies, tokens, account IDs, private URLs with sensitive query params, personal data, or screenshot-derived secrets.
