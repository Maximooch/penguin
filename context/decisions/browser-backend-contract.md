# Browser Backend Contract Decision

Date: 2026-05-07

## Decision

Penguin will use browser-harness as the preferred `browser_*` backend when it is installed locally/from source, while keeping PyDoll as the PyPI-available fallback exposed through `pydoll_browser_*` tools.

Penguin will not add browser-harness to base dependencies or the `[browser]` extra until browser-harness has a real package/release story that can be resolved from PyPI or another deliberate package source.

## Rationale

- browser-harness is not published on PyPI yet.
- Penguin supports Python `>=3.9,<3.13`; browser-harness currently targets newer Python and its own dependency constraints.
- PyDoll remains useful as an installable fallback for users who install `penguin-ai[browser]` without a local browser-harness checkout.
- The public Penguin browser interface should remain backend-agnostic enough to swap browser-harness, PyDoll, Playwright/CDP, or a future better backend later.

## Stable Penguin-Owned Contract

Penguin owns:

- public tool names and schemas: `browser_open_tab`, `browser_page_info`, `browser_harness_screenshot`, `browser_click`, `browser_type`, `browser_key`, `browser_fill`, `browser_wait`, `browser_js`, `browser_list_tabs`, `browser_switch_tab`, `browser_status`, `browser_cleanup`
- image/artifact shape: `filepath`, `artifact.image_path`, `artifact.mime_type`
- session/agent identity mapping: deterministic `BU_NAME`
- ownership and cleanup policy
- permission metadata and safety guidance
- skill/domain-skill integration
- normalized missing-backend and connection errors

browser-harness owns:

- Chrome attach and CDP mechanics
- daemon/socket lifecycle internals
- low-level helper implementations

## Fallback Matrix

| Condition | Behavior |
|---|---|
| browser-harness installed and Chrome attach works | Use canonical `browser_*` tools. |
| browser-harness missing | `browser_*` tools return actionable local-source install guidance. |
| browser-harness installed but Chrome attach fails | `browser_status` reports connection failure and Chrome remote-debugging guidance. |
| PyDoll installed | `pydoll_browser_*` tools remain available as fallback. |
| Neither backend available | Browser tools fail with install/setup guidance; non-browser tools unaffected. |

## Vendoring Trigger

Vendoring remains an escape hatch, not the current plan. Reconsider vendoring only if:

- browser-harness upstream API churn repeatedly breaks Penguin
- install/source packaging remains too awkward for users
- dependency constraints conflict with Penguin releases
- Penguin needs lifecycle/security controls that cannot be implemented cleanly through the library boundary

## Consequence

The adapter boundary is non-negotiable: do not leak browser-harness internal types or helper names into public Penguin tool outputs except explicit diagnostic metadata such as `backend: browser-harness`.
