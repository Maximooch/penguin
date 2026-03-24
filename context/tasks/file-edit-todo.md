# File Edit Consolidation TODO

## Objective

- Consolidate Penguin's file editing stack behind one reliable internal contract.
- Fix the current `multiedit` changed-file / LSP reporting bug first.
- Keep legacy behavior working while we migrate parser tags, tool schemas, and UI metadata.

## Progress Snapshot

- [x] Onboard the edit stack and confirm the current drift points
- [x] Add regression coverage for parser/schema/result mismatches
- [x] Fix `multiedit` changed-file reporting for LSP and UI refresh
- [x] Introduce a canonical file edit result contract
- [x] Route edit execution through one adapter/service layer
- [x] Normalize public edit tool names and centralized aliases
- [ ] Move edit payloads to JSON-first requests
- [ ] Collapse duplicate edit implementations
- [ ] Generate prompt docs from the same schema/registry source
- [ ] Remove legacy public edit tools once aliases are stable

## Current Audit Notes

- Parser/action-tag surface lives in `penguin/utils/parser.py` and `penguin/prompt_actions.py`.
- Tool schema + dispatch surface lives in `penguin/tools/tool_manager.py`.
- Concrete edit behavior lives in `penguin/tools/core/support.py` and `penguin/tools/multiedit.py`.
- TUI/OpenCode metadata is another contract surface in `penguin/core.py`.
- Current naming drift:
  - `enhanced_write` vs `write_to_file`
  - `multiedit` vs `multiedit_apply`
- Current schema drift:
  - parser exposes `replace_lines`, `insert_lines`, `delete_lines`
  - ToolManager dispatch supports them
  - ToolManager schema does not expose them
- Current live bug:
  - `ActionExecutor._extract_changed_files()` does not handle `multiedit`
  - `_execute_multiedit()` returns `files_edited`, but LSP refresh still reparses raw params
- Current result drift:
  - support layer returns a mix of plain strings, JSON strings, and ad hoc dict-like structures
  - `multiedit.py` has its own `MultiEditResult`

## Canonical JSON Direction

- `write_file` stays a direct JSON request with `path`, `content`, and optional `backup`.
- `patch_file` should converge on a nested JSON request with a single `operation` object.
- `patch_files` should converge on a structured JSON request with an `operations` array.
- Raw patch text / multiedit block content should remain a compatibility path during migration, not the long-term canonical interface.

## Working File Map

### Primary Refactor Targets

- `penguin/utils/parser.py`
- `penguin/tools/tool_manager.py`
- `penguin/core.py`

### Implementation Targets

- `penguin/tools/core/support.py`
- `penguin/tools/multiedit.py`
- `penguin/prompt_actions.py`

### Planned New Modules

- `penguin/tools/editing/contracts.py`
- `penguin/tools/editing/service.py`

### Likely Test Targets

- `tests/test_parser_and_tools.py`
- `tests/test_action_tag_parser.py`
- `tests/test_action_executor_subagent_events.py`
- `tests/test_core_tool_mapping.py`
- `tests/test_support_diff_metadata.py`
- `tests/tools/test_multiedit_apply.py`
- `tests/tools/test_multiedit_atomic.py`
- Optional new files if existing suites get too noisy:
  - `tests/tools/test_edit_contract_aliases.py`
  - `tests/utils/test_parser_edit_handlers.py`
  - `tests/integration/test_edit_lsp_reporting.py`

## Checklist

### Phase 0 - Regression Tests First

- [x] Freeze parser-visible edit action behavior before refactoring
- [x] Add coverage for parser/tool-schema parity
- [x] Add coverage for `multiedit` changed-file / LSP reporting
- [x] Add coverage for `enhanced_write` payloads ending in `:true` / `:false`
- [x] Add coverage for `replace_lines` payloads containing colons in content
- [x] Add coverage for `edit_with_pattern` payloads with colons in regex/search/replacement
- [x] Add coverage for current `multiedit_apply` output shape (`files_edited`, `files_failed`, `applied`)
- [x] Decide whether to extend existing tests or split into dedicated edit-contract suites

### Phase 1 - Canonical Contracts and Adapters

- [x] Add `penguin/tools/editing/contracts.py`
- [x] Define a canonical `FileEditResult`
- [x] Define a canonical edit operation/request shape
- [x] Add `penguin/tools/editing/service.py`
- [x] Start with adapter-style wrappers over existing support functions instead of rewriting behavior
- [x] Normalize success/error/results for:
  - `write`
  - `unified_diff`
  - `replace_lines`
  - `insert_lines`
  - `delete_lines`
  - `regex_replace`
  - `multifile_patch`
- [x] Keep legacy outward rendering available during migration

### Phase 2 - LSP / UI Reporting Fixes

- [x] Make action execution prefer returned changed files over reparsing raw params
- [x] Make action execution prefer returned diagnostics over string heuristics
- [x] Explicitly fix `multiedit` changed-file reporting in `ActionExecutor`
- [x] Ensure single-file and multi-file edits both emit normalized file lists
- [x] Keep raw param extraction only as a temporary fallback
- [x] Update core/TUI metadata handling if structured edit results provide better diff/file metadata

### Phase 3 - Canonical Public Tool Names and Alias Layer

- [x] Decide the canonical public edit names
- [x] Target public surface:
  - `read_file`
  - `write_file`
  - `patch_file`
  - `patch_files`
- [x] Add one centralized alias map in ToolManager
- [x] Route legacy names through the alias map:
  - `enhanced_write` -> `write_file`
  - `apply_diff` -> `patch_file`
  - `multiedit` -> `patch_files`
  - `edit_with_pattern` -> `patch_file`
  - `replace_lines` -> `patch_file`
  - `insert_lines` -> `patch_file`
  - `delete_lines` -> `patch_file`
- [x] Stop parser and ToolManager from owning separate public names
- [x] Fix the incorrect `multiedit_apply` schema description/default while doing this cleanup

### Phase 4 - JSON-First Payloads

- [ ] Define canonical JSON payloads for all edit requests
- [ ] Standardize `patch_file` on a nested JSON shape like `{ "path": ..., "operation": { ... }, "backup": true }`
- [ ] Standardize `patch_files` on structured JSON operations like `{ "operations": [...], "backup": true }`
- [ ] Teach parser handlers to accept canonical JSON directly
- [ ] Keep colon-delimited payloads as legacy compatibility input only
- [ ] Keep raw patch-text / multiedit `content` as a migration alias only, not the canonical multi-file contract
- [ ] Emit deprecation warnings for legacy payload parsing through the canonical result shape
- [ ] Ensure ambiguous colon parsing is no longer the primary contract

### Phase 5 - Collapse Duplicate Implementations

- [ ] Reduce duplicate backup/path/result logic across support functions
- [ ] Decide whether `multiedit.py` remains a thin facade or gets absorbed into the new edit service
- [ ] Keep one execution path per edit kind
- [ ] Keep one normalization path for changed files, diagnostics, backups, warnings, and errors

### Phase 6 - Prompt Docs From One Source of Truth

- [ ] Stop treating `penguin/prompt_actions.py` as an independent contract source
- [ ] Generate or assemble edit docs from schema/registry metadata
- [ ] Centralize alias and deprecation documentation
- [ ] Ensure prompt docs match ToolManager schema names and payload shapes

### Phase 7 - Legacy Public Surface Cleanup

- [ ] Remove model-facing legacy edit tools once migration is stable
- [ ] Remove or explicitly retain transitional aliases with a documented policy
- [ ] Confirm the public edit API is reduced to the intended minimal surface

## Suggested Execution Order

- [x] 1. Add regression tests
- [ ] 2. Fix `multiedit` LSP changed-file reporting
- [x] 2. Fix `multiedit` LSP changed-file reporting
- [x] 3. Introduce `FileEditResult` and adapter layer
- [x] 4. Route legacy edit paths through the canonical adapter/service
- [x] 5. Normalize public names and aliases
- [ ] 6. Move parser handlers to JSON-first payloads
- [ ] 7. Collapse duplicate implementations
- [ ] 8. Generate prompt docs from schema metadata
- [ ] 9. Remove legacy public edit tools

## Change Log

### 2026-03-23

- Created this task tracker and translated the audit into an execution checklist.
- Audited the current edit stack across:
  - `penguin/utils/parser.py`
  - `penguin/prompt_actions.py`
  - `penguin/tools/tool_manager.py`
  - `penguin/tools/core/support.py`
  - `penguin/tools/multiedit.py`
  - `penguin/core.py`
  - `penguin/engine.py`
- Confirmed the immediate bug: `multiedit` edits can succeed while LSP/UI receives incomplete file lists.
- Confirmed name drift, schema drift, and result-shape drift.
- Added dedicated Phase 0 regression coverage in:
  - `tests/test_edit_contract_aliases.py`
  - `tests/test_parser_edit_handlers.py`
  - `tests/test_edit_lsp_reporting.py`
  - `tests/tools/test_multiedit_apply.py`
- Captured current known failures as strict `xfail` coverage for:
  - parser/schema edit-surface drift
  - `edit_with_pattern` colon parsing in search patterns
  - `multiedit` changed-file / LSP reporting
- Added canonical Phase 1 edit modules:
  - `penguin/tools/editing/__init__.py`
  - `penguin/tools/editing/contracts.py`
  - `penguin/tools/editing/service.py`
- Routed ToolManager edit execution through the canonical edit service while preserving legacy outward tool outputs.
- Added structured service coverage in `tests/tools/test_edit_service.py`.
- Phase 2 result-first LSP reporting work completed in `penguin/utils/parser.py`.
- `ActionExecutor` now prefers structured changed-file data returned by tool results before falling back to raw action-param parsing.
- `multiedit` LSP refresh now uses returned file lists instead of emitting an empty `files` payload.
- Transitional multiedit JSON now exposes canonical `files` alongside legacy `files_edited` in `penguin/tools/editing/service.py`.
- Finished the colon-delimited regex edit bug by supporting escaped colons and JSON payloads in `parse_edit_with_pattern_payload()`.
- Normalized LSP file lists and diagnostic keys for absolute-path tool results.
- Updated core tool-card metadata to capture structured file lists returned by edit tools.
- Introduced canonical ToolManager public edit names:
  - `write_file`
  - `patch_file`
  - `patch_files`
- Added centralized ToolManager aliases for legacy edit names and routed parser edit handlers through the canonical names.
- Recorded the intended JSON-first end state:
  - `patch_file` uses a nested `operation` object
  - `patch_files` uses a structured `operations` array
- Updated ToolManager schema metadata, Responses API tool exposure, security permission mappings, and web permission mapping for the new canonical edit surface.

## Implementation Log

- Added parser-visible edit action coverage for:
  - `enhanced_write`
  - `apply_diff`
  - `multiedit`
  - `edit_with_pattern`
  - `replace_lines`
  - `insert_lines`
  - `delete_lines`
- Added parser-handler regression coverage for:
  - trailing backup parsing in `enhanced_write`
  - colon-safe replacement parsing in `replace_lines`
  - colon-safe replacement parsing in `edit_with_pattern`
- Added strict `xfail` regression coverage for the known colon-delimited `edit_with_pattern` search-pattern bug.
- Added strict `xfail` regression coverage for the known `multiedit` LSP changed-file bug.
- Added regression coverage for the current `multiedit_apply` JSON result shape as exposed by `ToolManager`.
- Chose dedicated focused suites instead of expanding already-large legacy files.
- Added `EditOperation` and `FileEditResult` as the canonical internal edit contract.
- Added `EditService` as the centralized adapter over existing support and multiedit implementations.
- Updated `ToolManager` so these edit paths now flow through the canonical adapter layer:
  - `write_to_file`
  - `apply_diff`
  - `replace_lines`
  - `insert_lines`
  - `delete_lines`
  - `edit_with_pattern`
  - `multiedit_apply`
- Preserved legacy text/JSON outputs during migration via the canonical result renderer.
- Switched the new ToolManager edit imports to package-relative imports for the new editing package.
- Added focused service tests covering:
  - canonical write result
  - canonical single-file patch result
  - canonical unified diff result
  - canonical multi-file patch result
- Added structured-result parsing helpers in `ActionExecutor` for UI/LSP refresh.
- Updated LSP refresh flow to:
  - prefer changed files returned by tool output
  - fall back to raw action-param parsing only when structured file data is unavailable
  - fall back to diagnostic-path keys when file lists are still absent
- Converted the `multiedit` changed-file LSP regression from strict `xfail` to a passing test.
- Added escaped-colon and JSON payload handling for `edit_with_pattern` parsing.
- Added path normalization helpers so single-file and multi-file edit results emit workspace-relative LSP file lists when possible.
- Updated `PenguinCore._map_action_result_metadata()` so structured edit results can attach returned file lists to tool-card metadata.
- Canonicalized ToolManager public edit schemas and Responses API exposure to `write_file`, `patch_file`, and `patch_files`.
- Added centralized ToolManager legacy alias resolution for:
  - `write_to_file`
  - `enhanced_write`
  - `apply_diff`
  - `edit_with_pattern`
  - `replace_lines`
  - `insert_lines`
  - `delete_lines`
  - `multiedit_apply`
  - `multiedit`
- Updated parser edit handlers to call the canonical ToolManager names.
- Added canonical-name and alias-routing coverage for ToolManager and permission mapping.

## Verification Log

- `pytest -q tests/test_edit_contract_aliases.py tests/test_parser_edit_handlers.py tests/test_edit_lsp_reporting.py tests/tools/test_multiedit_apply.py`
  - result: `13 passed, 3 xfailed`
  - expected `xfail` cases:
    - parser/schema parity drift
    - `edit_with_pattern` search-pattern colon parsing
    - `multiedit` changed-file LSP reporting
- `pytest -q tests/tools/test_edit_service.py tests/test_edit_contract_aliases.py tests/test_parser_edit_handlers.py tests/test_edit_lsp_reporting.py tests/tools/test_multiedit_apply.py tests/test_support_diff_metadata.py`
  - result: `19 passed, 3 xfailed`
  - expected `xfail` cases unchanged:
    - parser/schema parity drift
    - `edit_with_pattern` search-pattern colon parsing
    - `multiedit` changed-file LSP reporting
- Re-ran the same suite after the ToolManager import cleanup.
  - result: `19 passed, 3 xfailed`
- `pytest -q tests/test_edit_lsp_reporting.py tests/tools/test_edit_service.py tests/tools/test_multiedit_apply.py tests/test_action_executor_subagent_events.py tests/test_edit_contract_aliases.py tests/test_parser_edit_handlers.py`
  - result: `29 passed, 2 xfailed`
  - remaining expected `xfail` cases:
    - parser/schema parity drift
    - `edit_with_pattern` search-pattern colon parsing
- `pytest -q tests/test_core_tool_mapping.py tests/test_parser_edit_handlers.py tests/test_edit_lsp_reporting.py`
  - result: `32 passed`
- `pytest -q tests/test_parser_and_tools.py tests/test_edit_contract_aliases.py tests/test_parser_edit_handlers.py tests/test_permission_engine.py tests/tools/test_edit_service.py tests/tools/test_multiedit_apply.py tests/test_core_tool_mapping.py tests/test_edit_lsp_reporting.py`
  - result: `103 passed`
  - resolved previously expected failures:
    - parser/schema drift now covered by canonical schema + alias assertions
    - `edit_with_pattern` search-pattern colon parsing now covered by passing escaped-colon and JSON tests

## Notes For Ongoing Updates

- Append every meaningful code change to the Change Log.
- Record tests run and outcomes in the Verification Log.
- Mark checklist items as they complete instead of batching updates at the end.
- If scope changes, update this file first so it stays authoritative.
