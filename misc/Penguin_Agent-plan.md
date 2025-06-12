# Penguin Agent – Consolidation & Evolution Plan

> Draft – {{DATE}}
>
> This document tracks the work required to turn the current assortment of *agent*-related code into a coherent, extensible **Penguin Agent Runtime** that plugs neatly into the Core ⇄ Engine refactor described in `arch_notes/simple_core_refactor.md`.

---

## 0. Guiding Principles

1. One **public namespace** – everything agent-specific lives under `penguin.agent.*`.
2. "Thin by default" – keep the happy-path (`PenguinAgent().chat()`)
   trivial; advanced orchestration is opt-in.
3. Composition > inheritance – favour small mix-ins & helper classes.
4. Container-ready – every agent can, in principle, run in-process **or**
   inside an isolated sandbox (Docker/Firecracker).
5. Stable contracts – anything exported from `penguin.agent.__all__` obeys
   sem-ver once `v0.2.0` lands.

---

## 1. Current State (June 2025)

| Location | Purpose | Status |
|----------|---------|--------|
| `penguin/agent/` | Public sync/async wrappers used by SDK | **production** |
| `penguin/penguin/agent/` | Prototype runtime (BaseAgent, schema, Launcher) | **experimental** – causes import collisions |
| `arch_notes/simple_core_refactor.md` | Target engine-centric architecture | **accepted design** |

### Problems
1. Duplicate package names confuse the import graph.
2. Prototype launcher hard-codes Core dependencies; not wired into new Engine.
3. No container execution path implemented yet.
4. No unit tests for BaseAgent lifecycle.

---

## 2. Decision – Directory Consolidation

Move useful files from **nested** package into the **public** one and delete the stub directory.

| File | From | To |
|------|------|----|
| `schema.py` | `penguin/penguin/agent/` | `penguin/agent/` |
| `base.py`   | `penguin/penguin/agent/` | `penguin/agent/` |
| `launcher.py` | `penguin/penguin/agent/` | `penguin/agent/` |

After the move, extend `penguin/agent/__init__.py`:
```python
from .schema import AgentConfig
from .base import BaseAgent
from .launcher import AgentLauncher
__all__.extend(["AgentConfig", "BaseAgent", "AgentLauncher"])
```

*Acceptance*: `pytest -q tests/test_agent_imports.py` passes.

---

## 3. Alignment with Engine Refactor

| Requirement (from core_refactor) | Agent implication |
|---------------------------------|-------------------|
| **Engine** is the single runtime loop | BaseAgent exposes a **single** async `run(prompt, context)` entry-point the Engine (or future Cognition layer) can call. |
| Stop-conditions & snapshots | BaseAgent receives `ResourceSnapshot` updates & can `await engine.snapshot()` on demand. |
| Multi-process support | `AgentLauncher` gets a `sandbox_type` switch – `inprocess` (default) → `docker` → `firecracker`. |

<!-- | **Engine** is the single runtime loop | BaseAgent must expose `plan / act / observe` coroutines the 
Engine can call. | (For now ignore the plan/act/observe thing, that needs careful handling, but 
everything else in this phase 3 can proceed) -->

Tasks:
1. Add an abstract `async run(prompt, context)` method to `BaseAgent` that returns the agent's response.  (Cognition will layer richer loops later.)
2. Expose `Engine.spawn_child()` in `AgentLauncher` for container mode.
3. Write adapter so `PenguinAgent.run_task()` simply wraps `AgentLauncher.invoke()`.

---

## 4. Phased Implementation

### Phase A – Code Moves & Import Hygiene  (½ day)
* `git mv` files
* Update all `from penguin.penguin.agent` imports
* Remove empty directory & add wheel-exclusion guard in `pyproject.toml`.

### Phase B – Engine Hooks  (1 day)
* Implement minimal `BaseAgent.run()` (raises `NotImplementedError`).
* Pass `engine` instance into agents via `AgentLauncher`.
* Unit test with stub Engine that records calls.

### Phase C – Sandbox Prototype  (1½ days)
* Use [`docker` Python SDK] to run agent image.
* Mount `${workspace}` read-only, `/tmp` rw.
* Wire basic stdin/stdout JSON RPC channel.

### Phase D – Multi-Agent Orchestrator  (2 days)
* Simple `TaskGraph` class → DAG of agent invocations.
* CLI command: `penguin agent run --graph graph.yaml`.

### Phase E – Docs & Examples  (½ day)
* Update `docs/python_api_reference.md`.
* Add `examples/agents/echo_agent.py` & `examples/graphs/dual_agent.yaml`.

---

## 5. Open Questions

1. **State sharing** – should child agents share the parent ConversationManager or own isolated ones?
2. **Tool permissions** – enforce via runtime checks (cheap) or docker capabilities (secure but heavier)?
3. **Launcher location** – keep inside library or split into `penguin.agent.launcher` vs `penguin.web.launcher`?
4. **Async entry-point** – keep two classes (`PenguinAgent` vs `PenguinAgentAsync`) or switch to single class with `.create_async()` factory?

---

## 6. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Wheels ship duplicate "agent" packages | Consolidation + `exclude-package-data` guard |
| Docker dependency balloons default install size | Keep docker extras behind `penguin-ai[sandbox]` optional dependency |
| Import cycles between Agent ↔ Engine ↔ Core | Restrict Agent code to *interfaces* only; Engine owns the loop |

---

## 7. Next Step Checklist (for PR author)

- [ ] Phase A complete, all tests green
- [ ] `make format && ruff check .` clean
- [ ] Update `CHANGELOG.md` under `Unreleased`
- [ ] Draft migration note for SDK consumers

---

### References
* Simple Core Refactor design – [`arch_notes/simple_core_refactor.md`](../arch_notes/simple_core_refactor.md)
* GitHub "quickstart writing on GitHub" guide for README updates [[GitHub Docs](https://docs.github.com/en/get-started/writing-on-github/getting-started-with-writing-and-formatting-on-github/quickstart-for-writing-on-github)].
* `mergedirs` utility can merge directories while preserving files [[GitHub repo](https://github.com/luispedro/mergedirs)].

---

*End of plan – feedback welcome before implementation begins.* 