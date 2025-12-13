# CLI Multi/Sub-Agent Handling

*How the CLI manages multi-agent and sub-agent interactions*

---

## Current State

### Agent Commands Available

```bash
penguin agent personas      # List configured personas from config.yml
penguin agent list          # List registered agents in current session
penguin agent spawn <id> --persona <name>  # Spawn agent with persona
penguin agent info <id>     # Show agent details
penguin agent pause <id>    # Pause an agent
penguin agent resume <id>   # Resume a paused agent
penguin agent activate <id> # Set active agent for operations
penguin agent set-persona <id> --persona <name>  # Apply persona to existing agent
```

### Explicit Agent Invocation

**@agent-name syntax** (added this session):
```
@researcher Analyze the authentication code in src/auth/
@implementer Fix the bug in utils.py line 42
@reviewer Review the changes in the last commit
```

This syntax:
1. Parses `@agent-name message`
2. Checks if agent exists (persona or registered)
3. Auto-spawns from persona if not yet registered
4. Sends message to the target agent via `core.send_to_agent()`

### Message Commands

```bash
penguin msg to-agent <agent-id> <content>  # Send message to specific agent
penguin msg to-human <content>             # Agent sends to human operator
penguin msg broadcast <content>            # Broadcast to all agents
```

---

## Session Lifecycle

### Agents Are Session-Scoped

- Agents registered via CLI exist only for the current session
- Each `penguin` invocation starts fresh
- No persistence of agent state between sessions (yet)

### Default Agent

- Every session has a `default` agent
- This is the primary agent (you, Penguin)
- Sub-agents have `parent=default` unless specified otherwise

---

## Known Limitations

### 1. No Agent Persistence
Agents don't survive between CLI invocations. Each session starts fresh.

**Workaround:** Use personas in config.yml - they're always available to spawn.

### 2. Tool Restrictions Not Enforced
The `default_tools` field in personas is recorded but not enforced at runtime.
All agents currently have access to all tools.

**TODO:** Implement tool filtering in ActionExecutor based on agent's default_tools.

### 3. Model Override May Not Apply
When spawning with a persona, the model override (e.g., haiku-4.5) should apply,
but this needs verification in actual API calls.

**TODO:** Add logging to verify which model is used per agent.

### 4. No Parallel Execution
Sub-agents run sequentially, not in parallel. The orchestrator-worker pattern
from Anthropic's research system is not yet implemented.

### 5. Context Window Isolation Needs Testing
`shared_context_window_max_tokens` is set but actual isolation behavior
needs verification.

---

## Implementation Details

### Where Agent Logic Lives

| Component | Location | Purpose |
|-----------|----------|---------|
| Persona Config | `penguin/config.py` | `AgentPersonaConfig` dataclass |
| Agent Registration | `penguin/core.py` | `register_agent()`, `create_sub_agent()` |
| Agent Roster | `penguin/core.py` | `get_agent_roster()`, `get_persona_catalog()` |
| CLI Commands | `penguin/cli/cli.py` | `agent_app` Typer commands |
| Message Routing | `penguin/core.py` | `send_to_agent()`, `send_to_human()` |
| Conversation Manager | `penguin/system/conversation_manager.py` | Agent session management |
| Coordinator | `penguin/multi/coordinator.py` | Multi-agent orchestration |

### Config Loading Fix (This Session)

Changed CLI to use `Config.load_config()` instead of raw `load_config()` dict.
This ensures `agent_personas` are properly parsed and available.

```python
# Before (broken)
_loaded_config = penguin_config_global  # raw dict, no agent_personas

# After (fixed)
_loaded_config = Config.load_config()  # Config object with agent_personas
```

---

## Future Work

### Phase 1: Make It Work
- [x] Add personas to config.example.yml
- [x] Fix CLI config loading
- [x] Add @agent-name syntax
- [x] Test sub-agent spawning
- [ ] Verify model override in API calls
- [ ] Enforce tool restrictions

### Phase 2: Make It Useful
- [ ] Agent persistence across sessions
- [ ] Parallel sub-agent execution
- [ ] Automatic delegation based on description
- [ ] Result synthesis from sub-agents

### Phase 3: Make It Robust
- [ ] Context window isolation verification
- [ ] Error recovery for failed sub-agents
- [ ] Progress tracking for long-running sub-agents
- [ ] Cost tracking per agent

---

## Testing

Run the sub-agent test suite:
```bash
uv run python tests/test_sub_agents.py
```

Tests cover:
1. Config persona loading
2. Model override (haiku-4.5 vs sonnet)
3. Tool restrictions in config
4. Context limits
5. Core persona catalog
6. Agent registration with persona
7. Sub-agent creation
8. OpenRouter API verification

---

*Last updated: During multi-agent config session*

