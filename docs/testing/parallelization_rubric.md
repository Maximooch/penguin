# Parallelization Testing Rubric

## Overview
This rubric provides structured scenarios for validating the multi-agent parallelization system. Tests progress from basic functionality through edge cases to performance benchmarks.

---

## 1. Regular Scenarios

### 1.1 Single Agent Baseline
**Purpose:** Verify existing functionality still works.

| Test | Command/Action | Expected Result | Pass |
|------|---------------|-----------------|------|
| Basic prompt | "What is 2+2?" | Returns "4" with reasoning | [ ] |
| Tool use | "List files in current directory" | Uses bash/glob tool, returns file list | [ ] |
| Streaming | Any prompt with streaming enabled | Content streams incrementally | [ ] |
| Context retention | Ask follow-up question | References previous context | [ ] |

### 1.2 Sub-Agent Spawning
**Purpose:** Test basic agent creation and lifecycle.

| Test | Scenario | Expected Result | Pass |
|------|----------|-----------------|------|
| Spawn single | `spawn_sub_agent(id="helper", initial_prompt="Say hello")` | Agent created, responds | [ ] |
| Spawn with shared context | `spawn_sub_agent(id="child", share_context_window=True)` | Child sees parent's conversation | [ ] |
| Spawn isolated | `spawn_sub_agent(id="isolated", share_context_window=False)` | Child has fresh context | [ ] |
| Stop agent | `stop_sub_agent(agent_id="helper")` | Agent stops, state=CANCELLED | [ ] |
| Get status | `get_agent_status(agent_id="helper")` | Returns state, result, or error | [ ] |

### 1.3 Background Execution
**Purpose:** Verify non-blocking parallel execution.

| Test | Scenario | Expected Result | Pass |
|------|----------|-----------------|------|
| Background spawn | `spawn_sub_agent(id="bg", background=True)` | Returns immediately, agent runs in background | [ ] |
| Multiple background | Spawn 3 agents with `background=True` | All run concurrently | [ ] |
| Wait for completion | `wait_for_agents(agent_ids=["a","b","c"])` | Blocks until all complete | [ ] |
| Wait with timeout | `wait_for_agents(timeout=5000)` | Returns partial results on timeout | [ ] |

### 1.4 Delegation
**Purpose:** Test task delegation patterns.

| Test | Scenario | Expected Result | Pass |
|------|----------|-----------------|------|
| Delegate task | `delegate(child_id="worker", content="Summarize X")` | Worker receives and processes task | [ ] |
| Delegate with wait | `delegate(child_id="worker", wait=True)` | Blocks until worker completes | [ ] |
| Delegate explore | `delegate_explore_task(task="Find all API endpoints")` | Creates haiku agent, returns findings | [ ] |

### 1.5 Context Sharing
**Purpose:** Validate context window sharing mechanics.

| Test | Scenario | Expected Result | Pass |
|------|----------|-----------------|------|
| Parent→child visibility | Parent adds context, child queries it | Child sees parent's messages | [ ] |
| Isolated child | Parent adds context, isolated child queries | Child does NOT see parent's messages | [ ] |
| Sync context | `sync_context(parent="default", child="isolated")` | Isolated child receives snapshot | [ ] |
| Get sharing info | `get_context_info(agent_id="child")` | Returns sharing relationships | [ ] |

---

## 2. Edge Cases

### 2.1 Concurrency Limits
**Purpose:** Test semaphore and resource limits.

| Test | Scenario | Expected Result | Pass |
|------|----------|-----------------|------|
| Exceed max concurrent | Spawn more agents than `PENGUIN_MAX_CONCURRENT_TASKS` | Extra agents queue, don't fail | [ ] |
| Rapid spawn/stop | Spawn and immediately stop 10 agents | No race conditions, clean state | [ ] |
| Concurrent same ID | Try spawning two agents with same ID | Second spawn fails gracefully | [ ] |

### 2.2 Error Handling
**Purpose:** Verify graceful degradation.

| Test | Scenario | Expected Result | Pass |
|------|----------|-----------------|------|
| Agent error | Agent encounters exception during processing | State=FAILED, error captured | [ ] |
| Stop nonexistent | `stop_sub_agent(agent_id="nonexistent")` | Returns false, no crash | [ ] |
| Wait for failed | `wait_for_agents` with one failed agent | Returns results for completed, error for failed | [ ] |
| Delegate to dead | Delegate to stopped agent | Error message, suggests respawning | [ ] |

### 2.3 State Transitions
**Purpose:** Test state machine correctness.

| Test | Scenario | Expected Result | Pass |
|------|----------|-----------------|------|
| PENDING→RUNNING | Spawn agent | Transitions through states | [ ] |
| RUNNING→PAUSED | `pause_sub_agent` while running | Agent pauses, resumes correctly | [ ] |
| PAUSED→RUNNING | `resume_sub_agent` | Agent continues from pause point | [ ] |
| Double cancel | Cancel already-cancelled agent | No error, idempotent | [ ] |

### 2.4 Streaming Edge Cases
**Purpose:** Test per-agent streaming isolation.

| Test | Scenario | Expected Result | Pass |
|------|----------|-----------------|------|
| Parallel streaming | Two agents stream simultaneously | Content doesn't interleave incorrectly | [ ] |
| Abort mid-stream | Cancel agent while streaming | Clean abort, partial content preserved | [ ] |
| Empty response | Agent returns empty | Placeholder message, not crash | [ ] |

### 2.5 Context Window Limits
**Purpose:** Test token limit enforcement.

| Test | Scenario | Expected Result | Pass |
|------|----------|-----------------|------|
| Child token limit | Create child with `shared_context_window_max_tokens=1000` | Child's context capped at 1000 | [ ] |
| Overflow handling | Fill context beyond limit | Oldest messages truncated gracefully | [ ] |
| Shared overflow | Fill shared context, check all agents | All sharing agents see same truncation | [ ] |

---

## 3. Integration Scenarios

### 3.1 Multi-Agent Workflows
**Purpose:** Test realistic coordination patterns.

| Test | Scenario | Expected Result | Pass |
|------|----------|-----------------|------|
| Fan-out/fan-in | Spawn 3 workers, delegate tasks, collect results | All results aggregated correctly | [ ] |
| Pipeline | Agent A → Agent B → Agent C | Data flows through pipeline | [ ] |
| Supervisor pattern | Main agent monitors and restarts failed workers | Failed workers respawned | [ ] |

### 3.2 Real-World Tasks

| Test | Scenario | Expected Result | Pass |
|------|----------|-----------------|------|
| Parallel file analysis | Analyze 5 files simultaneously | All files analyzed, results merged | [ ] |
| Code review delegation | Main agent delegates reviews to specialists | Each specialist reviews assigned areas | [ ] |
| Research task | Explore agent gathers info for main agent | Findings shared via context sync | [ ] |

---

## 4. Performance Benchmarks

### 4.1 Latency Metrics

| Metric | Measurement | Target | Actual |
|--------|-------------|--------|--------|
| Agent spawn time | Time from spawn call to RUNNING | <100ms | ____ms |
| Context sync time | Time to sync 10K tokens | <50ms | ____ms |
| Wait overhead | Additional time vs sequential | <10% | ___% |

### 4.2 Throughput Metrics

| Metric | Measurement | Target | Actual |
|--------|-------------|--------|--------|
| Max concurrent agents | Before degradation | 10+ | ____ |
| Messages/second | Under parallel load | 100+ | ____ |
| Memory per agent | Additional RAM per spawned agent | <50MB | ____MB |

### 4.3 Scalability Tests

| Test | Scenario | Measurement | Result |
|------|----------|-------------|--------|
| Linear scaling | 1, 2, 4, 8 parallel tasks | Speedup ratio | ____ |
| Connection pool efficiency | 100 requests, same endpoint | Connection reuse % | ___% |
| Context sharing overhead | Shared vs isolated agents | Latency difference | ____ms |

---

## 5. Challenges (Future Evals)

### 5.1 Coordination Challenges
Tasks requiring multi-agent coordination.

| Challenge | Description | Difficulty | Evaluation Criteria |
|-----------|-------------|------------|---------------------|
| Divide and Conquer | Split large task among N agents, merge results | Medium | Correct merge, no duplication |
| Consensus | Multiple agents must agree on answer | Hard | Agreement reached, correct answer |
| Dynamic Load Balancing | Redistribute work based on agent speed | Hard | Even completion times |

### 5.2 Robustness Challenges
Tasks testing failure handling.

| Challenge | Description | Difficulty | Evaluation Criteria |
|-----------|-------------|------------|---------------------|
| Chaos Monkey | Random agent failures during task | Medium | Task completes despite failures |
| Resource Starvation | Compete for limited context window | Hard | Graceful degradation |
| Deadlock Avoidance | Circular dependencies between agents | Hard | No hangs, eventual completion |

### 5.3 Efficiency Challenges
Tasks measuring resource optimization.

| Challenge | Description | Difficulty | Evaluation Criteria |
|-----------|-------------|------------|---------------------|
| Token Budget | Complete task under token limit | Medium | Task complete, budget respected |
| Speed Run | Minimize wall-clock time | Medium | Optimal parallelization |
| Memory Efficiency | Complete with minimal RAM | Hard | Peak memory under threshold |

---

## 6. Evaluation Framework (Future)

### 6.1 Automated Test Runner
```python
# Future: penguin/evals/parallelization_eval.py
class ParallelizationEval:
    scenarios: List[Scenario]
    metrics: List[Metric]

    async def run_scenario(self, scenario: Scenario) -> Result:
        """Run single scenario, collect metrics."""
        pass

    async def run_suite(self) -> EvalReport:
        """Run all scenarios, generate report."""
        pass
```

### 6.2 Metrics Collection
- Latency percentiles (p50, p95, p99)
- Error rates by category
- Resource utilization over time
- Token efficiency (tokens/task completion)

### 6.3 Regression Detection
- Compare against baseline measurements
- Alert on >10% degradation
- Track trends over time

---

## Usage

### Manual Testing
1. Start Penguin in test mode: `penguin --test`
2. Work through scenarios in order
3. Mark pass/fail in checkboxes
4. Note any unexpected behavior

### Automated Testing (Future)
```bash
# Run eval suite
penguin eval run parallelization

# Run specific category
penguin eval run parallelization --category edge-cases

# Generate report
penguin eval report parallelization --format html
```

---

## Changelog
- 2026-01-02: Initial rubric created for parallelization v1
