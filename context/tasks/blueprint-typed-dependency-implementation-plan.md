# Blueprint Typed Dependency Implementation Plan

## Purpose

This document describes the recommended implementation plan for making typed dependency policies ergonomic in Blueprint authoring.

This plan assumes the following are already true:

- typed dependency schema exists
- scheduler semantics exist
- artifact evidence contract exists
- lifecycle contract exists
- property tests and focused tests already cover core semantics

What remains is authoring UX.

## Core Goal

Make typed dependency policies easy to author in Blueprint files without creating parser debt or multiple competing truth models.

## Guiding Principles

1. **One canonical internal model**
   - all authoring forms must normalize to `TaskDependency`
2. **Backward compatibility by default**
   - existing `Depends:` behavior must remain conservative
3. **No clever string encoding**
   - avoid colon-pipes-and-prayers syntax
4. **Parser simplicity beats terseness**
   - a boring syntax that parses reliably is better than cute inline shorthand
5. **Lintability matters**
   - authors should get explicit errors for invalid policy shapes

## Current State

Today the strongest internal representation is:

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

This is good for machines and mediocre for humans.

## Recommended Path

### Phase A: Canonicalize the Authoring Contract

Use:

- `context/architecture/blueprint-typed-dependency-syntax-contract.md`

as the single source of truth.

This phase is complete when:

- author-facing syntax rules are explicit
- allowed and forbidden forms are documented
- backward compatibility is formally stated

## Phase B: Add Minimal Markdown Support for Typed Dependency Specs

### Recommended Markdown Shape

Keep the existing:

- `Depends:`

line for task readability

Add a structured:

- `Dependency Specs:`

subsection for typed overrides

Example:

```md
- [ ] <WEB-1> Integrate generated auth client
  - Depends:
    - <AUTH-3>
  - Dependency Specs:
    - task_id: <AUTH-3>
      policy: artifact_ready
      artifact_key: generated_auth_client
```

### Why This Is Recommended

Pros:

- aligns with current Markdown Blueprint style
- keeps task edge list human-readable
- keeps typed semantics explicit
- normalizes cleanly into `TaskDependency`
- easy to validate and lint
- avoids hidden syntax inside opaque strings

Cons:

- slightly more verbose
- duplicates the dependency ID once when override semantics are used

This duplication is acceptable because clarity beats parser cleverness.

## Phase C: Parser Normalization

Parser order should be:

1. parse task bullets normally
2. parse `Depends:` entries into plain dependency IDs
3. parse `Dependency Specs:` entries into structured typed edges
4. normalize into canonical dependency spec objects
5. if no typed spec exists for a listed dependency:
   - default it to `completion_required`

### Validation Rules

Reject:

- typed spec without `task_id`
- unknown `policy`
- `artifact_ready` without `artifact_key`
- conflicting duplicate specs for the same `task_id`
- typed spec references not present in the overall task graph, when full validation is available

## Phase D: Focused Tests

Add tests for:

- plain `Depends:` remains `completion_required`
- `Dependency Specs:` overrides policy correctly
- `artifact_ready` requires `artifact_key`
- duplicate conflicting dependency specs fail validation
- mixed task dependency authoring normalizes consistently

## Phase E: Property / Invariant Expansion

After parser support lands:

- extend Hypothesis coverage for normalization of typed Blueprint dependency syntax
- generate mixed dependency graphs and assert normalization invariants

This should happen after correctness exists, not before.

## Recommended Example Syntax

### Conservative Default

```md
- [ ] <AUTH-2> Review auth endpoint behavior docs
  - Depends:
    - <AUTH-1>
```

Meaning:

- unlock only when `AUTH-1` is `COMPLETED`

### Review-Ready Override

```md
- [ ] <DOCS-2> Review auth docs
  - Depends:
    - <AUTH-1>
  - Dependency Specs:
    - task_id: <AUTH-1>
      policy: review_ready_ok
```

Meaning:

- docs work may begin once `AUTH-1` is review-ready

### Artifact-Ready Override

```md
- [ ] <WEB-4> Integrate generated client
  - Depends:
    - <SCHEMA-1>
  - Dependency Specs:
    - task_id: <SCHEMA-1>
      policy: artifact_ready
      artifact_key: generated_client
```

Meaning:

- task waits on the actual artifact, not mere task completion

## Suggested Implementation Order

1. update Blueprint parser to recognize `Dependency Specs:` blocks
2. normalize to existing `TaskDependency`
3. add focused parser/normalization tests
4. add lint/validation errors
5. expand property tests

## Why This Order

Because semantics already exist.

The highest leverage work now is not more runtime complexity. It is enabling people to use the capability without touching raw internal structures.

## Concerns and Risks

### Risk 1: String-Encoded Policy Syntax

Examples to avoid:

- `AUTH-1:review_ready_ok`
- `AUTH-1|artifact_ready|generated_client`

Why avoid them:

- ambiguous parsing
- ugly escaping and edge cases
- poor lintability
- hard to extend
- encourages hidden semantics

### Risk 2: Multiple Competing Syntax Models

Do not support several equally powerful but different syntax forms at once.

That leads to:

- parser complexity
- inconsistent examples
- documentation drift

### Risk 3: Premature Artifact Validator Complexity

Blueprint syntax work should not expand artifact validation beyond the current contract unless there is a concrete usage need.

Keep syntax and evidence semantics separate.

## Recommended Decision

### Recommended Primary Route

Implement:

- `Depends:` as readable edge list
- `Dependency Specs:` as structured typed overrides

This is the recommended route.

It is not the shortest-looking syntax, but it is the strongest maintainable one.

---

# Alternatives

## Alternative A: Inline Shorthand Syntax

Example:

```md
- Depends: <AUTH-1>:review_ready_ok, <SCHEMA-1>:artifact_ready:generated_client
```

### Pros

- compact
- fast to type

### Cons

- parser debt
- ambiguous extension rules
- poor readability
- difficult linting
- encourages hidden semantics in punctuation

### Recommendation

Reject for initial implementation.

---

## Alternative B: Metadata-Only YAML Frontmatter for Dependencies

Example:

```yaml
dependency_specs:
  - task_id: AUTH-1
    policy: review_ready_ok
```

with no Markdown-level syntax support.

### Pros

- simplest parser path
- strongest structure
- zero Markdown grammar complexity

### Cons

- weak ergonomics for Markdown-first Blueprint authors
- capability stays machine-oriented
- authoring friction remains high

### Recommendation

Viable fallback if parser time is constrained, but weaker than the recommended route.

---

## Alternative C: Nested Task Metadata Block

Example:

```md
- [ ] <WEB-4> Integrate generated client
  - Metadata:
      dependency_specs:
        - task_id: <SCHEMA-1>
          policy: artifact_ready
          artifact_key: generated_client
```

### Pros

- explicit
- YAML-like

### Cons

- visually awkward
- inconsistent with the rest of the Blueprint style
- more indentation fragility

### Recommendation

Possible, but inferior to a dedicated `Dependency Specs:` section.

---

## Strategic Bottom Line

The next Blueprint step is not about adding more power.

The power already exists.

The next step is about exposing that power in a syntax that is:

- readable
- boring
- lintable
- backward-compatible
- easy to normalize
- hard to misuse

That is the implementation target.
