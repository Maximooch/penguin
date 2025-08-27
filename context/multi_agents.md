


<!-- 
# Phase 1 – Engine support for multiple agents
- Introduce an Agent abstraction (ID, its own ConversationManager, optional settings).
- Replace the single conversation_manager on Engine with an agents: Dict[str, Agent] registry, plus helper methods (register_agent, get_agent, run_agent_turn) so the engine can route work to different agents rather than the one hard‑coded manager it holds today


# Phase 2 – ConversationManager multi-session
- Swap the single self.conversation instance for a map agent_sessions: Dict[str, ConversationSystem].
- Provide methods create_agent_conversation, get_agent_conversation, and save_all to persist and reload per‑agent sessions.
- Names‑space session storage so each agent keeps independent history and checkpoints. This extends the current design that initializes only one ConversationSystem for all work

# Phase 3 – Message & Session data with a communication envelope
- Extend Message and Session dataclasses with fields such as agent_id, recipient_id, and message_type so every utterance is attributable and routable.
- Define a lightweight protocol inspired by frameworks like AutoGen (messages shaped as {"sender": "...", "receiver": "...", "content": "...", "type": "message|action|status"}) to allow agents and humans to exchange structured messages.
- Update serialization (to_dict, from_dict) and persistence layers to carry these new fields. The current structures lack any agent metadata

# Phase 4 – Agent‑to‑Agent and Human communication layer
- Build a MessageBus (or router) that dispatches protocol messages between agents and to human interfaces (CLI/web).
- Provide adapters for human participants—e.g., a “HumanAgent” that emits/consumes bus messages—mirroring AutoGen’s human-in-the-loop design.
- Ensure conversation transcripts can interleave messages from multiple agents and humans while preserving ordering and agent labels.

# Phase 5 – Multi-agent coordination
- Implement a MultiAgentCoordinator responsible for scheduling interactions, delegating tasks, and terminating workflows (e.g., round-robin, role-based, or plan-driven strategies).
- Integrate with the Engine’s agent registry so workflows can be kicked off via run_workflow/delegate_task APIs.
- Add hooks for advanced features like shared memory, conflict resolution, or hierarchical sub-agent spawning as needed. -->


# Multi-Agent Support Plan for Penguin

## Phase Roadmap
1. **Engine support for multiple agents**
   - Introduce an `Agent` abstraction (ID, its own `ConversationManager`, optional settings).
   - Replace the single `conversation_manager` on `Engine` with an `agents` registry and helper methods (`register_agent`, `get_agent`, `run_agent_turn`).

2. **ConversationManager multi-session**
   - Swap the single `self.conversation` instance for a map of agent sessions.
   - Provide methods to create, fetch, and persist per-agent conversations.

3. **Message & Session data with a communication envelope**
   - Extend `Message` and `Session` structures with fields such as `agent_id`, `recipient_id`, and `message_type`.
   - Define a lightweight protocol for agent-to-agent and human communication and update serialization/persistence layers.
   - Prototype the message envelope using either an AutoGen-style or JSON-RPC format so different approaches can be evaluated.

4. **Agent-to-Agent and Human communication layer**
   - Build a `MessageBus` (or router) that dispatches protocol messages between agents and human interfaces.
   - Provide adapters for human participants and ensure conversation transcripts preserve ordering and agent labels.

5. **Multi-agent coordination**
   - Implement a `MultiAgentCoordinator` responsible for scheduling interactions and delegating tasks.
   - Integrate with the Engine’s agent registry and add hooks for advanced features like shared memory or sub-agent spawning.
   - Expose coordination strategies through configuration to allow round-robin, role-based, or custom planners.

## Implementation Opportunities for Engine and Conversation Manager

1. **Engine limited to a single `ConversationManager`**
   - Introduce an `Agent` dataclass with fields for an agent ID, its own `ConversationManager`, and optional settings.
   - Replace `self.conversation_manager` with a mapping of agents.
   - Update `run_response` and `run_task` to accept an `agent_id` and route work accordingly.
   - Backward compatibility with single-agent flows is not a priority during early development.

2. **ConversationManager handles only one conversation/session**
   - Maintain `agent_sessions: Dict[str, ConversationSystem]` for independent threads.
   - Modify APIs (e.g., `process_message`, `add_context`, `add_action_result`) to accept an `agent_id`.
   - Ensure session persistence is namespaced per agent.

3. **Messages & sessions lack agent context**
   - Extend `Message` and `Session` with `agent_id` fields and update serialization.
   - Update creation points to supply agent IDs and adjust persistence logic.
   - The message layer should remain flexible so protocols can be swapped or extended without major refactors.

4. **No coordinator for multi-agent reasoning**
   - Create a `MultiAgentCoordinator` for sequencing interactions and delegating tasks.
   - Provide APIs such as `run_workflow` or `delegate_task` and integrate with the Engine’s agent registry.

## Configurability

All components should expose configuration knobs so developers can experiment with different coordination heuristics, message
protocols, and agent capabilities without deep code changes.