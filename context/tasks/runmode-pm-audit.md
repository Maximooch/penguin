# RunMode / PM Stack Audit

## Purpose

This note captures a skeptical execution-path review across the RunMode / Engine / Project stack after the `engine-run-task-thin-wrapper` refactor work. The goal is to identify where the current runtime is solid, where adapters still flatten truth, and where future cleanup should focus.

## Entry Path Reviewed

1. `penguin/cli/cli.py`
   - `main_entry(...)`
   - `_handle_run_mode(...)`
2. `penguin/core.py`
   - `start_run_mode(...)`
   - `_handle_run_mode_event`
   - `emit_ui_event(...)`
3. `penguin/run_mode.py`
   - `start(...)`
   - `start_continuous(...)`
   - clarification paths
4. `penguin/engine.py`
   - `run_task(...)`
   - `_iteration_loop(...)`
   - `_llm_step(...)`
5. `penguin/project/`
   - `task_executor.py`
   - `workflow_orchestrator.py`
   - `manager.py`
   - `validation_manager.py`
6. `penguin/web/routes.py`
   - task execution / clarification resume / serialized task payloads

## Verified Findings

### What looks solid enough right now

- `RunMode` is still the correct outer orchestration layer.
  - task resolution
  - continuous mode
  - clarification persistence / resume
  - idle / no-ready-work behavior
  - time-limit handling
- `Engine.run_task(...)` is now much closer to the right shape: setup + task-mode config + `_iteration_loop(...)` delegation.
- Web/API route truth is materially better than before.
  - task payloads preserve status/phase/dependencies/artifacts/clarification metadata
  - execute/resume routes preserve clarification truth
  - SSE/session-status truth now covers clarification, time-limit, and idle/no-ready-work

### Highest-risk areas still in the stack

- `penguin/core.py`
  - status/event bridging still relies heavily on summary strings and centralized coordination state
  - `start_run_mode(...)` cleanup/failure-path behavior deserves another pass
- `penguin/project/task_executor.py`
  - preserves `run_mode_result`, which is good
  - but still reports a coarse top-level success shape that could flatten nuanced outcomes if consumers misuse it
- `penguin/project/workflow_orchestrator.py`
  - phase-aware and improved, but still an MVP orchestrator with narrow recipe/validation behavior
- `penguin/project/validation_manager.py`
  - fail-closed is better, but VERIFY is still pytest-centric and not a mature evidence system

## Engine-Specific Review Notes

### Thin-wrapper refactor conclusion

The `run_task(...)` thin-wrapper refactor was the right move.

It reduced real duplication between:
- `run_task(...)`
- `_iteration_loop(...)`

That duplication was an Engine-vs-Engine problem, not a RunMode-vs-Engine boundary problem.

### Additional verified issues fixed during review

- task-mode stream callback contract now matches provider/runtime expectations
- `_CURRENT_ENGINE_RUN_STATE` cleanup is now broader and safer
- task completion phrases are now propagated into loop config and checked centrally
- phrase-based task completion now emits the task completion event instead of silently breaking out
- fallback task IDs are less collision-prone

## Project / PM Review Notes

### Main concern

The next trust failures are more likely to originate from `penguin/project` rather than from the newly-thinned `run_task(...)` path.

### Why

`penguin/project` still concentrates too much policy in a few places:
- `manager.py`
- `workflow_orchestrator.py`
- `task_executor.py`
- `validation_manager.py`

That does not mean those files are broken. It means they remain the most likely place for contradictions, flattening adapters, or phase/status drift.

## Suggested Follow-Up Priorities

1. **Project Orchestration Hardening**
   - especially `workflow_orchestrator.py` and `task_executor.py`
2. **Validation / VERIFY Maturity Pass**
3. **Core Runtime Decomposition Pass**
   - especially the RunMode/event/status bridge in `core.py`
4. **Engine Loop Cleanup Follow-On**
   - remaining `run_response(...)` vs `_iteration_loop(...)` divergence

## Bottom Line

The `engine-run-task-thin-wrapper` branch still looks worth shipping.

The refactor did not reveal a hidden fatal flaw in the current call chain.
But it did reinforce that the next serious reliability work should focus on:
- `penguin/project`
- `core.py` event/status bridging
- validation maturity


## Surgical Edit Checklist

### 1. `penguin/project/task_executor.py`
- [ ] Stop flattening nuanced RunMode outcomes into a coarse top-level `status="success"`.
- [ ] Derive or expose explicit runmode outcome fields (for example `run_mode_status` and `run_mode_completion_type`).
- [ ] Preserve `run_mode_result` exactly as returned.
- [ ] Add focused tests for `waiting_input`, `pending_review`, and executor error handling.

### 2. `penguin/core.py`
- [ ] Harden `start_run_mode(...)` cleanup/failure-path behavior.
- [ ] Avoid referencing partially-initialized `run_mode` state unsafely in `finally`.
- [ ] Keep `_runmode_active`, `_runmode_stream_callback`, `_ui_update_callback`, and `_continuous_mode` cleanup honest on early failure.
- [ ] Add failure-path tests if practical.

### 3. `penguin/project/workflow_orchestrator.py`
- [ ] Remove `print()` debug usage and replace with logging.
- [ ] Review phase/status transitions for flattening or misleading summaries.
- [ ] Keep `PENDING_REVIEW` / verify semantics explicit.

### 4. `penguin/project/validation_manager.py`
- [ ] Verify current fail-closed behavior still holds.
- [ ] Identify where evidence/results are still too pytest-centric.
- [ ] Defer broader VERIFY redesign unless a clearly surgical fix appears.

### 5. Follow-up discipline
- [ ] Prefer adapter-truth fixes over broad refactors.
- [ ] Add tests before widening scope.
- [ ] Treat `penguin/project` as the highest-risk area for future trust failures.
