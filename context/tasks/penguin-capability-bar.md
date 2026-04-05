# Penguin Capability Bar

## Purpose

This file defines the quality bar for what Penguin should be able to deliver as a software-engineering system.

It is not just a list of demos. It is a statement of what “done” means, what evidence is required, and what should distinguish Penguin from shallow AI-agent output.

Use this file to answer questions like:

- What does “senior engineer done” mean for Penguin?
- What evidence should Penguin produce before claiming a task is complete?
- What kinds of projects should Penguin eventually be able to take from spec to near-finished product?
- How does reliability-first v1 relate to formal-verification-heavy v2?

## Core Thesis

Penguin should not optimize for “looks finished.”

Penguin should optimize for:

- behavioral correctness
- explicit evidence
- resumable workflows
- trustworthy completion semantics
- reliability under ambiguity
- eventually, formal verification where it materially improves correctness

The goal is not to produce code like an overconfident intern who stopped after the first green unit test.

The goal is to produce work that is as close as possible to what a strong senior engineer would hand back:

- correct enough to trust
- tested enough to believe
- documented enough to operate
- constrained enough to review
- explicit enough to resume
- verified enough to defend

## What “Senior Engineer Done” Means

For Penguin, “done” should usually mean:

- the implementation exists
- tests relevant to the change pass
- the behavior has been exercised through a realistic usage path
- acceptance criteria are checked against explicit evidence
- failure modes are surfaced, not hidden
- task state, clarification state, and execution evidence are persisted truthfully
- public surfaces and docs are updated when behavior changes materially

It should **not** mean:

- a code diff exists
- one happy-path test passed
- the assistant sounded confident
- the implementation “probably works”
- missing evidence was silently treated as success

## Evidence Bar

### Minimum Acceptable Evidence

For most non-trivial work, Penguin should produce:

- implementation evidence
  - changed files, relevant code paths, task linkage
- test evidence
  - targeted tests first, broader suite when needed
- usage evidence
  - recipe execution, shell/API checks, or equivalent realistic exercise
- verification evidence
  - acceptance criteria checked against structured results
- state/evolution evidence
  - task phase/status transitions, clarification records, and review truth

### Higher Bar Evidence

For higher-risk or more stateful work, Penguin should increasingly produce:

- richer artifact capture
  - logs, API responses, command output, screenshots, generated files
- stronger invariants
  - property-based testing, stateful testing
- stronger design verification
  - formal specifications and model checking where appropriate

## Reliability-First V1

The current phase is reliability-first.

That means the immediate goal is to make the systems that already exist honest and dependable before layering on more advanced verification.

V1 priorities include:

- making task lifecycle state truthful
- preventing completion bypass
- making validation fail closed
- making dependency semantics explicit
- making Blueprint authoring and diagnostics reliable
- making clarification handling persistent, resumable, and honest
- making public surfaces catch up with backend truth

This is the “stop lying about done” phase.

## Formal-Verification-Heavy V2

Formal verification belongs in the next phase, not as a substitute for current reliability work.

V2 should focus on places where formal methods create unique leverage, especially:

- orchestration state machines
- dependency scheduling behavior
- clarification/waiting/resume semantics
- concurrent or distributed runtime behavior
- Link/chat/session/stateful collaboration systems

The long-term opportunity is that Penguin can make formal verification normal for appropriate work, rather than rare and exceptional.

That is one of the strongest strategic differentiators Penguin can have.

## Representative Project Categories

### 1. Spec to Near-Finished Product

Input:

- feature spec or Blueprint
- repository or scaffold
- acceptance criteria
- usage recipes

Expected output:

- working implementation
- tests
- usage evidence
- updated docs where needed
- honest task/reporting state

### 2. Heavy Refactor with Behavioral Preservation

Input:

- existing codebase
- refactor objective
- invariants and acceptance criteria
- regression expectations

Expected output:

- improved implementation
- preserved externally required behavior
- regression evidence
- explicit statement of changed vs unchanged behavior

### 3. Stateful / Workflow / Orchestration Changes

Input:

- existing workflow engine or scheduler behavior
- target invariants
- task/phase semantics
- concurrency or pause/resume expectations

Expected output:

- implementation changes
- transition/invariant coverage
- clarification/recovery handling
- eventually formal verification where justified

### 4. Artifact-Producing Build / Codegen Workflows

Input:

- schema/spec/codegen source
- expected artifact contract
- downstream consumers

Expected output:

- generated artifact
- artifact evidence
- downstream integration validation
- dependency-edge semantics that unlock only on real artifact readiness

## Anti-Goals

Penguin should not optimize for:

- maximum apparent autonomy with weak evidence
- silent fallback from ambiguity into guesses
- broad claims of completion without verification
- “works on my machine” style pseudo-validation
- feature breadth at the cost of execution truth

## Review Questions

Use these questions when evaluating whether Penguin is actually meeting the bar:

- Did the system produce explicit evidence, or just confident prose?
- Did the system test the real behavior or only the easiest path?
- Did the system preserve truthful lifecycle state?
- Did the system ask for clarification when ambiguity mattered?
- Did the system resume cleanly after clarification?
- Did the system update user-facing surfaces when backend behavior changed?
- Did the system distinguish implemented, exercised, and verified behavior?
- Would a strong senior engineer sign off on this output without embarrassment?

## Current Practical Implications

Right now, Penguin should bias toward:

- reliability over cleverness
- explicit semantics over implicit convenience
- conservative defaults over speculative autonomy
- evidence-backed completion over optimistic completion
- sharper contracts before broader surface area

## Relationship to Other Planning Files

- `context/tasks/runmode-project-ituv-gap-matrix.md`
  - strategy, sequencing, backlog, and follow-on options
- `context/tasks/runmode-project-ituv-checklist.md`
  - execution tracking for the current reliability workstream
- `context/tasks/penguin_tla.md`
  - later-stage formal verification direction
- `context/architecture/*.md`
  - canonical contracts and architecture truth

## Bottom Line

Penguin’s advantage should not be “it can generate code fast.”

That is commodity behavior.

Penguin’s advantage should be:

- it can carry a task through a truthful lifecycle
- it can produce evidence instead of vibes
- it can make strong verification normal where it matters
- it can behave less like an intern with autocomplete and more like a disciplined engineering system
