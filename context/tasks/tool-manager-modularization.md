# ToolManager Modularization TODO

## Objective

- Break the current `ToolManager` monolith into smaller, testable domain modules.
- Preserve current tool behavior while reducing regression blast radius and startup complexity.
- Make tool registration, permission checks, edit tools, browser tools, and memory/search tooling easier to reason about independently.

## Why This Exists

- `penguin/tools/tool_manager.py` is currently a giant stateful module (~240 KB in the repo scan).
- The file mixes registry concerns, lazy loading, permission handling, tool execution, browser support, repository actions, and file root policy.
- That kind of surface area makes regressions cheap to introduce and expensive to isolate.

## Audit Evidence

- `penguin/tools/tool_manager.py`
- `penguin/tools/registry.py`
- `penguin/tools/plugin_tool_manager.py`
- `penguin/tools/editing/`
- `tests/test_core_tool_mapping.py`
- `tests/test_parser_and_tools.py`

## Progress Snapshot

- [ ] Freeze current behavior with targeted regression tests where coverage is thin
- [ ] Define modular boundaries for tool domains
- [ ] Extract registry/schema logic from execution logic
- [ ] Extract browser and optional-dependency tooling from core tool execution
- [ ] Extract file-root and permission wiring into dedicated helpers/services
- [ ] Keep backward-compatible public tool names and dispatch behavior
- [ ] Remove dead compatibility paths only after parity is verified

## Proposed Module Boundaries

- `tool_registry` / schema metadata
- `tool_dispatch` / execution routing
- `tool_permissions` / mode + root gating
- `tool_roots` / workspace/project write resolution
- `tool_domains.browser`
- `tool_domains.memory`
- `tool_domains.tasks`
- `tool_domains.repository`

## Checklist

### Phase 1 - Baseline and Guardrails
- [ ] Map current `ToolManager` responsibilities by section/function
- [ ] Add or tighten tests around registration, dispatch, and permission-sensitive tools
- [ ] Record current startup-critical lazy-load behavior that must be preserved

### Phase 2 - Extraction
- [ ] Extract pure registry/schema helpers first
- [ ] Extract domain-specific handlers behind stable call signatures
- [ ] Introduce a narrower orchestration layer for final dispatch only
- [ ] Avoid user-facing contract changes during extraction

### Phase 3 - Cleanup
- [ ] Remove duplicated helper paths
- [ ] Trim module globals where practical
- [ ] Add architecture notes for the new tool-layer shape

## Verification Targets

- `tests/test_core_tool_mapping.py`
- `tests/test_parser_and_tools.py`
- `tests/test_permission_engine.py`
- `tests/test_execution_context.py`
- targeted browser/edit/search smoke tests

## Notes

- This is a reliability refactor, not a feature project.
- The constraint is simple: fewer places for tool behavior to hide.
