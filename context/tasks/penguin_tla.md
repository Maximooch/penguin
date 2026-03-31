# TLA+ Integration Plan for Penguin & Link

## Purpose

This document is a follow-up to `runmode-project-ituv-gap-matrix.md`. That document identified the missing plumbing required to make ITUV function as a real phase machine. This document addresses what comes after the plumbing is fixed: using TLA+ formal verification to make the VERIFY gate actually prove behavioral correctness, and eventually using verified specs as the ground truth for agent-driven codebase refactoring.

## Context

### What TLA+ Is and Why It Matters Here

TLA+ (Temporal Logic of Actions) is Leslie Lamport's formal specification language for concurrent and distributed systems. It lets you model a system as a state machine, declare invariants that must hold across all reachable states, and exhaustively explore every possible interleaving of events using the TLC model checker.

This is fundamentally different from testing. Tests check specific scenarios. TLC checks *every* scenario. For concurrent systems — which is what Penguin's multi-agent orchestration and Link's real-time collaboration layer both are — this is the difference between "it worked when I tried it" and "it works under all possible interleavings."

### What TLA+ Is Not

- Not a replacement for pytest or integration tests. Tests verify implementation behavior. TLA+ verifies design behavior.
- Not a type system or static analysis tool. It operates on an abstract model of the system, not on the source code directly.
- Not something that needs to run on every commit. Specs change when the state machine changes, not when implementation details change.

### Relationship to the Gap Matrix

The gap matrix identified these critical issues:

1. **Completion can bypass validation** — tasks reach COMPLETED without passing gates.
2. **ITUV exists in metadata, not control flow** — phases are stored but not enforced.
3. **Validation fails open** — missing evidence is treated as success.
4. **Task resolution is ambiguous** — global fallback can select wrong task.
5. **Continuous mode has drift risk** — synthetic tasks escape the work graph.

The gap matrix's fix plan (Phases 1–7) addresses the plumbing. This document addresses what the VERIFY gate should actually *do* once it has real control flow authority — and how TLA+ specs become the strongest form of verification evidence.

## Part 1: TLA+ Specs for Penguin's Own Infrastructure

These specs protect Penguin from itself. They verify the orchestration layer that all agent work flows through. This is the highest-leverage starting point because bugs here corrupt everything downstream.

### Spec 1: ITUV Workflow State Machine

**What it models:** The lifecycle of a single ITUV workflow execution — phase transitions, pause/resume/cancel signals, feedback injection, and completion conditions.

**Why it matters:** `NativeBackend._run_workflow` and `ITUVWorkflow.run` both manage this state machine with async signals checked via polling. The gap matrix already identified that `RunMode` can bypass the orchestrator and complete tasks directly. Even after the plumbing fix, the interaction between signals and phase advancement has race windows that tests won't catch.

**State variables:**

```tla
VARIABLES
  phase,          \* WorkflowPhase enum
  status,         \* WorkflowStatus enum
  paused,         \* Boolean
  cancelled,      \* Boolean
  feedback,       \* NULL or feedback payload
  phaseResults,   \* Sequence of PhaseResult records
  activePhaseOk   \* Whether current phase execution succeeded
```

**Key invariants:**

```tla
\* A workflow never advances to the next phase while paused
NeverAdvanceWhilePaused ==
  paused => phase = phase'

\* Cancel is always respected — no phase starts after cancel
CancelIsTerminal ==
  cancelled => status' \in {"cancelled"}

\* COMPLETED requires all phase results to be successful
CompletedMeansAllPassed ==
  status = "completed" =>
    \A i \in 1..Len(phaseResults) : phaseResults[i].success = TRUE

\* No phase runs twice without an explicit retry
NoDoubleExecution ==
  Len(SelectSeq(phaseResults, LAMBDA r : r.phase = phase)) <= 1

\* A workflow in WAITING_INPUT does not advance until feedback arrives
WaitingBlocksAdvancement ==
  status = "waiting_input" => phase = phase'
```

**Actions to model:**

- `AdvancePhase` — move to next ITUV phase when current succeeds
- `FailPhase` — current phase fails, trigger retry or workflow failure
- `PauseSignal` — external pause signal arrives
- `ResumeSignal` — external resume signal arrives
- `CancelSignal` — external cancel signal arrives
- `InjectFeedback` — human feedback arrives while in WAITING_INPUT
- `RetryPhase` — retry current phase after failure (with backoff)

**Expected state space:** With 7 phases × 7 statuses × 2 pause states × 2 cancel states × up to 3 retries per phase, TLC should explore ~50K–500K states. Runs in seconds.

**Maps to code:**

| Spec element | Code location |
|---|---|
| `phase` | `WorkflowState.phase` in `orchestration/state.py` |
| `status` | `WorkflowState.status` |
| `PauseSignal` | `NativeBackend.signal_workflow("pause")` |
| `AdvancePhase` | `NativeBackend._run_workflow` phase loop |
| `phaseResults` | `WorkflowState.phase_results` |

### Spec 2: Task DAG Scheduler Under Concurrent Agents

**What it models:** N agents concurrently selecting tasks from the DAG frontier, transitioning task states, and completing dependencies that unblock downstream tasks.

**Why it matters:** `AgentExecutor` runs multiple agents in parallel via asyncio with semaphore-based concurrency control. `ProjectManager.get_ready_tasks()` reads the task frontier, and `update_task_status()` writes state changes. There is no lock or compare-and-swap between the read and the write. Two agents can both read task X as ACTIVE, both call `update_task_status(X, RUNNING)`, and the second write silently overwrites the first.

The SQLite storage layer does `UPDATE tasks SET status = ? WHERE id = ?` without a `WHERE status = 'active'` guard. This is the textbook lost-update race condition.

**State variables:**

```tla
VARIABLES
  taskState,      \* Function: TaskID -> {active, running, completed, failed}
  taskDeps,       \* Function: TaskID -> Set of TaskID (dependencies)
  agentClaim,     \* Function: AgentID -> TaskID or NULL
  dagFrontier     \* Set of TaskIDs with all deps completed and status = active
```

**Key invariants:**

```tla
\* No task is claimed by two agents simultaneously
ExclusiveClaim ==
  \A a1, a2 \in Agents :
    a1 /= a2 => agentClaim[a1] /= agentClaim[a2] \/ agentClaim[a1] = NULL

\* A running task has exactly one agent
RunningHasAgent ==
  \A t \in Tasks :
    taskState[t] = "running" => \E! a \in Agents : agentClaim[a] = t

\* A task only enters running if all dependencies are completed
RunningImpliesDepsComplete ==
  \A t \in Tasks :
    taskState[t] = "running" =>
      \A d \in taskDeps[t] : taskState[d] = "completed"

\* DAG frontier is correctly computed
FrontierCorrect ==
  dagFrontier = {t \in Tasks :
    taskState[t] = "active" /\
    \A d \in taskDeps[t] : taskState[d] = "completed"}

\* Completed dependencies are never reverted while dependents are running
NoDepRegression ==
  \A t \in Tasks :
    taskState[t] = "running" =>
      \A d \in taskDeps[t] : taskState'[d] = "completed"
```

**Actions to model:**

- `SelectTask(agent)` — agent reads frontier and picks a task
- `ClaimTask(agent, task)` — agent transitions task to RUNNING
- `CompleteTask(agent, task)` — agent completes task, updates deps, recomputes frontier
- `FailTask(agent, task)` — agent fails task, returns to ACTIVE (retry) or FAILED (terminal)

**Expected state space:** With 5 tasks and 3 agents, ~10M states. With 8 tasks and 5 agents, ~100M+ states (may need symmetry reduction or constraint narrowing). The `AgentRuns` spec in the tweet screenshot explored 29M states — same ballpark.

**Maps to code:**

| Spec element | Code location |
|---|---|
| `taskState` | `Task.status` in `models.py` |
| `taskDeps` | `Task.dependencies` |
| `dagFrontier` | `ProjectManager.get_ready_tasks()` |
| `SelectTask` | `get_next_task_dag()` |
| `ClaimTask` | `update_task_status(task_id, RUNNING)` |
| `agentClaim` | Implicit in `AgentExecutor._tasks` |

**Known bug this will find:** The lost-update race on `update_task_status`. The fix is either a CAS guard (`UPDATE ... WHERE status = 'active'` with rowcount check) or a mutex in `get_next_task_dag` + `update_task_status` as an atomic operation.

### Spec 3: Link Task Identifier Sequence

**What it models:** Concurrent task creation within a project, where each task gets an identifier like `BACKEND-42` by incrementing `project.identifierSequence`.

**Why it matters:** The Link `task` router increments `identifierSequence` in application code before creating the task. Two concurrent `create` calls can read the same sequence value, both increment, and produce duplicate identifiers or a sequence gap.

**State variables:**

```tla
VARIABLES
  sequence,       \* Current identifier sequence (integer)
  createdIds,     \* Set of identifiers already assigned
  pendingCreates  \* Set of in-flight create operations with their read sequence value
```

**Key invariants:**

```tla
\* No two tasks share the same identifier
UniqueIdentifiers ==
  Cardinality(createdIds) = Len(createdIds)
  \* (i.e., no duplicates in the set)

\* Sequence is monotonically increasing
MonotonicSequence ==
  sequence' >= sequence
```

**Expected state space:** Small — 2–3 concurrent creators, sequence up to ~10. TLC runs in under a second. The value is not in scale but in proving the invariant holds (or finding the counterexample).

**Likely finding:** `UniqueIdentifiers` will be violated under concurrent creation without a database-level sequence or transaction isolation. The fix is either `SELECT ... FOR UPDATE` on the project row, a PostgreSQL `SERIAL`/`SEQUENCE`, or an application-level mutex.

## Part 2: TLA+ in the VERIFY Gate

This section describes how TLA+ model checking becomes part of the ITUV VERIFY phase for tasks that touch stateful or concurrent logic.

### Not Every Task Needs TLA+

TLA+ in VERIFY applies to tasks that modify state machines, concurrency control, message ordering, or distributed coordination. A task that adds a CSS class to a button does not need formal verification.

The decision of whether a task requires TLA+ verification is encoded in the Blueprint, not decided at runtime by the agent.

### Schema Changes

#### BlueprintItem additions

```python
@dataclass
class BlueprintItem:
    # ... existing fields ...
    
    # TLA+ verification (optional)
    tlaplus_spec: Optional[str] = None        # Path to .tla file, relative to project root
    tlaplus_invariants: List[str] = field(default_factory=list)  # Invariant names to check
    tlaplus_constants: Dict[str, str] = field(default_factory=dict)  # TLC constant overrides
```

#### Blueprint markdown syntax

```markdown
## Tasks

- [ ] <ORCH-3> Implement pause/resume signal handling {priority=high}
  - Acceptance: Paused workflow never advances phase
  - Acceptance: Resume restarts from paused phase, not from beginning  
  - Depends: <ORCH-1>, <ORCH-2>
  - TLA+: specs/ituv_workflow.tla
  - Invariants: NeverAdvanceWhilePaused, ResumePreservesPhase
  - Constants: MaxRetries=3, NumPhases=4
```

#### Task model additions

```python
@dataclass
class Task:
    # ... existing fields ...
    
    # TLA+ verification
    tlaplus_spec: Optional[str] = None
    tlaplus_invariants: List[str] = field(default_factory=list)
    tlaplus_constants: Dict[str, str] = field(default_factory=dict)
```

### VERIFY Gate Integration

The VERIFY phase in `NativeBackend._execute_verify` (and the Temporal `verify_activity`) gains a TLA+ check step:

```python
async def _execute_verify(self, state, timeout):
    artifacts = {}
    task = self._get_task(state.task_id)
    
    # --- Existing gate checks ---
    implement_passed = self._check_phase_passed(state, "implement")
    test_passed = self._check_phase_passed(state, "test")
    use_passed = self._check_phase_passed(state, "use")
    
    if not (implement_passed and test_passed and use_passed):
        artifacts["verification"] = "Prior gates failed"
        return False, artifacts
    
    # --- Acceptance criteria check ---
    ac_result = self._check_acceptance_criteria(task, state)
    artifacts["acceptance_criteria"] = ac_result
    if not ac_result["all_met"]:
        return False, artifacts
    
    # --- TLA+ model checking (if spec is defined) ---
    if task.tlaplus_spec:
        tlc_result = await self._run_tlc(
            spec_path=task.tlaplus_spec,
            invariants=task.tlaplus_invariants,
            constants=task.tlaplus_constants,
            timeout=min(timeout, 120),
        )
        artifacts["tlaplus"] = tlc_result
        
        if not tlc_result["passed"]:
            artifacts["tlaplus_counterexample"] = tlc_result.get("trace")
            return False, artifacts
    
    return True, artifacts
```

### TLC Runner

TLC is a Java application (~30MB jar). It takes a `.tla` spec and a `.cfg` config file, explores all reachable states, and reports either success or a counterexample trace.

```python
async def _run_tlc(self, spec_path, invariants, constants, timeout):
    """Run TLC model checker on a TLA+ spec.
    
    Returns:
        {
            "passed": bool,
            "states_explored": int,
            "distinct_states": int,
            "duration_sec": float,
            "invariants_checked": list[str],
            "trace": Optional[list[dict]],  # counterexample if failed
            "error": Optional[str],
        }
    """
    # Build TLC command
    cfg = self._generate_tlc_config(spec_path, invariants, constants)
    
    cmd = [
        "java", "-jar", str(self._tlc_jar_path),
        "-config", str(cfg),
        "-workers", "auto",
        "-deadlock",  # check for deadlocks
        str(spec_path),
    ]
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._workspace_path,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout
        )
        return self._parse_tlc_output(stdout.decode(), stderr.decode())
    except asyncio.TimeoutError:
        return {
            "passed": False,
            "error": f"TLC timed out after {timeout}s",
            "states_explored": 0,
            "distinct_states": 0,
            "duration_sec": timeout,
            "invariants_checked": invariants,
            "trace": None,
        }
```

### TLC Output Parsing

TLC output is structured and parseable. Key lines:

```
Model checking completed. No error has been found.
  Finished in 02s at (2025-03-30)
  29747089 states generated, 920871 distinct states found
```

Or on failure:

```
Error: Invariant NeverAdvanceWhilePaused is violated.
Error: The following sequence of states led to the violation:
  State 1: <phase = "implement", paused = FALSE, ...>
  State 2: <phase = "implement", paused = TRUE, ...>
  State 3: <phase = "test", paused = TRUE, ...>   ← violation
```

The counterexample trace is the most valuable artifact. It tells you exactly which sequence of events breaks the invariant. This trace should be stored in the task's execution record as verification evidence.

### Dependency: TLC Installation

TLC requires Java 11+ and the `tla2tools.jar`. Options for making this available:

1. **Bundled in workspace.** Download `tla2tools.jar` as a project dependency. ~30MB. No install required beyond JRE.
2. **Docker sidecar.** Run TLC in a container. Isolates Java dependency. Better for CI.
3. **Lazy check.** If `tla2tools.jar` is not present and task has `tlaplus_spec`, VERIFY fails with a clear error ("TLA+ verification required but TLC not found"). Fail closed, not fail open.

Option 3 is the right default. Option 1 or 2 for setups where TLA+ verification is routinely used.

## Part 3: Spec Authorship and Trust Boundaries

### Who Writes the Specs

There is an important trust boundary question: should the agents that implement code also write the specs that verify that code?

**Short answer: no, not for infrastructure specs.**

**Longer answer:**

| Spec category | Author | Reviewer | Rationale |
|---|---|---|---|
| Penguin orchestration (ITUV, DAG, signals) | Human or planner agent with human review | Human | These specs govern the agent runtime itself. Letting agents write their own governance specs is a trust violation. |
| Link infrastructure (chat ordering, presence, sessions) | Human or planner agent with human review | Human | Same — foundational system invariants need human sign-off. |
| Application-level features (API state machines, form workflows) | Planner agent from acceptance criteria | QA agent or human | Lower risk. Spec errors mean feature bugs, not platform corruption. |
| Regression specs (generated from bug reports) | Implementer agent | Automated (TLC pass/fail) | Spec encodes the bug as an invariant violation. If TLC passes on the fix, the bug is provably fixed. |

### Current LLM Capability for TLA+ Authorship

Claude can write basic TLA+ specs — simple state machines, invariants, basic temporal properties. It makes errors on:

- Fairness conditions (weak vs. strong fairness)
- Liveness properties (eventually something happens, vs. safety which is "bad thing never happens")
- Complex set comprehensions and function domains
- Subtle off-by-one errors in sequence indexing

For safety properties (invariants that must always hold), current LLMs are adequate with human review. For liveness properties (something must eventually happen), human authorship is strongly recommended until LLM TLA+ capability improves.

**Practical recommendation:** Start with human-authored specs for the three infrastructure specs described in Part 1. Once those are stable, experiment with agent-authored specs for application features, always with TLC as the backstop — a wrong spec that TLC explores is still safer than no spec at all, because TLC will find internal contradictions.

## Part 4: Spec-Driven Refactoring

This is the long-term play. Once TLA+ specs exist and are verified, they become the authoritative description of intended system behavior — and agents can use them to rewrite implementations with a formal correctness contract.

### The Problem With "Rewrite This Codebase"

When you tell an agent "rewrite this module," the agent has no formal definition of correctness. It has:

- README descriptions (informal, often outdated)
- Test suites (incomplete, test what was implemented, not what was intended)
- Code comments (aspirational, may not match behavior)

The result is rewrites that change behavior in subtle ways that only surface in production. This is why most large-scale AI-assisted refactors require extensive human review — the agent doesn't know what it's not supposed to break.

### How Specs Fix This

A TLA+ spec declares exactly which state transitions are legal, which invariants must hold, and what the allowed interleavings are. The agent's contract becomes:

1. Produce code that implements the state machine described in the spec.
2. The code must pass the existing test suite.
3. When the system's abstract behavior is model-checked against the spec, all invariants hold.

Condition 3 is the key addition. Tests check implementation. The spec checks design. Both must pass.

### The Link Chat Layer Case

Link's real-time chat layer is the strongest candidate for spec-driven refactoring. From the data model and router deep-dives:

**Current state:** TypeScript/tRPC backend with Drizzle ORM, PostgreSQL/Supabase storage, channels, DMs, messages, threads, agent sessions. The router deep-dives identify real concerns: identifier sequence races, shallow dependency validation, inconsistent auth patterns, heavy hydration endpoints.

**Scaling concerns:** As Link grows, the chat layer needs to handle concurrent message delivery, presence updates, channel membership mutations, and agent session lifecycle — all under concurrency. These are the exact problems that CSP (Communicating Sequential Processes) and the actor model were designed to solve, and that TLA+ was designed to verify.

**Refactor path:**

#### Step 1: Spec the invariants

Write TLA+ specs for the properties Link's chat layer must satisfy:

```tla
\* Messages within a channel are totally ordered
ChannelMessageOrder ==
  \A c \in Channels, m1, m2 \in Messages :
    (m1.channel = c /\ m2.channel = c /\ m1.sent_at < m2.sent_at) =>
      m1.sequence < m2.sequence

\* A user sees their own message after send completes
SendAck ==
  \A u \in Users, m \in Messages :
    m.author = u /\ m.status = "sent" =>
      m \in visible_messages(u, m.channel)

\* Agent messages are never delivered to a channel
\* the agent has been removed from
AgentChannelMembership ==
  \A a \in Agents, m \in Messages :
    m.author = a /\ m.status = "delivered" =>
      a \in members(m.channel)

\* Presence state is eventually consistent
\* (liveness property — use with fairness)
PresenceConvergence ==
  \A u \in Users :
    <>[]( observed_presence(u) = actual_presence(u) )
```

#### Step 2: Model-check the current design

Write a TLA+ model of how Link currently handles these operations — based on the router code and data model. Run TLC. Document which invariants hold and which are violated. This produces a concrete list of design bugs independent of any rewrite.

#### Step 3: Spec the target design

Write a new TLA+ spec for the target architecture. If the target involves Elixir/BEAM (which you've been evaluating for Link), the actor-model primitives map almost directly to TLA+ process specifications:

- Each channel is a process with a mailbox
- Messages are delivered via sends to the channel process
- Membership mutations are serialized through the channel process
- Presence is an eventually-consistent CRDT

Model-check the target spec. Prove it satisfies all invariants from Step 1. This is the "system design document" — except it's machine-verified, not a Google Doc that drifts.

#### Step 4: Agent-driven refactor

Penguin agents rewrite Link's chat backend with the contract:

- New code must pass existing integration tests.
- New code must implement the state machine described in the target spec.
- VERIFY gate runs TLC against the target spec with the implementation's behavior abstracted into the model.

The agents know what "correct" means because the spec defines it. The VERIFY gate enforces it. Human review focuses on code quality and performance, not on "did this change break message ordering" — because TLC already proved it didn't.

### Elixir/BEAM Connection

The Elixir direction for Link is particularly well-suited to this approach because:

1. BEAM's actor model provides process isolation and message-passing semantics that map cleanly to TLA+ process specifications.
2. OTP supervision trees give you fault tolerance patterns that are well-studied in formal methods literature.
3. Phoenix Channels (for WebSocket real-time) are built on the actor model, so the concurrency guarantees are structural rather than requiring careful locking.
4. The CSP (Communicating Sequential Processes) foundations that Hoare laid out in 1978 — which is what the Ashish reply in the tweet was pointing at — are directly implemented in BEAM's process model and directly specifiable in TLA+.

A verified TLA+ target spec for Link's chat layer would let you evaluate "can we implement this in TypeScript with acceptable complexity" vs. "does this naturally require actor-model primitives" with formal backing rather than vibes.

## Part 5: Execution Plan

### Phase 0: Prerequisites (from gap matrix)

Complete gap matrix Phases 1–3 first:

1. Fix completion bypass — RunMode cannot directly complete project tasks.
2. Harden ValidationManager to fail closed.
3. Add explicit ITUV phase transitions in orchestrator.

TLA+ in VERIFY is meaningless if the VERIFY gate can be bypassed.

### Phase 1: Write Infrastructure Specs (3–5 days)

Write and model-check the three specs from Part 1:

| Spec | Estimated effort | Expected state space |
|---|---|---|
| ITUV workflow state machine | 1–2 days | ~50K–500K states |
| Task DAG scheduler (concurrent agents) | 2–3 days | ~10M–100M states |
| Link identifier sequence | 0.5 day | ~1K states |

**Deliverables:**

- `specs/ituv_workflow.tla` + `specs/ituv_workflow.cfg`
- `specs/dag_scheduler.tla` + `specs/dag_scheduler.cfg`
- `specs/link_task_identifier.tla` + `specs/link_task_identifier.cfg`
- Bug report for any invariant violations found
- Fixes for confirmed bugs

**Success criteria:** TLC reports "no error found" for all invariants on all three specs. Any bugs found are fixed in the Python/TypeScript implementation.

### Phase 2: Wire TLA+ into VERIFY Gate (2–3 days)

- Add `tlaplus_spec`, `tlaplus_invariants`, `tlaplus_constants` to `BlueprintItem` and `Task`.
- Update `BlueprintParser` to parse `TLA+:`, `Invariants:`, `Constants:` lines.
- Update `sync_blueprint` to propagate TLA+ fields to tasks.
- Implement `_run_tlc` in `NativeBackend` and `verify_activity` in Temporal backend.
- Implement TLC output parser.
- Add TLC result to verification artifacts.
- Fail closed: if `tlaplus_spec` is set and TLC is not available, VERIFY fails.

**Deliverables:**

- Updated `models.py`, `blueprint_parser.py`, `manager.py`
- `penguin/orchestration/tlc_runner.py` — TLC execution and output parsing
- Updated `native.py` and `temporal/activities.py` VERIFY implementations
- Tests for the TLC runner (mock TLC output parsing)

**Success criteria:** A Blueprint with TLA+ annotations produces tasks that run TLC during VERIFY. A spec with a known invariant violation causes VERIFY to fail with a counterexample trace in the artifacts.

### Phase 3: First Self-Verification (1–2 days)

Use Penguin to verify Penguin. Create a Blueprint for the ITUV orchestration fixes from the gap matrix, with the `ituv_workflow.tla` spec as the VERIFY contract.

**Deliverables:**

- `blueprints/ituv-fix.md` — Blueprint with tasks for gap matrix Phases 1–3, with TLA+ verification on relevant tasks.
- Execution log showing ITUV phase progression with TLA+ VERIFY pass.

**Success criteria:** At least one task passes VERIFY with TLC model checking as part of the evidence. The system verifies its own orchestration changes.

### Phase 4: Link Chat Layer Specs (1–2 weeks, can overlap with Link development)

- Write invariant specs for message ordering, presence, agent session lifecycle.
- Model-check against current Link design.
- Document findings.
- Write target design spec (actor-model or otherwise).
- Model-check target spec.

**Deliverables:**

- `specs/link_chat_ordering.tla`
- `specs/link_presence.tla`
- `specs/link_agent_sessions.tla`
- Design analysis document comparing current vs. target with formal backing

### Phase 5: Spec-Driven Refactoring Pipeline (ongoing)

Once Phase 4 specs exist:

- Target specs become the contract for agent-driven refactoring.
- VERIFY gate enforces spec compliance on every task.
- Human review focuses on code quality, not behavioral correctness.

This is not a one-time project. It's an ongoing capability that compounds as the spec library grows.

## Appendix A: TLA+ Tooling Requirements

| Component | Purpose | Size | Install |
|---|---|---|---|
| `tla2tools.jar` | TLC model checker + TLA+ parser | ~30MB | Download from GitHub `tlaplus/tlaplus` releases |
| Java 11+ | TLC runtime | System dependency | `apt install openjdk-11-jre-headless` or equivalent |
| VS Code TLA+ extension | Spec authoring (optional) | ~5MB | `alygin.vscode-tlaplus` |
| TLAPS (TLA+ Proof System) | Full theorem proving (future) | ~200MB | Not needed for model checking, only for unbounded proofs |

For CI/container environments, a minimal Docker image with JRE + `tla2tools.jar` is ~150MB.

## Appendix B: TLA+ Learning Path

For getting up to speed on TLA+ authorship:

1. **LearnTLA+ (learntla.com)** — Practical tutorial, best starting point.
2. **Lamport's "Specifying Systems"** — The canonical reference. Dense but thorough.
3. **Hillel Wayne's "Practical TLA+"** — Book-length tutorial with practical examples.
4. **Lamport's video course** — Free on Microsoft Research site. Good for visual learners.

For Penguin's purposes, the core concepts needed are: state variables, Init/Next predicates, invariants, and TLC configuration. Temporal properties (liveness, fairness) are useful but not required for the initial specs — all three infrastructure specs in Part 1 use only safety properties (invariants).

## Appendix C: Relationship to Other Verification Approaches

| Approach | Strength | Penguin use case |
|---|---|---|
| TLA+ / TLC | Exhaustive state-space exploration for concurrent systems | ITUV state machine, DAG scheduler, Link chat layer |
| Lean 4 | Theorem proving for pure functions and algorithms | Blueprint parser correctness, topological sort, dependency cycle detection |
| Property-based testing (Hypothesis) | Randomized input generation for function contracts | API input validation, serialization round-trips |
| pytest | Concrete scenario testing | Unit tests, integration tests, regression tests |
| Mypy / type checking | Static type correctness | All Python code |

These are complementary, not competing. TLA+ covers the concurrency and state-machine layer that none of the others can reach. Lean 4 covers mathematical properties of pure functions. Property-based testing covers input-space exploration. pytest covers known scenarios. Type checking covers structural correctness.

The VERIFY gate should be able to invoke any of these as appropriate for the task. TLA+ is the addition with the highest marginal value for Penguin's specific architecture because the hardest bugs in multi-agent orchestration are concurrency bugs, and TLA+ is purpose-built for finding them.
