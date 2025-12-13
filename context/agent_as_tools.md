# Agents as Tools

*Last updated: Multi-agent config session*

---

## Overview

Sub-agents and lite agents are tools that parent Penguin agents can use. The backend infrastructure is now stable enough for basic usage.

---

## Agent Types

### Lite Agents (Single-Turn)
Particular tools similar to Claude Code's approach:
- `enhanced_read` - Read files
- `perplexity_search` - Search web
- `workspace_search` - Search codebase

These are *expected* to be single turn only.

### Sub-Agents (Multi-Turn)
More autonomous and longer running than lite agents:
- Have their own context window (isolated or shared)
- Can use a subset of tools
- Report back to parent agent
- Can be paused/resumed

---

## Available Actions

### spawn_sub_agent
Spawn a new sub-agent with optional persona.

Parameters:
- `id` (required): Unique identifier for the sub-agent
- `parent` (optional): Parent agent ID (defaults to current)
- `persona` (optional): Persona name from config.yml
- `system_prompt` (optional): Custom system prompt
- `share_session` (default: false): Share parent session
- `share_context_window` (default: false): Share parent context
- `shared_context_window_max_tokens` (optional): Context limit
- `model_config_id` (optional): Model configuration to use
- `default_tools` (optional): List of allowed tools
- `initial_prompt` (optional): First message to send

### stop_sub_agent
Pause a sub-agent. Can be resumed later.

Parameters:
- `id` (required): Agent ID to pause

### resume_sub_agent
Resume a paused sub-agent.

Parameters:
- `id` (required): Agent ID to resume

### delegate
Send a task to an existing agent.

Parameters:
- `parent`: Parent agent ID
- `child`: Target agent ID
- `content`: Task description
- `channel` (optional): Communication channel
- `metadata` (optional): Additional data

---

## Configured Personas

From config.yml:

| Persona | Model | Tools | Context Limit |
|---------|-------|-------|---------------|
| researcher | claude-haiku-4.5 | read-only (enhanced_read, search, etc.) | 50,000 |
| implementer | claude-sonnet-4 | full access (write, execute, etc.) | 80,000 |
| reviewer | claude-haiku-4.5 | read-only (enhanced_read, search) | 60,000 |

---

## CLI Integration

### Explicit Invocation
```
@researcher Analyze the codebase structure
@implementer Fix the bug in utils.py
@reviewer Review my changes
```

### Commands
```bash
penguin agent personas           # List available personas
penguin agent spawn X --persona Y  # Spawn agent with persona
penguin agent list               # List active agents
penguin agent pause X            # Pause agent
penguin agent resume X           # Resume agent
```

---

## Current Limitations

1. **No destroy action** - Agents can be paused but not destroyed (checkpointing complexity)
2. **No cross-parent transfer** - Child agents can't move between parents
3. **Tool restrictions not enforced** - default_tools is recorded but not filtered
4. **Sequential execution** - No parallel sub-agent execution yet

---

## Integration Notes

- Uses existing MessageBus for multi-agent/human communication
- Project management integration deferred for simplicity
- Parent agent delegation should be sufficient for now

---

## References

- `context/claude_code_subagents_reference.md` - Claude Code patterns
- `context/multi_agent_design_patterns.md` - Anthropic research patterns
- `context/cli_multi_agent_handling.md` - CLI implementation details
- `tests/test_sub_agents.py` - Test suite
