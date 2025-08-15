# Penguin Improvements (Backlog)

## Streaming & UX
- Reasoning banner: Show transient 🧠 status in sidebar during reasoning; do not insert separate messages. Collapse into <details> on final.
- Idempotent streaming protocol: Include cumulative offset in `stream_chunk` events so UI can reconcile dropped chunks; only render unseen suffixes.
- Spinner visibility: Keep sidebar spinner until first assistant chunk arrives; hide immediately on first content.
- Throttle scroll updates: Scroll every N chunks or on idle to reduce jank.

## Markdown & Code Rendering
- Heuristic language fencing for action/tool outputs (python/json) to improve syntax highlighting.
- Normalize assistant content: ensure triple backticks are balanced; coerce stray code into fenced blocks when confidence is high.
- Optional: run a light formatter for Python snippets in compact mode for readability (off by default).

## Action/Tool Visuals
- Remove redundant `text` labels; rely on fences and ribbons only.
- Auto-compact large outputs with head/tail preview and collapsible full content.
- Subtle gutter lines to group action→result blocks (Claude Code style).

## Behavior & Planning
- Reduce redundant actions and over-thinking:
  - Add a “decision gate” template step before tools: summarize intended action in one line and expected signal.
  - Track last N actions + outcomes; avoid repeating same failing action unless inputs changed.
  - Add hard cap per turn: max K tools; require justification to exceed.
- Introduce lightweight memory of “recent failures” per action name and parameters hash.

## Performance
- Virtualize message list (replace full `VerticalScroll` with a windowed adapter when message count > threshold).
- Batch Markdown updates with a small debounce (already partially implemented).
- Avoid re-layout by limiting mount/remove during streaming.

## Testing & Diagnostics
- Golden transcript tests for streaming edge cases (reasoning→assistant switch, missing final chunk, duplicate message suppression).
- Snapshot diff tests for action/result rendering.
- Add a `/perf profile` command to log frame time and mount counts.

## Roadmap Notes
- Consider a dedicated diff viewer widget when needed (inline syntax-aware, jump-by-hunk).
- Optional keybindings once visuals settle.
