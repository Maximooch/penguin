# TUI Validation Checklist

## Order

1. Automated gates
2. Startup and directory coherence (`I2`)
3. Running animation continuity (`I1`)
4. Interrupt and exit behavior (`I4`)
5. Record temporary exceptions

## Automated Gates

- [ ] Run Python regressions:
  - `pytest -q tests/test_core_tool_mapping.py tests/test_part_event_persist_callback.py`
  - `pytest -q tests/test_cli_entrypoint_dispatcher.py tests/test_opencode_launcher.py`
  - `pytest -q tests/api/test_opencode_session_routes.py tests/api/test_session_view_service.py`
- [ ] Run TUI typecheck:
  - `bun run typecheck`
- [ ] Confirm `publish-tui.yml` is green for:
  - `linux-arm64`
  - `linux-x64`
  - `linux-x64-baseline`
  - `linux-arm64-musl`
  - `linux-x64-musl`
  - `linux-x64-baseline-musl`
  - `macos`
  - `windows`
- [ ] Note known temporary exception:
  - Windows baseline artifact is intentionally skipped for now

## I2 Startup / Directory Coherence

- [ ] Launch from repo root with `penguin`
- [ ] Launch with `ptui`
- [ ] Launch headless with `penguin-cli config setup`
- [ ] Launch in GH workspace with `PENGUIN_TUI_BIN_PATH=... penguin`
- [ ] Verify working directory behavior when launched from:
  - project root
  - parent directory with project path argument
  - unrelated directory pointing at project
- [ ] Confirm expected results:
  - active session binds to the intended project immediately
  - first tool call uses the correct root with no corrective prompt
  - `/path`, `/vcs`, `/formatter`, and `/lsp` reflect the chosen directory
  - continuing the session preserves that binding
- [ ] Capture one proof point, for example:
  - `pwd` from inside the session
  - a file read/write rooted in the expected project

## I1 Running / Animation Continuity

- [ ] Run prompts that create silent action phases, for example:
  - "Inspect this repo and summarize the architecture"
  - "Read these files and compare them"
  - prompts that trigger `glob`, `grep`, `read`, or tool cards before text
- [ ] Confirm the spinner or working animation:
  - stays active through tool-only phases
  - does not flicker idle between stream end and tool start
  - does not look crashed while files or tools are running
  - returns to idle only after the full turn finishes
- [ ] Repeat with:
  - short prompt
  - long tool-heavy prompt
  - one interrupted prompt
- [ ] If it fails, capture:
  - screenshot or short recording
  - session id
  - relevant server log around `session.status`

## I4 Interrupt / Exit

- [ ] Idle behavior:
  - `Ctrl+D` exits
  - `<leader>q` exits
  - `Ctrl+C` clears input only
- [ ] Busy behavior:
  - `Esc` interrupts the current run
  - `/exit` while busy shows confirm dialog
  - confirm path interrupts and exits cleanly
  - cancel path keeps app open and the run continues
- [ ] Route-specific checks:
  - main prompt route
  - child/session route
  - shell mode: `Esc` exits shell mode without doing the wrong thing
- [ ] Confirm there is no misleading "esc again to interrupt" behavior in Penguin mode
- [ ] Confirm no stuck busy state remains after interrupt-and-exit

## PR Exit Criteria

- [ ] All automated gates pass
- [ ] `penguin` and `ptui` launch correctly in GH workspace with branch artifact override
- [ ] Directory and root are correct on first tool call
- [ ] Running animation remains visible during non-token action phases
- [ ] Exit and interrupt behavior matches:
  - `Esc` interrupt
  - `Ctrl+C` clear input
  - `Ctrl+D` / `<leader>q` exit
  - busy exit = confirm interrupt and exit

## Temporary Exceptions To Note In PR

- [ ] Branch validation still uses `PENGUIN_TUI_BIN_PATH` until release assets are consumed automatically
- [ ] Temporary branch trigger in `.github/workflows/publish-tui.yml` should be removed post-merge
- [ ] Windows baseline sidecar artifact is still intentionally skipped for now
