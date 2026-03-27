# Context Loading Hygiene TODO

## Objective

- Stop archived, backup, session, and log files from polluting normal context loading and search.
- Preserve historical material in `context/archive/` without letting it impersonate current truth.
- Make default context ingestion prioritize current architecture, tasks, rationale, and process docs.

## Why This Exists

- Audit searches were polluted by archived docs, backups, sessions, and other stale files.
- If Penguin loads or searches these by default, the model gets noise instead of signal.
- Historical context is useful only when explicitly requested.

## Audit Evidence

- `context/archive/`
- `context/docs_cache/`
- `context/journal/`
- search results during context reorg and tool/LLM audit
- prompt/context-loading references in `penguin/prompt_workflow.py` and related loaders

## Progress Snapshot

- [ ] Identify where default context loading/search includes archived noise
- [ ] Define a default include/exclude policy for `context/`
- [ ] Exclude backups, logs, sessions, and archived docs from default ingestion
- [ ] Keep explicit opt-in access to archived material
- [ ] Add tests/docs for the new default behavior

## Proposed Default Policy

### Prefer by Default
- `context/architecture/`
- `context/tasks/`
- `context/rationale/`
- `context/process/`
- `context/MEMORY.md`

### Exclude by Default
- `context/archive/`
- `context/docs_cache/`
- `context/journal/` except when explicitly requested by workflow
- `*.bak`
- `*.backup`
- session dumps
- generated logs/media

## Checklist

### Phase 1 - Discovery
- [ ] Trace the code paths that load/search project context
- [ ] Identify all default inclusions that should become opt-in
- [ ] Confirm whether docs cache should ever auto-load

### Phase 2 - Policy
- [ ] Define centralized ignore/include rules
- [ ] Apply the same rules to search, context ingestion, and any auto-discovery helpers
- [ ] Document override paths for deliberate archival lookup

### Phase 3 - Verification
- [ ] Add regression tests for ignored paths
- [ ] Verify current-task docs remain discoverable
- [ ] Verify archived docs are still searchable when explicitly targeted

## Verification Targets

- context command tests
- memory/context loading tests
- any auto-discovery tests around project docs
- manual search sanity checks

## Notes

- Archive is not garbage.
- It just should not sit in the driver’s seat.
