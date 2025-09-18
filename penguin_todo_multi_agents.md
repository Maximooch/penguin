# Penguin Multi-Agent & Sub-Agent TODO

This document tracks the remaining work to reach robust multi-agent and sub-agent flows across Penguin's runtime, API, and UI layers. Items are grouped by phase so we can tackle foundational plumbing before layering on UX and automation.

## Conversation History Structure: Flat vs. Tree (exploration)
- **Flat log (starting point)**: single chronological stream tagged with `agent_id` / `recipient_id`. Simpler persistence and querying; works well with existing transcript tooling; easier to render in Link/TUI “timeline” views. Downsides include extra filtering when inspecting per-agent branches and limited visibility into delegated hierarchies without additional metadata columns.
- **Tree / hierarchical view**: captures parent ↔ sub-agent relationships explicitly, making delegation trees and branch outcomes obvious. Useful for debugging nested workflows and summarising sub-runs. Comes with higher complexity (recursive storage, UI that can collapse/expand branches, harder migrations). We will adopt flat storage enriched by metadata for the initial implementation and treat tree/hierarchical logging as a future enhancement once tooling and UX demand it.

## Phase 0 – Validation & Smoke Coverage
- [x] Run full interactive Penguin sessions that spawn both additional top-level agents and sub-agents to confirm the existing plumbing behaves under real engine load.
- [x] Extend `scripts/docs_multi_and_sub_agent_examples.py` (or a new suite) to simulate more realistic multi-agent conversations, including message-bus routing and coordinator workflows. *(Initial standalone script: `scripts/phase0_multi_agent_validation.py`; latest run ✅ via `uv run phase0_multi_agent_validation.py`.)*
- [x] Add python-based integration checks (preferred over pytest for UV runs) that hit the `/api/v1/agents` REST endpoints and verify the coordinator hooks. *(Validated with `uv run phase0_agents_api_smoke.py`.)*

## Phase 1 – Client & Core API Completeness
- [x] Add `PenguinClient` helpers for agent lifecycle: `create_agent`, `list_agents`, `send_to_agent`, `create_sub_agent`, and `list_sub_agents` so docs and automation scripts do not need to reach into `client.core` internals. *(Client now exposes these helpers plus channel-aware messaging.)*
- [x] Ensure `PenguinCore` exposes symmetric APIs for destroying/unregistering agents and sub-agents, not just registration (`penguin/core.py` currently lacks a destroy helper).
- [x] Decide on and implement a public API for sub-agent creation (e.g., `PenguinCore.spawn_sub_agent(...)`), rather than relying on direct `conversation_manager.create_sub_agent` access.
- [x] Support true shared-session and shared-context-window modes in `ConversationManager.create_sub_agent`; the current implementation forces isolation regardless of the flags.
- [ ] Expose configuration surfaces for custom agent personas (per-agent prompts, default tools) so operators can register tailored agents beyond the defaults.

## Phase 2 – Engine & Coordinator Enhancements
- [x] Wire `engine.run_task`, `engine.run_response`, and Run Mode to accept and schedule multiple agents via the `MultiAgentCoordinator` when policy configuration dictates. *(Engine now accepts `agent_role` and falls back to lite agents through the coordinator.)*
- [x] Implement coordinator strategies (round robin, role chain, plan-driven) as first-class, configurable options instead of demo methods only. *(Coordinator now exposes selection helpers, broadcasts, and lite-agent registration.)*
- [x] Introduce "lite" agents that can be spawned as limited-capability tools (e.g., read-only analyzers) and invoked from the coordinator or tool manager. *(Lite agents can be registered with executable handlers and triggered when no full agent is available.)*
- [ ] Clarify and document how parent ↔ sub-agent conversations progress: specify the message flow (synchronous vs. event-driven), ordering guarantees, and how results are merged.
- [ ] Fix planner → implementer handoff so file paths and behavior specs stay consistent (e.g., live_agents_demo, empty-input policy).
- [ ] Align planner, implementer, and QA task specs to prevent conflicting requirements within one run.

## Phase 3 – Communication Fabric & Persistence
- [x] Decide on channel semantics for the MessageBus (rooms, topics, or per-agent queues) and implement channel identifiers if needed. *(MessageBus now supports channel-aware handlers and filtering.)*
- [x] Persist multi-agent conversation history with explicit agent_id/recipient metadata so transcripts show full agent ↔ human dialogue sequences. *(ConversationManager now records agent metadata and exposes `get_conversation_history`.)*
- [x] Provide APIs to retrieve multi-agent conversation logs, including sub-agent contributions, for CLI/TUI/Web displays. *(Core, client, and REST now expose conversation history endpoints.)*
- [x] Ensure message envelopes capture provenance for sub-agent-originated messages (who spawned them, delegated context, etc.). *(ProtocolMessage includes channel + metadata; history surfaces agent/recipient/message_type details.)*
- [x] Instrument telemetry (conversation logs, runtime diagnostics, delegation events) and surface it through a local API/dashboard that Link or future web UIs can consume; real-time dashboards trump raw CLI output when feasible. *(Telemetry collector + `/api/v1/telemetry` ready; next step is rich visualization.)*
- [x] Restore ActionXML `<send_message>` fallback when Penguin core is absent so agents can post status instead of raising.
- [x] Make apply_diff tolerate absolute paths or enforce relative ones to stop context-mismatch failures.

## Phase 4 – UI/UX Surfaces
- [ ] Update the TUI/CLI to list registered agents and sub-agents, with commands to inspect their state and switch personas interactively.
- [ ] Add multi-agent awareness to Link/web UI: visual agent roster, streaming indicators per agent, configurators for spawning/destroying agents, and access to agent-specific transcript views.
- [ ] Provide CLI scripting helpers (e.g., `penguin agent spawn`, `penguin agent list`) that wrap the new client/core APIs.

## Phase 5 – Full-System Scenarios & Documentation
- [ ] Document end-to-end workflows demonstrating multiple Penguins collaborating (parent + sub-agents, or several top-level agents sharing tasks).
- [ ] Cover operational guidance: monitoring, logging, and troubleshooting multi-agent runs.
- [ ] Revisit docs once API helpers land so examples no longer reach into private attributes.

## Parking Lot / Open Questions
- How should we represent hierarchical conversations (parent agent coordinating several sub-agents) within persistence and analytics? Tree vs. flat log?
- What telemetry do we need to debug multi-agent handoffs (token usage per agent, context-window clamps, delegation outcomes), and how should dashboards/visualizers surface it?
- How will "lite" tool-style agents be configured—through ToolManager, coordinator templates, or separate registries?
