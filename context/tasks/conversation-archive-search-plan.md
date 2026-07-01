# Conversation Archive Search Plan

## Objective

- Add deterministic previous-session lookup over Penguin's persisted session archive.
- Expose model-callable tools for finding and opening old conversations:
  - `conversation_search`
  - `conversation_open`
  - `conversation_summary` later, after search/open behavior is stable
- Keep raw transcripts local, auditable, and canonical.
- Treat Honcho and future Context Graph work as semantic layers over the archive, not as the source of truth for transcripts.

## Why This Exists

- Penguin already persists sessions under `workspace/conversations`.
- Multi-agent sessions already have separate conversation directories under the conversations root.
- There is already a public-ish history path through:
  - `PenguinCore.get_conversation_history(...)`
  - `APIClient.get_conversation_history(...)`
- The current `grep_search` tool is not enough for previous-session lookup because it searches in-memory messages and `WORKSPACE_PATH/logs`, not the persisted conversation archive.
- Agents need a reliable way to answer questions like "what did we decide last session?" without relying on live memory, logs, or semantic recall.

## Audit Evidence

- `penguin/system/session_manager.py`
  - `SessionManager.session_index`
  - `SessionManager.load_session(...)`
- `penguin/system/conversation_manager.py`
  - initializes `SessionManager` under `workspace/conversations`
  - manages per-agent conversation systems under `conversations/<agent_id>/`
  - exposes `list_conversations(...)` and `get_conversation_history(...)`
- `penguin/core.py`
  - wraps conversation listing and history access
- `penguin/api_client.py`
  - exposes `get_conversation_history(...)`
- `penguin/web/services/session_view.py`
  - already has view-only session loading patterns that avoid mutating the active session
- `penguin/tools/core/grep_search.py`
- `penguin/tools/tool_manager.py`
  - registers and dispatches `grep_search`

## Product Shape

### `conversation_search`

Search persisted session transcripts and return ranked matches with enough context to decide what to open.

Suggested arguments:

- `query: str`
- `limit: int = 10`
- `agent_id: str | None = None`
- `session_id: str | None = None`
- `date_from: str | None = None`
- `date_to: str | None = None`
- `roles: list[str] | None = None`
- `case_sensitive: bool = False`

Suggested result fields:

- `session_id`
- `agent_id`
- `title` or best available session label
- `created_at`
- `updated_at`
- `message_index`
- `role`
- `excerpt`
- `match_count`
- `score`

### `conversation_open`

Open one persisted session or a bounded slice of one persisted session.

Suggested arguments:

- `session_id: str`
- `agent_id: str | None = None`
- `message_start: int | None = None`
- `message_end: int | None = None`
- `around_message: int | None = None`
- `context_messages: int = 5`
- `include_metadata: bool = True`

Suggested behavior:

- Load the session in a view-only way.
- Return structured messages plus session metadata.
- Never switch the active session.
- Never write to the loaded session as a side effect.

### `conversation_summary`

Optional later tool that summarizes a selected session or result set.

Defer this until deterministic lookup is working. Summary quality should be layered on top of reliable transcript retrieval, not used as a substitute for it.

## Recommended Implementation

### Phase 1 - JSON Archive Tool

- Add `penguin/tools/core/conversation_archive.py`.
- Implement a small archive service with a read-only API:
  - discover conversation roots
  - load session indexes
  - load sessions without mutating active state
  - normalize transcript messages into searchable records
  - search records deterministically
  - open sessions or bounded message slices
- Reuse `SessionManager.session_index` and `SessionManager.load_session(...)`.
- Reuse the view-only pattern from `penguin/web/services/session_view.py`.
- Scan JSON/session data directly for the first implementation.
- Include root-agent and per-agent session directories.
- Register `conversation_search` and `conversation_open` in `ToolManager`.
- Add deterministic unit tests with temporary conversation directories and fake sessions.

### Phase 2 - SQLite FTS5 Sidecar

- Add a local sidecar index for fast transcript search.
- Keep JSON session files as the canonical transcript store.
- Rebuild or incrementally update the FTS index from session metadata and message content.
- Store only derived search rows in SQLite:
  - session identity
  - agent identity
  - message identity/index
  - role/category
  - searchable text
  - timestamps and lightweight metadata
- Add an explicit index refresh path if automatic refresh is too invasive for v1.
- Keep search results reproducible and inspectable.

### Phase 3 - Semantic Overlay

- Add `HonchoBackend` as a semantic profile/search/reasoning layer.
- Use Honcho for questions like:
  - "What does this imply?"
  - "What patterns have emerged across sessions?"
  - "What does this user usually prefer?"
- Do not use Honcho as the canonical transcript store.
- Keep all semantic results traceable back to local transcript session IDs and message ranges.

### Phase 4 - Context Graph Backend

- Add `ContextGraphBackend` only after the deterministic archive and semantic overlay contracts are stable.
- Treat Context Graph as a future durable graph projection over transcripts, decisions, tasks, entities, and relationships.
- Expect this to be a larger architecture project, not part of the MVP.

## Backend Split

- `JsonFtsBackend`
  - canonical deterministic archive access
  - JSON scan first, SQLite FTS5 sidecar later
  - local, auditable, reproducible
- `HonchoBackend`
  - semantic memory and peer/user profile layer
  - useful for inference and recall, not transcript authority
- `ContextGraphBackend`
  - future durable graph layer
  - useful for relationship traversal, project memory, and higher-level knowledge modeling

## Architecture Constraints

- Raw transcripts remain local and auditable.
- Archive reads must be view-only and must not mutate the active `ConversationSystem`.
- Tool implementation belongs under `penguin/tools/core/`, not in `PenguinCore`.
- `ToolManager` should register and dispatch the tools, but business logic should live in the archive module/service.
- Web routes should remain thin if an HTTP surface is added later.
- Do not overload `grep_search`; previous-session lookup deserves explicit tool names and archive-specific result shape.

## Testing Plan

- Unit tests for JSON session discovery across:
  - root conversations directory
  - per-agent conversation directories
  - missing or partial `session_index.json`
  - malformed session files
- Unit tests for deterministic search behavior:
  - case-insensitive matching
  - case-sensitive matching
  - role filtering
  - date filtering
  - result limits
  - stable ranking/tie-breaking
- Unit tests for `conversation_open`:
  - full-session open
  - bounded message ranges
  - around-message slices
  - nonexistent session handling
  - view-only reads do not mutate the active session
- Tool registration tests in the existing tool mapping suite.
- Optional FTS tests once the sidecar backend exists:
  - rebuild behavior
  - stale index detection
  - query escaping
  - snippet/excerpt generation

## Verification Targets

- `pytest -q tests/test_core_tool_mapping.py`
- targeted archive-tool tests under `tests/tools/`
- targeted session-view regression tests under `tests/api/test_session_view_service.py`
- `ruff check penguin/tools/core/conversation_archive.py tests/tools`

## Effort Estimate

- JSON scan tool: 0.5-1 day
- SQLite FTS archive with search/open: 2-3 days
- Honcho semantic layer: 3-7 days
- Context Graph-native version: multi-week

## Recommendation

Ship deterministic `conversation_search` and `conversation_open` first.

This is the boring path, which is the right path here: fast, local, auditable, and immediately useful. Once it works reliably, add Honcho as the semantic "what does this imply?" layer on top of transcript-backed results.
