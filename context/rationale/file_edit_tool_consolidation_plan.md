# File Edit Tool Consolidation Plan

## Goal

Consolidate Penguin's file edit tooling into a smaller, more reliable system with:
- one public edit contract
- one canonical result type
- one source of truth for tool docs/schemas
- correct UI/LSP file reporting
- backward-compatible migration path

## Problem Statement

The current file edit system is split across multiple overlapping layers:

- Prompt docs in `penguin/prompt_actions.py`
- Action tags and string parsers in `penguin/utils/parser.py`
- Tool schemas and dispatch in `penguin/tools/tool_manager.py`
- Concrete implementations in `penguin/tools/core/support.py`
- Batch edit handling in `penguin/tools/multiedit.py`

This creates protocol drift, duplicate logic, brittle string parsing, and inconsistent result handling.

## Confirmed Issues

### 1. Tool Name Drift
Different layers expose different names for the same capabilities.

Examples:
- Parser/public names: `enhanced_write`, `multiedit`
- ToolManager names: `write_to_file`, `multiedit_apply`

This forces translation logic across layers and makes drift likely.

### 2. Schema/Action Mismatch
Parser-exposed edit actions do not fully match ToolManager-exposed schemas.

Examples observed:
- Parser exposes `replace_lines`, `insert_lines`, `delete_lines`
- ToolManager has dispatch methods for those operations
- ToolManager does not expose matching tool schemas for all of them

### 3. Concrete LSP/UI Bug
`MULTIEDIT` is treated as file-mutating by the parser/UI refresh logic, but changed-file extraction does not handle it properly. That means multi-file edits can succeed while LSP/UI refresh receives incomplete or empty file lists.

### 4. Brittle Colon-Delimited Parsing
Current edit handlers parse payloads with ad hoc `:` splitting logic. This is unsafe for real content because colons are common in:
- diffs
- regex
- YAML
- CSS
- JSON
- URLs
- Markdown
- Windows paths

This is not a small bug. It is a protocol design flaw.

### 5. Duplicate Edit Pipelines
There are effectively multiple editing systems:
- legacy file ops
- enhanced file ops
- direct patch application
- line-based edits
- regex edits
- multiedit batching

They overlap in responsibilities such as:
- path handling
- backups
- newline/encoding handling
- diagnostics
- diff generation
- result formatting

## Target Architecture

## Public Tool Surface

Reduce the model-facing/public edit surface to four tools:

- `read_file`
- `write_file`
- `patch_file`
- `patch_files`

Everything else becomes internal implementation detail:

- `replace_lines`
- `insert_lines`
- `delete_lines`
- `edit_with_pattern`
- current `apply_diff`
- current `multiedit`

## Canonical Edit Contract

Add a new internal contract layer, e.g. `penguin/tools/editing/contracts.py`.

Suggested structures:

```python
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


EditOpType = Literal[
    "write",
    "unified_diff",
    "replace_lines",
    "insert_lines",
    "delete_lines",
    "regex_replace",
]


@dataclass
class EditOperation:
    type: EditOpType
    path: str
    payload: Dict[str, Any]
    backup: bool = True


@dataclass
class FileEditResult:
    ok: bool
    files: List[str] = field(default_factory=list)
    message: str = ""
    diagnostics: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    backup_paths: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None
```

## Canonical Responsibilities

### Parser
- parse action tags
- decode JSON payloads
- map legacy payloads to canonical requests during migration
- stop owning edit semantics

### ToolManager
- expose canonical public tool names
- manage alias mapping
- dispatch edit requests to one edit service
- return one result shape

### Edit Service
Create a dedicated edit execution layer, e.g. `penguin/tools/editing/service.py`.

It should own:
- path resolution
- backups
- encoding/newline handling
- write operations
- unified diff application
- regex replacements
- line-based edits
- multi-file batching
- result normalization into `FileEditResult`

### UI/LSP Layer
- consume `FileEditResult.files`
- consume `FileEditResult.diagnostics`
- stop reparsing raw tool params to infer changed files

## Migration Plan

### Phase 0 - Add Regression Tests Before Refactoring

Create tests that freeze current expected behavior and expose known failures.

Recommended coverage:
- parser/action parity for edit actions
- `MULTIEDIT` changed-file/LSP behavior
- `enhanced_write` payloads ending in `:true` / `:false`
- `replace_lines` payloads containing colons
- `edit_with_pattern` payloads with colons in regex/search/replacement
- schema parity between parser-visible edit actions and ToolManager schemas

Suggested test files:
- `tests/tools/test_edit_contract_aliases.py`
- `tests/utils/test_parser_edit_handlers.py`
- `tests/integration/test_edit_lsp_reporting.py`

#### Acceptance Criteria
- known drift and parser edge cases are reproducible in tests
- no consolidation starts before these tests exist

### Phase 1 - Introduce Canonical Edit Contracts

Add:
- `penguin/tools/editing/contracts.py`
- `penguin/tools/editing/service.py`

Do not delete old edit functions yet.

Wrap existing implementations behind canonical operations:
- `write_file(...) -> FileEditResult`
- `patch_file(...) -> FileEditResult`
- `patch_files(...) -> FileEditResult`

Use existing support code initially where practical:
- `apply_diff_to_file`
- `edit_file_with_pattern`
- `replace_lines`
- `insert_lines`
- `delete_lines`
- multiedit apply logic

#### Acceptance Criteria
- all edit paths return the same structured result type
- successful edits always return changed files
- result normalization is centralized

### Phase 2 - Fix UI/LSP Reporting

Refactor parser/action execution so UI/LSP refresh consumes:
- `result.files`
- `result.diagnostics`

Use raw action-param parsing only as temporary fallback.

This phase should explicitly fix the current `MULTIEDIT` changed-file bug.

#### Acceptance Criteria
- single-file and multi-file edits both report changed files correctly
- diagnostics are attached to normalized paths
- UI no longer depends primarily on parser-side string heuristics

### Phase 3 - Normalize Public Tool Names

In ToolManager, make these canonical public tools:
- `read_file`
- `write_file`
- `patch_file`
- `patch_files`

Add centralized aliases for backward compatibility:
- `enhanced_write` -> `write_file`
- `apply_diff` -> `patch_file`
- `multiedit` -> `patch_files`
- `edit_with_pattern` -> `patch_file` with `regex_replace`
- `replace_lines` -> `patch_file` with `replace_lines`
- `insert_lines` -> `patch_file` with `insert_lines`
- `delete_lines` -> `patch_file` with `delete_lines`

#### Acceptance Criteria
- one canonical public name per capability
- aliases live in one place
- parser and ToolManager stop drifting

### Phase 4 - Move to JSON-First Payloads

Replace colon-delimited edit payloads as the canonical interface.

Preferred request style:

```json
{
  "path": "src/main.py",
  "operation": {
    "type": "replace_lines",
    "start_line": 10,
    "end_line": 12,
    "new_content": "def fixed():\n    return True\n"
  },
  "backup": true
}
```

Migration strategy:
- JSON payloads become canonical
- legacy string payloads are still accepted temporarily
- legacy path emits deprecation warnings in `FileEditResult.warnings`

#### Acceptance Criteria
- JSON is the default and preferred path
- ambiguous colon parsing is no longer the primary interface
- backward compatibility remains during migration

### Phase 5 - Collapse Duplicate Implementations

After canonical dispatch is working:
- reduce `support.py` to internal primitives or wrappers
- either absorb `multiedit.py` into the new edit service or keep it only for truly unique batch patch functionality
- remove duplicated backup/path/result logic

#### Acceptance Criteria
- one execution path per edit kind
- one place for backup/path/diagnostic normalization
- no parallel public edit frameworks remain

### Phase 6 - Generate Prompt Docs From Schema

Current prompt docs are a separate contract source. That should stop.

Refactor so file-edit tool docs come from:
- ToolManager schema metadata, or
- a shared registry imported by prompt construction

#### Acceptance Criteria
- prompt docs and tool schemas derive from one source
- alias/deprecation documentation is centralized

### Phase 7 - Remove Legacy Public Edit Tools

After aliases have stabilized and migration is complete:
- remove model-facing `replace_lines`
- remove model-facing `insert_lines`
- remove model-facing `delete_lines`
- remove model-facing `edit_with_pattern`
- optionally remove transitional aliases like `enhanced_write` and `multiedit`

Keep internal operations only where they remain useful to the implementation layer.

#### Acceptance Criteria
- public edit API is reduced to the intended four tools
- internal flexibility remains without public complexity

## Concrete File Plan

### New Files
- `penguin/tools/editing/contracts.py`
- `penguin/tools/editing/service.py`

### Refactor Targets
- `penguin/utils/parser.py`
- `penguin/tools/tool_manager.py`

### Implementation Migration Targets
- `penguin/tools/core/support.py`
- `penguin/tools/multiedit.py`

### Documentation Targets
- `penguin/prompt_actions.py`
- architecture docs if needed after implementation settles

## Recommended Execution Order

1. Add regression tests
2. Introduce `FileEditResult` and canonical edit contracts
3. Fix `MULTIEDIT` changed-file/LSP reporting
4. Add canonical `write_file`, `patch_file`, `patch_files`
5. Route legacy names through centralized aliases
6. Move parser handlers to JSON-first payloads
7. Collapse duplicate implementations
8. Generate prompt docs from schema metadata
9. Remove legacy public edit tools

## Risks

### Risk: Breaking Existing Prompts or Tool Calls
Mitigation:
- explicit alias layer
- deprecation warnings
- migration tests

### Risk: Regressing Robust Patch Behavior
Mitigation:
- wrap existing patch implementations first
- refactor behavior second
- avoid rewriting diff logic blindly

### Risk: Refactor Sprawl
Mitigation:
- contract-first
- adapter-first
- delete-last

## Non-Goals

These should not be the first step:
- rewriting all of `support.py`
- renaming files for aesthetic reasons
- merging everything into one giant module
- changing prompt docs before behavior is stabilized

## Definition of Done

The consolidation is complete when:
- there is one public edit API surface
- all edit operations return one structured result type
- UI/LSP uses returned file/diagnostic data instead of reparsing raw params
- parser-visible tools and ToolManager schemas are aligned
- prompt docs are generated from or anchored to the same source of truth
- legacy aliases are either removed or explicitly maintained in one place
- multi-file edits report changed files correctly

## Immediate Next Step

Start with Phase 0 and Phase 2's concrete bug:
- add regression tests
- fix `MULTIEDIT` changed-file reporting
- then introduce the canonical result contract

That gives the highest leverage with the least risk.
