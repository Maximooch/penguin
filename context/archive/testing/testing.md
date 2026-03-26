# Penguin Stress/Regression Test Plan

This document outlines high‑value stress tests added to validate recent changes:

## Domains

- Tools (multiedit, patch backends, root policy)
- System (Context Window Manager trimming + borrowing)
- RunMode/Streaming (burst coalescing, mixed types, event fan‑out)
- Prompt (builder permutations)

## Running

- All tests: `uv run penguin/tests/run_all_tests.py`
- Skip heavy tests: `PENGUIN_SKIP_STRESS=1 uv run penguin/tests/run_all_tests.py`

## Environment Toggles

- `PENGUIN_PATCH_ROBUST=1` enable git apply backend when in a git repo
- `PENGUIN_PATCH_THREEWAY=1` enable 3‑way merge fallback on drift
- `PENGUIN_PATCH_SHADOW=1` apply in a shadow worktree and commit a checkpoint

## New Stress Tests (summary)

- Tools
  - `tools/stress_test_multiedit_mixed.py` – create+modify+forced‑fail → atomic rollback
  - `tools/test_multiedit_shadow.py` – shadow worktree commit (skips if git missing)
  - `tools/test_root_policy_burst.py` – burst of new‑file writes outside workspace denied
  - `tools/test_git_threeway_vs_fail.py` – drift failing vs three‑way success
  - `tools/test_patch_unicode_heavy.py` – unicode/emoji heavy patches
  - `tools/stress_test_multiedit_scale.py` – 500/1000/2000 file creation timing

- System
  - `system/stress_test_cwm_borrow_and_trim.py` – mixed images/dialog/context → trim then borrow
  - `system/stress_test_cwm_rebalance_loop.py` – repeated rebalancing safety

- RunMode
  - `runmode/stress_test_stream_burst.py` – 1000 chunk burst coalescing + finalization
  - `runmode/test_stream_mixed_types.py` – mixed reasoning/assistant/tool/error
  - `runmode/stress_test_event_fanout.py` – many handlers, many events

- Prompt
  - `prompt/stress_test_prompt_builder.py` – build all modes 100×, hash for drift

## Acceptance Criteria

- All new tests pass consistently locally (skip gracefully if prerequisites missing)
- Atomic operations roll back fully on any failure
- Streaming emits coherent chunks and a single finalization per task
- Context trim preserves SYSTEM and prunes in priority order; borrowing keeps totals within limits

## Performance Baseline (Prelim)

- Atomic multi-file apply throughput (temp workspace, macOS, fast-startup):
  - ~300–350 files/second for create-only patches (500/1000/2000 files).
- We’ll treat “300 files/sec” as a reasonable starting baseline — Penguin’s just warming up.

## Three‑Way Merge Conflicts (Robust Backend)

- Robust mode (git apply) is enabled via `PENGUIN_PATCH_ROBUST=1` inside a git repo.
- With `PENGUIN_PATCH_THREEWAY=1` Penguin attempts a 3‑way merge on context drift.
- If git reports conflicts, Penguin now:
  - Returns a structured result with `status: "conflict"`, a `conflicted` file list, and a `message`.
  - Leaves conflict markers in the worktree for the user (or a follow‑up tool) to resolve.
  - Does not rollback in this case (by design), so the conflict is visible and actionable.
- If the apply fails without conflicts, Penguin rolls back fully (atomic) and returns `status: "error"`.
