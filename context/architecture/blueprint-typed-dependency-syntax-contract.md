# Blueprint Typed Dependency Syntax Contract

## Purpose

This document defines the canonical authoring syntax for typed dependency policies in Blueprint files.

It exists so that:

- typed dependency semantics are usable by humans, not just internal data structures
- Blueprint authoring remains backward-compatible
- parser behavior is explicit instead of inferred from ad hoc examples
- future syntax improvements do not silently change dependency meaning

If implementation disagrees with this document, implementation is wrong or this document is stale. Fix one of them explicitly.

## Scope

This contract governs:

- Blueprint YAML/JSON syntax for dependency declaration
- normalized mapping from author syntax to `TaskDependency`
- backward compatibility for existing `depends_on` / `dependencies` forms
- constraints on `artifact_ready` dependency syntax

This contract does **not** define runtime lifecycle legality. That remains in:

- `context/architecture/ituv-task-state-machine-contract.md`

This contract does **not** define artifact validation semantics in full. That remains in:

- `context/architecture/artifact-evidence-contract.md`

## Related Documents

- `context/architecture/ituv-task-state-machine-contract.md`
  - lifecycle legality and runtime review/completion semantics
- `context/architecture/artifact-evidence-contract.md`
  - artifact validation rules for `artifact_ready`
- `context/architecture/runmode-project-ituv-system-map.md`
  - visual map of how Blueprint syntax flows into scheduling and ITUV execution

## Core Principle

A dependency edge is not just a task reference.

It is a tuple of:

- upstream task identity
- readiness policy
- optional artifact requirement

Therefore authoring syntax must be able to express more than:

- “Task B depends on Task A”

It must also express:

- “Task B may start when Task A is review-ready”
- “Task B may start when Task A has produced artifact X”

## Canonical Internal Shape

All supported authoring forms must normalize to this conceptual structure:

```json
{
  "task_id": "AUTH-1",
  "policy": "completion_required",
  "artifact_key": null
}
```

or, for artifact-based edges:

```json
{
  "task_id": "SCHEMA-1",
  "policy": "artifact_ready",
  "artifact_key": "generated_client"
}
```

## Supported Dependency Policies

### `completion_required`

Default policy.

Meaning:

- dependent task unlocks only when upstream task is `COMPLETED`

### `review_ready_ok`

Relaxed policy.

Meaning:

- dependent task may unlock when upstream task is:
  - `PENDING_REVIEW` with `phase=DONE`, or
  - `COMPLETED`

### `artifact_ready`

Artifact-gated policy.

Meaning:

- dependent task may unlock only when the upstream task has valid artifact evidence
- the required `artifact_key` must be explicit

## Backward Compatibility Rule

These legacy forms remain valid:

```yaml
depends_on:
  - AUTH-1
  - AUTH-2
```

```yaml
dependencies:
  - AUTH-1
  - AUTH-2
```

Both normalize to:

- `completion_required` for each listed dependency

No existing blueprint should silently change meaning because typed dependency support was added.

## Supported Authoring Forms

### Form 1: Plain String List

This is the conservative legacy/default form.

```yaml
depends_on:
  - AUTH-1
  - AUTH-2
```

Normalized as:

```yaml
dependency_specs:
  - task_id: AUTH-1
    policy: completion_required
  - task_id: AUTH-2
    policy: completion_required
```

### Form 2: Explicit Structured Dependency Specs

This is the canonical typed form.

```yaml
dependency_specs:
  - task_id: AUTH-1
    policy: completion_required
  - task_id: API-2
    policy: review_ready_ok
  - task_id: SCHEMA-1
    policy: artifact_ready
    artifact_key: generated_client
```

This form is the most explicit and should be preferred by automation and tooling.

### Form 3: Mixed Blueprint Authoring Policy

Mixed use of `depends_on` and `dependency_specs` in the same task is strongly discouraged.

Rule:

- if `dependency_specs` is present, it is the canonical source of typed dependency meaning
- `depends_on` should not be used in parallel to express different semantics for the same edge set

Implementation may normalize both, but authoring should not rely on ambiguous mixed forms.

## Required Field Rules

### For Plain Dependency Entries

Required:

- task identifier string

Implicit:

- `policy = completion_required`

Forbidden:

- artifact metadata
- inline policy syntax hidden inside task IDs

### For Explicit Dependency Specs

Required:

- `task_id`
- `policy`

Optional:

- `artifact_key` only when `policy = artifact_ready`

Forbidden:

- unknown policy values
- missing `task_id`
- `artifact_key` on policies that do not use it

## Artifact-Ready Rules

If `policy = artifact_ready`, then:

- `artifact_key` is required
- empty or omitted `artifact_key` is invalid
- evaluation semantics come from:
  - `context/architecture/artifact-evidence-contract.md`

Valid example:

```yaml
dependency_specs:
  - task_id: SCHEMA-1
    policy: artifact_ready
    artifact_key: generated_client
```

Invalid example:

```yaml
dependency_specs:
  - task_id: SCHEMA-1
    policy: artifact_ready
```

Reason:

- artifact-gated readiness without an explicit artifact key is meaningless

## Forbidden Syntax

The following forms are intentionally forbidden unless explicitly added later.

### Inline Colon Encoding

```yaml
depends_on:
  - AUTH-1:review_ready_ok
```

Forbidden because:

- ambiguous parsing
- ugly escaping rules
- hard to extend
- easy to misread as part of the task ID

### Ad Hoc Pipe Encoding

```yaml
depends_on:
  - AUTH-1|review_ready_ok
```

Forbidden for the same reason: hidden semantics in strings are brittle and hard to lint.

### Freeform English Dependency Notes

```yaml
depends_on:
  - AUTH-1 when review is ready
```

Forbidden because it is not machine-checkable.

## Markdown Blueprint Guidance

If Markdown task syntax later gains typed dependency sugar, it must still normalize into `dependency_specs`.

That future syntax should remain equivalent to the structured YAML form, not invent a second dependency model.

Until such Markdown sugar is formally added, authors should prefer structured YAML/JSON if typed dependency policies are needed.

## Normalization Rules

Parser normalization must follow this order:

1. If `dependency_specs` exists:
   - parse each entry as structured dependency data
2. Else if `depends_on` exists:
   - normalize each task ID to `completion_required`
3. Else if `dependencies` exists:
   - normalize each task ID to `completion_required`
4. Else:
   - task has no dependencies

## Validation Rules

Blueprint validation should reject:

- duplicate dependency edges to the same `task_id` with conflicting policies
- `artifact_ready` dependencies missing `artifact_key`
- dependency policies not in the allowed enum
- non-string `task_id` values
- references to missing Blueprint task IDs when full Blueprint validation runs

## Examples

### Conservative Default Example

```yaml
tasks:
  - id: AUTH-2
    title: Add login API
    depends_on:
      - AUTH-1
```

Meaning:

- `AUTH-2` waits until `AUTH-1` is `COMPLETED`

### Review-Ready Example

```yaml
tasks:
  - id: DOCS-2
    title: Write rollout docs
    dependency_specs:
      - task_id: API-3
        policy: review_ready_ok
```

Meaning:

- docs work may start once `API-3` has finished execution and reached review-ready state

### Artifact-Ready Example

```yaml
tasks:
  - id: WEB-4
    title: Integrate generated client
    dependency_specs:
      - task_id: SCHEMA-1
        policy: artifact_ready
        artifact_key: generated_client
```

Meaning:

- `WEB-4` waits for the `generated_client` artifact from `SCHEMA-1`

## Relationship to Tooling

This contract should drive:

- Blueprint parser behavior
- Blueprint linting
- sync normalization into `TaskDependency`
- future editor/tooling support
- future human-friendly Markdown sugar

## Strategic Bottom Line

The strongest system does not hide dependency policy inside clever strings.

It makes dependency meaning explicit, machine-checkable, backward-compatible, and boring.

Boring is good. Boring systems fail less.
