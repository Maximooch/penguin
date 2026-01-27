# Context Messages and Memory System Report

## Scope and sources

This report is based on these primary files and docs:

- `README.md`
- `architecture.md`
- `penguin/system/state.py`
- `penguin/system/conversation.py`
- `penguin/system/conversation_manager.py`
- `penguin/system/context_window.py`
- `penguin/system/session_manager.py`
- `penguin/system/context_loader.py`
- `penguin/llm/model_config.py`
- `penguin/constants.py`
- `penguin/memory/__init__.py`
- `penguin/memory/summary_notes.py`
- `penguin/memory/declarative_memory.py`
- `penguin/memory/providers/*`
- `penguin/memory/indexing/incremental.py`
- `penguin/tools/tool_manager.py`
- `penguin/cli/ui.py`
- `docs/docs/system/context-window.md`
- `docs/docs/system/conversation-manager.md`
- `docs/docs/system/memory-system.md`
- `docs/docs/configuration.md`

## How context messages work in Penguin today

### Message categories and defaults

- Categories are defined in `penguin/system/state.py` as `MessageCategory`: `SYSTEM`, `CONTEXT`, `DIALOG`, `SYSTEM_OUTPUT`, plus `ERROR`, `INTERNAL`, and `UNKNOWN`.
- Default categorization happens inside `ConversationSystem.add_message()` in `penguin/system/conversation.py`:
  - `role == "system"` and `content == system_prompt` => `SYSTEM`.
  - `role == "system"` and content contains markers like `action executed`, `code saved to`, `result`, `status` => `SYSTEM_OUTPUT`.
  - Other `role == "system"` => `CONTEXT`.
  - All non-system roles default to `DIALOG`.
- `ConversationSystem.add_context()` is a convenience method that always adds a `role="system"`, `category=CONTEXT` message.

### Where context messages come from

1. **Manual or tool-driven context injection**
   - `ConversationManager.add_context()` delegates to `ConversationSystem.add_context()`.
   - Context messages are stored directly in the active `Session` in `penguin/system/state.py`.

2. **Context folder autoload**
   - `SimpleContextLoader` in `penguin/system/context_loader.py` loads files listed in `context/context_config.yml` and adds them as `CONTEXT` messages.
   - These are loaded at `ConversationManager` initialization (`load_core_context()`).

3. **Project docs autoload**
   - `ConversationManager` calls `ContextWindowManager.load_project_instructions()` when `context.autoload_project_docs` is enabled (default in `penguin/config.yml`).
   - `load_project_instructions()` in `penguin/system/context_window.py` loads `PENGUIN.md`, `AGENTS.md`, or `README.md` from the workspace root and adds the result as a single `CONTEXT` message (with size caps).

### Session boundaries and continuity

- `SessionManager.create_continuation_session()` copies **all `SYSTEM` and `CONTEXT` messages** from the source session into the new session, then adds a `SYSTEM` transition marker.
- This guarantees context messages persist across long-running sessions even when message count limits trigger session rotation.

### Multi-agent context sharing

- `ConversationManager.create_sub_agent()` has flags for `share_session` and `share_context_window`.
- If sessions are isolated (`share_session=False`), it **copies SYSTEM/CONTEXT** messages into the child via `partial_share_context()`.
- If context windows are not shared, it optionally **clamps** the child context window size and emits a `cw_clamp_notice` system note.

### UI visibility

- The CLI UI (`penguin/cli/ui.py`) defaults to **hiding** `SYSTEM`, `CONTEXT`, and `SYSTEM_OUTPUT` messages unless `show_context_messages` is enabled.
- This means context messages exist and influence the model but are often invisible to the user unless toggled.

## Context window management (token budgets and trimming)

### Configuration resolution

- `ContextWindowManager` resolves `max_context_window_tokens` from `config.yml` via `model.context_window` and applies `safe_context_window()` (85% safety fraction by default, controlled by `PENGUIN_CONTEXT_SAFETY_FRACTION`).
- If no model context is configured, it falls back to `DEFAULT_CONTEXT_WINDOW_EMERGENCY_FALLBACK_TOKENS` (100,000) via `get_default_context_window_emergency_fallback_tokens()`.
- Token counting uses (in priority order): explicit token counter, API client counter, model config counter, `diagnostics.count_tokens()` (tiktoken), or a fallback estimator.

### Category budgets and trimming

- Default budget allocations (in code) are:
  - `SYSTEM`: 10%
  - `CONTEXT`: 30%
  - `DIALOG`: 40%
  - `SYSTEM_OUTPUT`: 20%
  - Other categories (`ERROR`, `INTERNAL`, `UNKNOWN`) are assigned a small fallback budget from `CONTEXT_UNCATEGORIZED_BUDGET_FRACTION` (5% default).
- Trim order is: `SYSTEM_OUTPUT` -> `DIALOG` -> `CONTEXT`. `SYSTEM` is preserved.
- Trimming is **chronological** within each category (oldest first) and records truncation events for UI display.
- Images are handled specially: if more than `DEFAULT_MAX_CONTEXT_IMAGES` (5), oldest images are replaced with placeholders before token trimming.

### Notable doc/code mismatch

- `docs/docs/system/context-window.md` lists different category percentages (SYSTEM 10%, CONTEXT 35%, DIALOG 50%, SYSTEM_OUTPUT 5%).
- Actual code in `penguin/system/context_window.py` is 10/30/40/20. This mismatch can confuse tuning and should be reconciled.

## Memory system configuration and behavior

### Provider architecture

- Memory lives under `penguin/memory` and uses a **pluggable provider** interface (`MemoryProvider` in `penguin/memory/providers/base.py`).
- `MemoryProviderFactory` auto-selects providers in priority order: `lancedb` > `faiss` > `sqlite` > `file`.
- Default storage path is workspace-scoped: `WORKSPACE_PATH/memory_db` (via `penguin/memory/__init__.py` and `penguin/memory/providers/factory.py`).

### Configuration knobs

- The memory system is configured by a `memory:` block in config (see `docs/docs/configuration.md`). Example:
  ```yaml
  memory:
    provider: sqlite
    storage_path: "${paths.memory_db}"
    embedding_model: sentence-transformers/all-MiniLM-L6-v2
    providers:
      sqlite:
        database_file: penguin_memory.db
  ```
- Memory can be disabled by setting `memory.enabled: false` (checked in `ToolManager._initialize_memory_provider`).
- Memory tools are gated by `tools.allow_memory_tools` (default `False` if not set). If it is absent, memory search returns an error.

### Tooling integration

- `ToolManager` lazily initializes the memory provider when memory tools are used.
- Background indexing uses `IncrementalIndexer` to index **notes/** and **conversations/** under `WORKSPACE_PATH`.
- Memory tools exposed include `memory_search` and `reindex_workspace` (see `penguin/tools/tool_manager.py`).
- Summary and declarative notes are **not** stored in the provider by default. They are file-backed YAML (`notes/summary_notes.yml`, `notes/declarative_notes.yml`).

### Summary/declarative notes

- `SummaryNotes` and `DeclarativeMemory` are lightweight YAML-backed stores.
- Actions `<add_summary_note>` and `<add_declarative_note>` write to these files via `ToolManager`.
- These notes are useful for persistent, human-readable state but **do not automatically feed into context** unless explicitly loaded or searched.

## Gaps and friction points

1. **Context loader on-demand path uses a missing method**
   - `SimpleContextLoader.load_file()` calls `context_manager.add_working_memory()` which does not exist in `ConversationSystem` or `ConversationManager`.
   - This likely breaks on-demand context file loading.

2. **Memory tools are disabled by default**
   - `tools.allow_memory_tools` defaults to `False` unless explicitly set in config.
   - This makes memory search and indexing unavailable without configuration.

3. **Memory config is not present in default config.yml**
   - `penguin/config.yml` does not include a `memory:` block, which means memory tools error unless users add configuration.

4. **Context budget docs mismatch**
   - Docs and code disagree on category allocation values.

5. **Context messages are hidden in CLI by default**
   - This reduces transparency of what is influencing the model, especially project-doc autoload and core context files.

## Proposed improvements: Journal 247 system

A journal-driven system can extend continuous operation across hours/days while preserving coherence and reducing context bloat. The goal is to provide a stable, queryable, and continuously updated memory layer that complements the context window.

### Design goals

- **Continuity across long runs:** keep a rolling, structured history of decisions, tasks, and results even when context is trimmed.
- **Low-friction recall:** latest state can be injected as a compact `CONTEXT` message when resuming or when token limits are near.
- **High signal density:** compress raw session text into structured journal entries.
- **Operator visibility:** readable updates for users at configurable intervals.

### Core components

1. **Journal entries (durable, append-only)**
   - Stored as JSONL or YAML under `notes/journal/` (e.g., `notes/journal/2026-01-27.jsonl`).
   - Suggested schema:
     ```json
     {
       "timestamp": "2026-01-27T12:34:56Z",
       "agent_id": "default",
       "run_id": "run_...",
       "summary": "...",
       "decisions": ["..."],
       "progress": ["..."],
       "open_questions": ["..."],
       "files_touched": ["..."],
       "tags": ["context", "memory"],
       "source_session": "session_...",
       "token_usage": {"total": 12345}
     }
     ```

2. **Journal summarizer (periodic)**
   - Triggers on:
     - token usage threshold (e.g., 70-80% of context budget),
     - time interval (e.g., every 15-30 minutes),
     - checkpoint creation events,
     - run-mode iterations.
   - Uses `<add_summary_note>` and `<add_declarative_note>` as building blocks, then writes a structured journal entry.

3. **Journal injector (context bootstrap)**
   - On session start or when resuming, load the **latest journal summary** as a `CONTEXT` message.
   - Add a compact “state digest” (current goals, open tasks, last changes) to reduce rehydration cost.

4. **Journal indexer (memory provider integration)**
   - Journal files are indexed by the existing `IncrementalIndexer` (already scans `notes/`).
   - Add a `journal` category to metadata for targeted retrieval.

### Suggested config additions

```yaml
journal:
  enabled: true
  interval_minutes: 20
  max_entries_per_day: 200
  inject_latest_on_start: true
  token_threshold_fraction: 0.75
  summary_token_budget: 1200
  include_files: true
  include_errors: true
  redact_patterns: ["api_key", "secret"]
```

### Integration points in current code

- **ConversationManager**: hook journaling into `add_message()` or after `process_session()` when token usage approaches limits.
- **CheckpointManager**: create journal entries on checkpoints for reliable phase summaries.
- **ToolManager**: add `add_journal_entry`, `list_journal_entries`, and `journal_status` tools.
- **ContextWindowManager**: treat journal summaries as `CONTEXT` with a reserved mini-budget so they survive trimming.

### Continuous updates for long-running tasks

- Add a “journal heartbeat” that emits a summarized status update to the UI/console every N minutes.
- Provide a `/journal` command to display the latest digest or filter by tags.
- Support rolling daily summaries (e.g., `notes/journal/daily_summary.md`) for human scanning.

## Practical next steps

1. Fix `SimpleContextLoader.load_file()` to use `add_context()` or reintroduce `add_working_memory()`.
2. Decide whether memory tools should be enabled by default; if so, add `allow_memory_tools: true` and a default `memory:` block in config.
3. Reconcile context budget values between code and docs.
4. Prototype Journal 247 with:
   - a JSONL journal writer,
   - a minimal config block,
   - a CLI command to view the latest entry,
   - and injection of the most recent journal summary as a `CONTEXT` message on startup.

