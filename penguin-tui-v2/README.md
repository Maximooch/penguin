# Penguin OpenCode 2 extension

Penguin runs the pinned upstream `opencode2` binary unchanged. This directory
contains only Penguin-owned TUI extensions that use OpenCode 2's supported
plugin and slot API.

Release archives place `plugins/tui/penguin.tsx` next to `bin/opencode2`. The
Penguin launcher points `OPENCODE_CONFIG_DIR` at that isolated, checksummed
sidecar root, so OpenCode discovers the extension without writing into a user
project or global OpenCode configuration. Explicit user configuration always
wins.

The extension may present Penguin branding and commands. It must not implement
HTTP transport, authentication, session persistence, provider execution, or
event translation; those remain in Penguin's server-side compatibility seam.
If an upstream plugin ABI change breaks this file, V2 can be disabled by
unsetting `PENGUIN_TUI_V2`, with the default V1 TUI and its cache untouched.

Pinned provenance and refresh checks live in
`context/tasks/penguin-tui-opencode-v2.md`.
