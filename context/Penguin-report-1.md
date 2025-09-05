# Penguin Multi-Agent Communication and Coordination — Research Report (v1)

Author: Penguin Team
Date: 2025-08-30

## Purpose
This report surveys multi-agent communication and coordination approaches relevant to Penguin’s emerging multi/sub-agent architecture. It synthesizes patterns from recent LLM agent frameworks and classical MAS research, and recommends a practical roadmap for Penguin that balances capability, robustness, and simplicity.

## Summary of Findings
- No single “best” pattern fits all tasks. Successful systems blend direct routing (for low-latency task handoffs), pub-sub/blackboard (for transparency and loose coupling), and role/planner strategies (for decomposition and oversight).
- Robustness requires isolation-by-default (sessions, CWMs, tools) with well-defined sharing interfaces (partial context share, declarative memory). Safety/policy layers (spend/time caps, approvals) gate complexity.
- Human-in-the-loop remains key: humans trigger/approve spawns, inspect rationales, and arbitrate conflicts. Tooling must make provenance (agent_id, message_type) explicit.

## Contemporary Frameworks (LLM-focused)
- AutoGen (Microsoft): GroupChat, role-based agents (planner/executor), tool calling, memory. Pros: Structured multi-turn delegations. Cons: Complexity and tight coupling to framework abstractions.
- OpenAI Swarm/Function-calling patterns: Lightweight coordinator; function-call tool routing. Pros: Minimal overhead. Cons: Less opinionated; you must design policies.
- CAMEL: Role-playing agents (System prompts define roles), iterative mutual refinement. Pros: Clear role separation; social dynamics. Cons: Unpredictable long-run behavior without constraints.
- CrewAI: Task/role orchestration, hierarchical planners and tools. Pros: Pragmatic workflows. Cons: Requires configuration discipline; emergent complexity.
- AgentVerse/HuggingGPT: Central planner assigns tools/agents; a blackboard mediates. Pros: Visibility; replicable pipelines. Cons: Latency; tight integration demands.
- Anthropic Claude Code sub-agents: Delegation to specialized sub-agents and tool-like “thinking/reading” utilities. Pros: Simplicity; human approvals central. Cons: Limited published detail on routing internals.

## Patterns to Merge
- Routing layer: Envelope (agent_id, recipient_id, message_type), direct delivery + EventBus fan-out. Penguin already has MessageBus+EventBus, enabling both direct and observable flows.
- Coordinator strategies: 
  - Round-robin (fairness among same-role agents)
  - Role-based (planner→researcher→implementer)
  - Plan-driven (planner decomposes into tasks; coordinator dispatches; aggregator merges)
  - Priority queues (urgent tasks jump ahead)
- Memory sharing: Isolated CWMs; partial sharing (SYSTEM/CONTEXT) on creation; declarative shared memory (notes) via tools; snapshots/branches for lineage.
- Safety/policy: Human approval for spawn; per-agent budgets (time/tokens/tools); kill-switch on policy breach; require rationale summaries for expensive steps.

## Recommended Baseline for Penguin
- Keep envelope + MessageBus + EventBus as the core communication substrate.
- Isolation-by-default:
  - Separate sessions and CWMs; no live CWM sharing; copy SYSTEM/CONTEXT once on spawn.
- Coordinator (Phase 4):
  - Pluggable strategies (round-robin, role-chain, plan-driven later).
  - Policy hooks (approval, budgets) — implement incrementally after baseline.
  - Human commands to spawn/destroy/reactivate; coordinator records registry + roles.
- Tooling as agents: Treat a subset of tools as simple inbox handlers that return “action” messages, sharing envelope semantics.
- Observability:
  - UI labels using agent_id and message_type; EventBus “bus.message” stream; coordinator logs decisions + rationales.

## Failure Modes & Mitigations
- Message storms / runaway spawns: coordinator caps and approval gates; role quotas; cooling-off backoffs.
- Context bloat: per-agent isolation; periodic compaction tools; declarative memory instead of copying dialog.
- Hallucinated authority: require explicit “reason+plan+approval” messages before delegation; have policies validate tools and targets.
- Tool misuse: whitelists per agent; audit logs capturing action results.

## Roadmap (Next 4–8 weeks)
1. Phase 4 (Coordinator MVP)
   - Coordinator integrated in Core with CLI control.
   - Strategies: round-robin, role-chain; minimal policy adapters (approval stubs, token/time limits).
   - Human approval flow: command hooks + UI prompts.
2. Tools-as-agents pilot
   - Wrap 1–2 existing tools as message handlers (e.g., memory search → “action” response).
3. Shared memory via declarative notes
   - Central “notes” tool; agents can write/read notes; coordinator references notes instead of duplicating dialog.
4. Evaluation harness
   - Task benchmarks (coding tasks, research summaries); KPIs: success rate, cost, human interventions.

## References & Influences
- AutoGen, GroupChat/role agents (Microsoft)
- CAMEL (role-playing agents)
- CrewAI (orchestration patterns)
- AgentVerse/HuggingGPT (planner/blackboard)
- OpenAI Swarm/function-calling demos
- Anthropic Claude Code sub-agents (delegation patterns)

## Appendix: Implementation Notes in Penguin
- Envelope fields added to Message; MessageBus introduced; UI events tagged with agent_id.
- Coordinator scaffold available (spawn/destroy/register, round-robin, role-chain).
- CLI commands for messaging and coordination demos.
- Checkpoint/Autosave: event-loop safe workers; session autosaves per agent.

