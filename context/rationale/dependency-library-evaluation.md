# Dependency Library Evaluation

## Purpose

This note evaluates candidate libraries for strengthening Penguin's task-state and dependency-policy system.

The goal is not to collect abstractions for sport. The goal is to choose the smallest set of tools that improves semantic correctness, enforcement, and test confidence.

## Current Baseline

From `pyproject.toml` and current code paths:

- `pydantic` is already a project dependency.
- `networkx` is already a project dependency and is already used for DAG/cycle logic.
- The current problems are primarily:
  - state-machine semantics
  - dependency-policy semantics
  - invariant enforcement
  - scheduler correctness

This is **not** primarily a runtime type-checking problem.

## Decision Table

| Library | Status | Recommendation | Why | Revisit Trigger |
| --- | --- | --- | --- | --- |
| `networkx` | Already in use | Keep using now | Correct tool for DAGs, cycle detection, topological reasoning, and future edge-attribute scheduling | No change needed unless graph needs exceed current DAG model |
| `pydantic` | Already in use | Use selectively | Good for schema normalization, parser validation, dependency-edge payload validation, and repair/migration boundaries | Expand if edge schemas and persisted payload validation become noisy |
| `hypothesis` | Not installed | Add next | Highest-value testing addition for transition/invariant/property testing | Add once typed dependency policies stabilize |
| `transitions` | Not installed | Defer | Useful FSM library, but current status × phase semantics are still being hardened; adding it now risks abstraction churn | Revisit if state logic becomes too fragmented to manage in plain Python |
| `python-statemachine` | Not installed | Reject for now | Cleaner class API, but weaker fit than `transitions` for dual-axis state semantics | Only revisit if architecture becomes class-centric and simpler than today |
| `beartype` | Not installed | Reject for now | Low leverage compared to invariant tests; runtime type checking will not solve semantic bugs | Revisit only if runtime type drift becomes a proven source of production defects |
| `typeguard` | Not installed | Reject for now | Same issue as `beartype`; too much ceremony for too little systems leverage | Same as above |
| `modelator` | Not installed | Defer hard | Interesting bridge for future TLA+ workflows, but semantics are still moving | Revisit after typed dependency policy and contract enforcement settle |
| `alembic` | Not installed | Reject for now | Current storage/migration pressure does not justify DB migration framework complexity | Revisit if task state moves into a more formal relational migration lifecycle |
| `pytest-xdist` | Not installed | Optional later | Nice throughput tool, not a correctness tool | Add if focused/property suites become slow enough to hurt iteration |

## Detailed Notes

### `networkx`

**Decision:** keep and extend.

Best current use cases:

- dependency DAG construction
- cycle detection
- topological ordering
- future edge-attribute-aware readiness evaluation

This is already the right graph foundation for typed dependency policies such as:

- `completion_required`
- `review_ready_ok`
- `artifact_ready`

No graph-library change is warranted.

### `pydantic`

**Decision:** use narrowly, not as a total rewrite.

Best use cases:

- typed dependency edge schema validation
- normalized blueprint parser payloads
- persisted task/document repair validation
- storage-boundary checks

Avoid using it to immediately replace every domain dataclass. That would be a refactor tax, not a leverage move.

Best pattern:

- keep current domain model where stable
- add small validation models where schema correctness matters most

### `hypothesis`

**Decision:** strongest next addition.

Why it matters:

- the system is stateful
- transition order matters
- edge-policy semantics will create combinatorial behavior that example tests miss

Best targets:

- status × phase transition sequences
- reopen / approve / fail / retry flows
- dependency unlock policy invariants
- parser normalization invariants

This is the best bridge between the written contract and real confidence before formal methods.

### `transitions`

**Decision:** defer.

Why not now:

- current status/phase model is still being clarified and enforced
- introducing an FSM framework now would force architecture around the library before semantics fully settle
- that risks replacing explicit logic problems with abstraction problems

Use plain Python + tests first. Revisit only if the state logic becomes too distributed to reason about sanely.

### `python-statemachine`

**Decision:** reject for now.

It is not obviously better than `transitions` for this codebase, and `transitions` would already be the more plausible FSM candidate.

No reason to evaluate the weaker fit first.

### `beartype` / `typeguard`

**Decision:** reject for now.

These address runtime typing confidence, but the current failure modes are mostly semantic:

- invalid transitions
- readiness policy ambiguity
- completion bypass
- review semantics drift

That is not where runtime type decorators pay off.

### `modelator`

**Decision:** defer.

This could become valuable once:

- dependency-policy semantics stop moving
- contract enforcement is stable
- TLA+ specs become part of the workflow

Before that, it is premature.

### `alembic`

**Decision:** reject for now.

The current system does not yet have the kind of relational schema migration burden that justifies Alembic overhead for this problem area.

For now, explicit repair scripts and schema-boundary validation are enough.

## Recommended Stack by Time Horizon

### Now

- Plain Python domain logic
- `networkx`
- focused `pytest`
- selective `pydantic` validation models where schemas matter

### Next

- `hypothesis`

### Later

- `transitions` if state logic becomes too fragmented
- `modelator` / TLA+ bridge after semantics stabilize

## Practical Recommendation

### Adopt Now

- Keep `networkx`
- Use `pydantic` selectively
- Plan to add `hypothesis`

### Defer

- `transitions`
- `modelator`
- `pytest-xdist`

### Reject for Now

- `python-statemachine`
- `beartype`
- `typeguard`
- `alembic`

## Strategic Bottom Line

The repo does **not** currently have a “needs more libraries” problem.

It has a:

- semantic model problem
- enforcement consistency problem
- invariant confidence problem

So the right order is:

1. finish typed dependency-policy semantics
2. centralize readiness evaluation
3. add stronger invariant/property testing (`hypothesis`)
4. only then consider heavier abstraction or formal-method bridges

If a new library does not reduce ambiguity or increase provable confidence, it is probably just another penguin-shaped object on the ice.
