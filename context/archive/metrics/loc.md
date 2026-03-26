# Lines of Code Reduction Plan

*Created: 2025-12-16*
*Current State: ~89,000 LOC (excluding tests)*

---

## Target

Reduce from **89k → 60k LOC** (29k reduction needed)

---

## TIER 1: Immediate Removal (Dead Code) — ~4,800 LOC

These files are not imported anywhere and can be safely deleted.

| File | LOC | Reason |
|------|-----|--------|
| `cli/cli_new.py` | 807 | Entirely commented out |
| `cli/cli_prototype_mock.py` | 718 | Prototype, not imported |
| `cli/tui_prototype_mock.py` | 787 | Prototype, not imported |
| `cli/cli_simple.py` | 161 | Not imported anywhere |
| `cli/textual_cli.py` | 279 | Only self-reference |
| `tools/core/old_memory_search.py` | 698 | Deprecated ("old" in name) |
| `tools/notes/` (entire dir) | 484 | Example files, not imported |
| `local_task/vis.py` | 254 | Visualization, not imported |
| `llm/reasoning_example.py` | 186 | Example file |
| `llm/test1.py` | 32 | Leftover test junk |
| `possible_prompt.py` | 383 | Not imported anywhere |

**Empty files to delete:**
- `memory/memory_system.py` (0 lines)
- `workspace/interface.py` (0 lines)
- `integrations/__init__.py` (0 lines)
- `prompt/__init__.py` (0 lines)
- `llm/adapters/gemini.py` (0 lines)

**Subtotal: ~4,789 LOC removable immediately**

---

## TIER 2: Move to tests/ — ~3,333 LOC

These files should be moved to the `tests/` directory for cleaner package structure.
This doesn't reduce core code but cleans up the package.

| Location | LOC | Files |
|----------|-----|-------|
| `llm/test_*.py` | ~1,672 | 7 test files |
| `cli/test_*.py` | 799 | 3 test files |
| `memory/tests/` | 359 | Test directory |
| `utils/test_*.py` | ~224 | 2 test files |
| `local_task/test_manager.py` | 279 | 1 test file |

**Files to move:**
- `penguin/llm/test_openai_adapter.py`
- `penguin/llm/test_link_integration.py`
- `penguin/llm/streaming_smoke_test.py`
- `penguin/llm/test_reasoning_tokens.py`
- `penguin/llm/test1.py`
- `penguin/llm/test_openrouter_gateway.py`
- `penguin/llm/test_litellm_gateway.py`
- `penguin/memory/tests/test_providers.py`
- `penguin/utils/test_error_handling.py`
- `penguin/utils/test_minimal.py`
- `penguin/cli/test_tui_commands.py`
- `penguin/cli/test_tui_widgets.py`
- `penguin/cli/test_tui_interactive.py`
- `penguin/local_task/test_manager.py`

---

## TIER 3: CLI Consolidation — Potential ~3,000 LOC

The CLI directory is 20,679 lines with significant overlap.

| Current | LOC | Opportunity |
|---------|-----|-------------|
| `cli.py` | 5,354 | Main CLI (keep, but audit for dead code) |
| `interface.py` | 2,394 | Consolidate with cli.py |
| `tui.py` | 3,179 | Keep if TUI is used, otherwise remove |
| `renderer.py` | 1,229 | Has duplicate filtering (already noted) |

**Estimated consolidation savings: ~2,000-3,000 LOC**

---

## TIER 4: Provider Consolidation (Bigger Effort)

### Memory Providers (~2,800 LOC total)

Multiple memory providers with similar code:
- `lance_provider.py` (740 lines)
- `sqlite_provider.py` (677 lines)
- `faiss_provider.py` (464 lines)
- `file_provider.py` (291 lines)
- `milvus_provider.py` (10 lines - stub)
- `chroma_provider.py` (93 lines)

**Opportunity:** Consolidate to 2 providers (local + vector). Potential savings: ~1,000 LOC

### LLM Adapters/Gateways (~3,000 LOC total)

- `openrouter_gateway.py` (1,188 lines)
- `litellm_gateway.py` (446 lines)
- `api_client.py` (560 lines)
- `client.py` (396 lines)
- `provider_adapters.py` (384 lines)

**Opportunity:** Some duplication in streaming logic. Potential savings: ~500-1,000 LOC

---

## Largest Files (Candidates for Refactoring)

| File | LOC | Notes |
|------|-----|-------|
| `cli/cli.py` | 5,354 | Main CLI, needs audit |
| `core.py` | 3,802 | Central logic, some dead code removed |
| `cli/tui.py` | 3,179 | TUI interface |
| `tools/tool_manager.py` | 2,998 | Tool management |
| `web/routes.py` | 2,946 | API routes |
| `cli/interface.py` | 2,394 | Could merge with cli.py |
| `local_task/manager.py` | 2,092 | Task management |

---

## Summary

| Tier | LOC Reduction | Effort | Status |
|------|---------------|--------|--------|
| Tier 1 (Dead Code) | ~4,800 | Low (just delete) | Ready |
| Tier 2 (Move Tests) | ~3,300 | Low (move files) | Ready |
| Tier 3 (CLI Consolidation) | ~3,000 | Medium | Needs planning |
| Tier 4 (Provider Consolidation) | ~2,000-4,000 | High | Future |
| **Total** | **~13,000-15,000** | | |

---

## Progress Tracking

### Tier 1 Progress

- [ ] Delete `cli/cli_new.py` (807 LOC)
- [ ] Delete `cli/cli_prototype_mock.py` (718 LOC)
- [ ] Delete `cli/tui_prototype_mock.py` (787 LOC)
- [ ] Delete `cli/cli_simple.py` (161 LOC)
- [ ] Delete `cli/textual_cli.py` (279 LOC)
- [ ] Delete `tools/core/old_memory_search.py` (698 LOC)
- [ ] Delete `tools/notes/` directory (484 LOC)
- [ ] Delete `local_task/vis.py` (254 LOC)
- [ ] Delete `llm/reasoning_example.py` (186 LOC)
- [ ] Delete `llm/test1.py` (32 LOC)
- [ ] Delete `possible_prompt.py` (383 LOC)
- [ ] Delete empty files (5 files)

### Tier 2 Progress

- [ ] Move test files to `tests/` directory
- [ ] Update imports if needed

---

## Notes

- Tier 1 + Tier 2 + Tier 3 gets codebase to ~79k LOC
- To reach 60k target, need deeper consolidation in core.py, tool_manager.py, web/routes.py
- Consider feature removal if some capabilities are unused
