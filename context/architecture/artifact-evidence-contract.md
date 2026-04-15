# Artifact Evidence Contract

## Purpose

This document defines the contract for artifact-based task evidence and for dependency edges that use:

- `artifact_ready`

It exists so artifact-gated scheduling does not degrade into vague metadata checks or human vibes.

## Scope

This contract governs:

- how tasks declare produced artifacts
- how artifacts are identified
- how artifact evidence is persisted
- how `artifact_ready` dependency edges are evaluated
- what fail-closed behavior is required when artifact evidence is missing or invalid

This document does **not** define the full task lifecycle. That remains in:

- `context/architecture/ituv-task-state-machine-contract.md`

## Related Documents

- `context/architecture/ituv-task-state-machine-contract.md`
  - lifecycle legality, review semantics, and `status × phase` invariants
- `context/architecture/blueprint-typed-dependency-syntax-contract.md`
  - canonical Blueprint authoring syntax for typed dependency policies
- `context/architecture/runmode-project-ituv-system-map.md`
  - visual map of how artifact evidence fits into scheduling, ITUV, and project execution

## Core Rules

### Rule 1: Artifact Evidence Must Be Explicit

An `artifact_ready` dependency must declare the required artifact key.

Example:

- dependency edge requires `generated_client`
- dependency edge requires `api_smoke_report`
- dependency edge requires `ui_screenshot_login`

A dependency that merely says “some artifact should exist” is invalid.

### Rule 2: Artifact Keys Are Stable Identifiers

Artifact keys must be:

- machine-readable
- stable across runs
- scoped to task outputs, not ad hoc human descriptions

Good examples:

- `generated_client`
- `schema_snapshot`
- `smoke_test_report`
- `login_flow_screenshot`

Bad examples:

- `the file`
- `latest output`
- `proof it worked`

### Rule 3: Artifact Evidence Must Be Persisted

Artifact evidence must survive beyond the in-memory execution turn.

Valid persistence targets may include:

- task metadata
- execution records
- project-backed evidence files
- structured verification artifacts

Ephemeral assistant text alone is not sufficient evidence.

### Rule 4: Artifact Validation Must Be Machine-Checkable

An artifact only counts as ready if the system can check it mechanically.

Examples of machine-checkable evidence:

- file exists at expected path
- JSON artifact contains required keys
- command output artifact includes required success markers
- screenshot artifact file exists and is linked to the producing task
- API response artifact was captured and persisted

A human saying “looks good” is not an artifact validator.

### Rule 5: Missing or Invalid Evidence Fails Closed

If the required artifact evidence is:

- missing
- malformed
- stale
- unparseable
- not linked to the producing task

then `artifact_ready` must evaluate to **not ready**.

No fallback to “but the task is completed anyway” is allowed.

## Data Model Requirements

### Producing Task

A task that produces artifacts should expose structured artifact declarations.

Minimum shape:

```json
{
  "artifacts": [
    {
      "key": "generated_client",
      "kind": "file",
      "path": "artifacts/generated/client.json",
      "producer_task_id": "SCHEMA-1",
      "created_at": "2026-04-01T12:00:00Z",
      "valid": true
    }
  ]
}
```

### Dependency Edge

A dependency edge using `artifact_ready` must include:

- `task_id`
- `policy = artifact_ready`
- `artifact_key`

Example conceptual shape:

```json
{
  "task_id": "SCHEMA-1",
  "policy": "artifact_ready",
  "artifact_key": "generated_client"
}
```

## Initial Evaluation Semantics

Until artifact support is fully implemented, the scheduler should remain fail-closed.

That means:

- `artifact_ready` edges are recognized
- but they do not unlock dependents until real evidence validation exists

This preserves semantic honesty during incremental rollout.

## Future Implementation Requirements

When artifact-ready support is implemented for real, the scheduler must:

1. locate the producing task
2. resolve the declared artifact by `artifact_key`
3. verify the artifact exists and validates
4. confirm the artifact belongs to the declared producer
5. unlock the dependent only if validation succeeds

## Relationship to Invariant Testing

This contract should drive future property/invariant tests for:

- artifact keys must be explicit
- missing evidence never unlocks work
- malformed artifacts never unlock work
- valid artifacts unlock only the edges that requested them

## Non-Goals

This contract does not yet define:

- artifact retention lifecycle
- large binary storage strategy
- deduplicated evidence stores
- content-addressed artifact hashing
- cryptographic attestation

Those can come later if the simpler contract proves insufficient.

## Strategic Bottom Line

`artifact_ready` is allowed to exist as a typed dependency policy only because it currently fails closed.

The moment it unlocks work, it must do so on the basis of persisted, machine-checkable evidence — not optimism, memory, or chat transcript vibes.
