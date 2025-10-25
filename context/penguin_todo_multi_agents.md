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
- [x] Expose configuration surfaces for custom agent personas (per-agent prompts, default tools) so operators can register tailored agents beyond the defaults. *(Config accepts personas; CLI/TUI can list, spawn, and reconfigure agents using those templates.)*

## Phase 2 – Engine & Coordinator Enhancements
- [x] Wire `engine.run_task`, `engine.run_response`, and Run Mode to accept and schedule multiple agents via the `MultiAgentCoordinator` when policy configuration dictates. *(Engine now accepts `agent_role` and falls back to lite agents through the coordinator.)*
- [x] Implement coordinator strategies (round robin, role chain, plan-driven) as first-class, configurable options instead of demo methods only. *(Coordinator now exposes selection helpers, broadcasts, and lite-agent registration.)*
- [x] Introduce "lite" agents that can be spawned as limited-capability tools (e.g., read-only analyzers) and invoked from the coordinator or tool manager. *(Lite agents can be registered with executable handlers and triggered when no full agent is available.)*
- [x] Clarify and document how parent ↔ sub-agent conversations progress: specify the message flow (synchronous vs. event-driven), ordering guarantees, and how results are merged. *(Added MessageBus ordering guidance to sub-agent docs.)*
- [x] Fix planner → implementer handoff so file paths and behavior specs stay consistent (e.g., live_agents_demo, empty-input policy). *(Handoffs now mandate workspace-relative paths, placeholder detection, and charter updates.)*
- [x] Align planner, implementer, and QA task specs to prevent conflicting requirements within one run. *(Shared charter workflow updated; prompts require filling sections and QA refusal on placeholders.)*

### Agents-as-Tools (implemented)
- [x] ActionXML tags implemented and documented: `<spawn_sub_agent>`, `<stop_sub_agent>`, `<resume_sub_agent>`, `<delegate>`.
- [x] Lite tools available via ToolManager (grep, perplexity web search, linter) and validated.
- [x] Use `<send_message>` + `channel` for chatter; delegation events now preserve `channel` in metadata.
- [x] Sub-agent spawn defaults to isolated session/CW; initial SYSTEM/CONTEXT copied once; optional `shared_cw_max_tokens` supported.
- [x] Clamp notices recorded on parent and child with `type=cw_clamp_notice` and `clamped` flag.
- [x] No runtime permission/budget engine; record persona/model/default_tools but do not enforce.

## Phase 3 – Communication Fabric & Persistence
- [x] Decide on channel semantics for the MessageBus (rooms, topics, or per-agent queues) and implement channel identifiers if needed. *(MessageBus now supports channel-aware handlers and filtering.)*
- [x] Persist multi-agent conversation history with explicit agent_id/recipient metadata so transcripts show full agent ↔ human dialogue sequences. *(ConversationManager now records agent metadata and exposes `get_conversation_history`.)*
- [x] Provide APIs to retrieve multi-agent conversation logs, including sub-agent contributions, for CLI/TUI/Web displays. *(Core, client, and REST now expose conversation history endpoints.)*
- [x] Ensure message envelopes capture provenance for sub-agent-originated messages (who spawned them, delegated context, etc.). *(ProtocolMessage includes channel + metadata; history surfaces agent/recipient/message_type details.)*
- [x] Instrument telemetry (conversation logs, runtime diagnostics, delegation events) and surface it through a local API/dashboard that Link or future web UIs can consume; real-time dashboards trump raw CLI output when feasible. *(Telemetry collector + `/api/v1/telemetry` ready; next step is rich visualization.)*
- [x] Restore ActionXML `<send_message>` fallback when Penguin core is absent so agents can post status instead of raising.
- [x] Make apply_diff tolerate absolute paths or enforce relative ones to stop context-mismatch failures.

### Channels and Rooms (future)
- [ ] Consider IRC-style room semantics over MessageBus for broader multi-agent conversations. Document guardrails to avoid cross-parent sub-agent confusion. For now, prefer direct `target` in `<send_message>` for parent↔sub-agent coordination.

## Phase 4 – UI/UX Surfaces
- [x] Update the TUI/CLI to list registered agents and sub-agents, with commands to inspect their state and switch personas interactively. *(New `/agent …` commands and persona tables surface roster details and allow persona switching.)*
- [ ] Add multi-agent awareness to Link/web UI: visual agent roster, streaming indicators per agent, configurators for spawning/destroying agents, and access to agent-specific transcript views.
- [ ] Provide CLI scripting helpers (e.g., `penguin agent spawn`, `penguin agent list`) that wrap the new client/core APIs.

### New UX for Sub-Agent Tools
- [x] Surface sub-agent actions in CLI: spawn/stop/resume/delegate. Show paused state in rosters. Add `penguin agent list --json` for scripting.
- [ ] Mirror in TUI with pause/resume bindings and channel badges in transcript.

## Phase 5 – Full-System Scenarios & Documentation
- [ ] Document end-to-end workflows demonstrating multiple Penguins collaborating (parent + sub-agents, or several top-level agents sharing tasks).
- [ ] Cover operational guidance: monitoring, logging, and troubleshooting multi-agent runs.
- [x] Sub-agent docs updated with ActionXML, CLI references, REST pointers, and live demo script (`docs/docs/advanced/sub_agents.md`).
- [x] Context-window docs updated with clamp-notice behavior (`docs/docs/system/context-window.md`).
- [x] Multi-agent overview refreshed with REST/WebSocket notes (`docs/docs/advanced/multi_agents.md`).
- [ ] Revisit docs once API/REST helpers land so examples no longer reach into private attributes.

## Parking Lot / Open Questions
- How should we represent hierarchical conversations (parent agent coordinating several sub-agents) within persistence and analytics? Tree vs. flat log?
- What telemetry do we need to debug multi-agent handoffs (token usage per agent, context-window clamps, delegation outcomes), and how should dashboards/visualizers surface it?
- How will "lite" tool-style agents be configured—through ToolManager, coordinator templates, or separate registries?
- Should we introduce a permission/budget engine to enforce per-sub-agent tool and cost policies? For now, record user-provided defaults only; no enforcement.

## Implementation Steps (current status)

1) Agents-as-Tools core (DONE)
   - Tags wired: spawn/pause/resume/delegate; channel metadata preserved; clamp-notice mirrored.
   - Core pause/resume state with roster exposure; CLI pause/resume commands added.

2) Scripting & Tests (DONE)
   - Phase A smoke + CLI tests; Phase B scenario scripts (multi-child, persona/model, ActionXML robustness, channel provenance, context sharing/clamp, pause-during-delegate, lite tools sanity).

3) CLI polish (PARTIAL)
   - `agent list --json` shipped; Paused column added; spawn supports personas/model ids.
   - TODO: `agent delegate` helper; improved onboarding hints in help output.

4) API/REST (PARTIAL)
   - ✅ Endpoints for roster (`GET /api/v1/agents`), profile, message routing exist
   - ✅ MessageBus WebSocket streaming (`/api/v1/ws/messages`) implemented
   - ❌ **CRITICAL LIMITATION DISCOVERED**: Agents don't auto-respond to MessageBus messages
     - Messages sent via `/api/v1/messages` or `/api/v1/messages/human-reply` only route to MessageBus
     - No agent listener subscribes to MessageBus and triggers `core.process_message()`
     - For agent responses, must use `/api/v1/chat/stream` WebSocket (chat mode only)
   - TODO: Implement Agent Message Listener that:
     - Subscribes to MessageBus for each agent
     - Triggers `core.process_message()` when messages arrive
     - Publishes responses back to MessageBus
   - Add conversation history filters (by agent_id, channel, message_type).

5) TUI/Web (IN PROGRESS - 2025-10-25)
   - ✅ **Penguin CLI Multi-Agent UI Complete** (Phase 2):
     - Full UI implementation with AgentRoster, ChannelList, MessageThread, ChannelInputBar
     - Tab cycling (Ctrl+P), WebSocket connections, @mention autocomplete
     - TypeScript compilation successful, all tests passing
   - ❌ **Agent auto-response blocked by backend limitation** (see API/REST section above)
   - ⚠️ **UI displays "Under Development" notice** until backend agent listener is implemented
   - Roster with paused indicator; spawn/pause/resume actions; per-agent transcript view with channel badges.

6) Docs (IN PROGRESS)
   - Sub-agents and context-window docs updated; remaining end-to-end and operational guidance pending API/REST finalization.
