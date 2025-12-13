# Penguin Codebase Improvements

A prioritized list of technical debt and architectural improvements identified during the max_tokens migration and auto-continuation bug fix session.

---

## 🔴 Critical Priority (Actually Stupid)

### 1. The Codebase is Too Big and Tangled

**Files:**
- `penguin/core.py`: 3500+ lines
- `penguin/cli/cli.py`: 5200+ lines  
- `penguin/cli/interface.py`: 2400+ lines
- `penguin/engine.py`: 1000+ lines

**Problem:** When everything is in one file, every change risks breaking something else. The token migration touched 38 files because concerns aren't separated. This slows development and breeds bugs.

**Solution:** Extract focused modules. `core.py` should be <500 lines orchestrating smaller components.

**Suggested Breakdown for core.py:**
- `core/orchestrator.py` - Main coordination logic
- `core/agent_manager.py` - Agent registration/lifecycle
- `core/message_processor.py` - Message handling
- `core/streaming.py` - Streaming logic
- `core/config_runtime.py` - Runtime configuration

**Estimated Effort:** Large (multiple sessions)

---

### 2. Inconsistent Patterns Everywhere

**Examples Found:**
- Config access: `data.get("key")` vs `getattr(obj, "key", None)` vs direct attribute
- Async patterns: Some async, some sync, some mixed in same class
- Config types: Dict-based AND dataclass AND Pydantic models
- File editing: `apply_diff` vs `multiedit` vs `enhanced_write` (3 ways to edit files)
- Logging: `logger.debug` vs `print()` vs `console.print()`

**Problem:** New code copies random patterns. Bugs hide in the inconsistency. Onboarding is painful.

**Solution:** 
1. Document the "blessed" approach for each concern
2. Create an AGENTS.md or CONTRIBUTING.md with patterns
3. Gradually refactor to consistency

**Estimated Effort:** Medium (ongoing)

---

### 3. The System Prompt is 64KB

**Location:** `penguin/prompt_actions.py`, `penguin/system_prompt.py`

**Problem:**
- ~64,000 characters / ~16,000 tokens just for instructions
- 10% of context window consumed before conversation starts
- Redundant sections (20 mentions of `finish_response` alone)
- Contradictory instructions in places

**Solution:**
1. Audit and deduplicate instructions
2. One clear instruction > five redundant ones
3. Consider dynamic prompt assembly based on task type
4. Move examples to a separate retrievable section

**Estimated Effort:** Medium (1-2 focused sessions)

**Quick Wins:**
- Remove duplicate `finish_response` documentation
- Consolidate code formatting rules (repeated 3+ times)
- Remove verbose examples that aren't referenced

---

## 🟡 Medium Priority (Annoying but Survivable)

### 4. No Clear Error Boundaries

**Pattern Found:**
```python
except Exception as e:
    logger.warning(f"Something failed: {e}")
    # continue anyway
```

**Problem:** Silent failures are worse than loud crashes. You don't know what's broken until it's really broken.

**Solution:**
1. Fail fast and loud for unexpected errors
2. Only catch specific, recoverable exceptions
3. Add error classification (recoverable vs fatal)
4. Consider a central error handler

**Files to Audit:**
- `penguin/core.py` - Many broad exception catches
- `penguin/engine.py` - Silent swallows in loop
- `penguin/llm/adapters/*.py` - API error handling

**Estimated Effort:** Medium

---

### 5. Testing is Sparse

**Current State:**
- Mostly integration tests and mocks
- No unit tests for core logic

**Missing Unit Tests For:**
- Token budget calculations (`context_window.py`)
- Action parsing (`utils/parser.py`)
- Context window trimming logic
- Config merge/override logic
- Message categorization

**Problem:** Refactoring is scary. Bugs in core logic go undetected.

**Solution:**
1. Add unit tests for math/logic parts (fast, catch regressions)
2. Start with `context_window.py` - critical and complex
3. Add test for auto-continuation (verify loop behavior)

**Estimated Effort:** Medium (ongoing)

---

### 6. Configuration is a Maze

**Config Sources:**
1. `config.yml` (user settings)
2. Environment variables
3. Dataclass defaults
4. Runtime overrides
5. CLI arguments
6. Per-agent settings
7. Model-specific settings

**Problem:** "Where does this value come from?" is unanswerable without tracing 5+ files.

**Solution:**
1. Document clear override precedence
2. Single `ConfigResolver` that logs where values came from
3. Add `--show-config-sources` debug flag
4. Reduce config sources if possible

**Estimated Effort:** Medium

---

## 🟢 Low Priority (Polish Later)

### 7. Dead Code / Commented Blocks

**Problem:** Lots of `# TODO`, `# DEPRECATED`, commented-out code blocks adding noise.

**Solution:** 
- Remove truly dead code
- Convert important TODOs to GitHub issues
- Delete commented code (git has history)

**Estimated Effort:** Small (cleanup session)

---

### 8. Inconsistent Logging

**Current State:**
- `logger.debug()` in some places
- `print()` in others
- `console.print()` (Rich) in CLI
- Some debug prints left in production code

**Solution:**
1. Use `logger` everywhere except CLI display
2. CLI display uses `console.print()` only in CLI layer
3. Remove debug `print()` statements
4. Add log level configuration

**Estimated Effort:** Small

---

### 9. Magic Numbers

**Examples Found:**
- `max_iters = 5000` (engine.py)
- `0.85` safety fraction (context_window.py)
- `200000` default context (multiple places)
- `8000` / `8192` default output tokens
- `0.05` sleep delays

**Solution:**
1. Move to named constants with docstrings
2. Centralize in a `constants.py` or config
3. Document why each value was chosen

**Estimated Effort:** Small

---

## Suggested Session Order

1. **System Prompt Trim** - High impact, relatively safe, immediate token savings
2. **Add Unit Tests for Context Window** - Safety net before refactoring
3. **Split core.py** - Biggest architectural win, enables everything else
4. **Error Boundary Audit** - Find and fix silent failures
5. **Configuration Cleanup** - Make debugging easier
6. **Pattern Documentation** - Prevent future inconsistency
7. **Polish items** - Dead code, logging, magic numbers

---

## Related Issues

- Dependabot: 26 vulnerabilities (1 critical, 5 high) - see GitHub Security tab
- Auto-continuation bug: Fixed in commit d4fe084
- Token naming: Completed in commit b66d692

---

*Created: Session with Penguin, following max_tokens migration*
*Last Updated: Same session*


---

## 🔴 Multi-Agent Infrastructure Issues

*Added after reviewing penguin/multi/coordinator.py, core.py register_agent, config.py AgentPersonaConfig, and docs*

### 1. No Agent Configuration in Default Configs

**Problem:** Neither `config.yml` nor `config.example.yml` contain any `agents:` or `personas:` section, despite the code fully supporting it.

**Evidence:**
- `config.py` lines 1418-1431 parse `agents:` or `personas:` from config
- `AgentPersonaConfig` dataclass is fully implemented (lines 1146-1230)
- Documentation in `sub_agents.md` line 82 says: *"Define them in `config.yml` under the `agents:` section"*
- But neither config file has this section

**Impact:** Users have no example of how to configure personas. The feature is invisible.

**Fix:** Add example agents section to `config.example.yml`:
```yaml
agents:
  researcher:
    description: "Research and analysis specialist"
    system_prompt: "You are a research specialist focused on gathering information."
    shared_context_window_max_tokens: 50000
    model_output_max_tokens: 8000
    permissions:
      mode: read_only
      operations: [filesystem.read, memory.read, web.search]

  implementer:
    description: "Code implementation specialist"
    permissions:
      operations: [filesystem.read, filesystem.write, process.execute]
      denied_paths: [".env", "**/*.key"]
```

**Estimated Effort:** Small (add config examples, update docs)

---

### 2. Confusing Parameter Naming Between Layers

**Problem:** Different layers use different parameter names for the same concept:

| Layer | Context Window Param | Output Token Param |
|-------|---------------------|-------------------|
| `spawn_sub_agent` action | `shared_cw_max_tokens` (web API) | `model_max_tokens` |
| `coordinator.spawn_agent` | `shared_context_window_max_tokens` | `model_output_max_tokens` |
| `core.register_agent` | `shared_context_window_max_tokens` | `model_output_max_tokens` |
| `AgentPersonaConfig` | `shared_context_window_max_tokens` | `model_output_max_tokens` |

**Evidence:**
- Web API routes.py keeps `shared_cw_max_tokens` for backward compat
- Parser.py accepts both old and new names
- Documentation mixes both naming conventions

**Impact:** Confusion when configuring agents. Users don't know which name to use.

**Fix:** 
1. Standardize on new names everywhere except web API (for backward compat)
2. Add clear deprecation notices in docs
3. Update all examples to use new names

**Estimated Effort:** Small (mostly done in token migration, needs doc cleanup)

---

### 3. No Validation or Feedback on Agent Config Errors

**Problem:** Invalid agent configurations fail silently or with cryptic errors.

**Evidence:**
- `config.py` line 1430: catches all exceptions with just a warning log
- No schema validation for agent configs
- No CLI command to validate agent configuration

**Impact:** Users don't know if their agent config is correct until runtime failure.

**Fix:**
1. Add `penguin config validate` command
2. Add JSON schema for agent configuration
3. Surface config errors clearly at startup

**Estimated Effort:** Medium

---

### 4. Unclear Relationship Between Coordinator and Core

**Problem:** Two overlapping APIs for agent management:
- `MultiAgentCoordinator.spawn_agent()` - role-based, delegation tracking
- `PenguinCore.register_agent()` - lower-level, conversation/executor setup

**Evidence:**
- `coordinator.spawn_agent()` calls `core.register_agent()` internally (line 126)
- But coordinator adds role tracking, round-robin routing, delegation records
- Users don't know which to use

**Impact:** Confusion about the right abstraction level. Potential for inconsistent state.

**Fix:**
1. Document clear use cases: Coordinator for multi-agent workflows, Core for single-agent setup
2. Consider making Coordinator the only public API for agent management
3. Add architecture diagram showing the relationship

**Estimated Effort:** Medium (mostly documentation)

---

### 5. Missing Integration Between CLI and Multi-Agent

**Problem:** CLI commands for agents exist but aren't well-integrated with config-based personas.

**Evidence:**
- `sub_agents.md` line 84 mentions `penguin agent personas` command
- But running `penguin agent --help` shows limited options
- No easy way to spawn a pre-configured persona from CLI

**Impact:** Multi-agent features are hard to discover and use.

**Fix:**
1. Add `penguin agent spawn --persona researcher` that pulls from config
2. Add `penguin agent list-personas` to show available personas
3. Add TUI integration for persona selection

**Estimated Effort:** Medium

---

### 6. Context Window Sharing Logic is Complex and Undocumented

**Problem:** The logic for sharing context windows between agents is spread across multiple files and hard to follow.

**Evidence:**
- `core.py` lines 1179-1204: Complex conditional logic for `effective_cw_cap`
- `conversation_manager.create_sub_agent()` has its own sharing logic
- No clear documentation of what happens when you set various combinations of:
  - `share_session_with`
  - `share_context_window_with`
  - `shared_context_window_max_tokens`

**Impact:** Users can't predict behavior. Easy to misconfigure.

**Fix:**
1. Create a decision matrix documenting all combinations
2. Add validation that rejects invalid combinations
3. Add debug logging showing what sharing mode was selected

**Estimated Effort:** Medium

---

### 7. No Live Demo or Tutorial for Multi-Agent

**Problem:** The only example is `scripts/phaseD_live_sub_agent_demo.py` which is hard to find and understand.

**Evidence:**
- `sub_agents.md` line 116 references the script
- No step-by-step tutorial
- No simple "hello world" multi-agent example

**Impact:** High barrier to entry for multi-agent features.

**Fix:**
1. Add `docs/docs/tutorials/multi_agent_quickstart.md`
2. Create a simpler example script
3. Add interactive CLI walkthrough

**Estimated Effort:** Medium

---

## Recommended Multi-Agent Session Order

1. **Add agents section to config.example.yml** - Immediate visibility
2. **Create multi-agent quickstart tutorial** - Lower barrier to entry
3. **Add `penguin agent spawn --persona` CLI** - Easy experimentation
4. **Document context window sharing matrix** - Reduce confusion
5. **Add config validation command** - Catch errors early



---



---

## 📘 Reference: Claude Code Sub-Agent Patterns

*See `context/claude_code_subagents_reference.md` for full documentation*

### Config Format (What Claude Code Uses)

```yaml
# .claude/agents/code-reviewer.yaml
name: code-reviewer
description: Reviews code for quality, security, and best practices
model: claude-haiku-3-20240307  # Optional: cheaper/faster model
tools:  # Optional: restrict available tools
  - Read
  - Glob
  - Grep
  - LS
prompt: |
  You are an expert code reviewer...
```

### What Penguin Already Has vs. Needs

| Feature | Claude Code | Penguin Status |
|---------|-------------|----------------|
| YAML config | `.claude/agents/*.yaml` | ✅ `config.yml` agents section (code exists, no examples) |
| Required fields | name, description, prompt | ✅ `AgentPersonaConfig` has these |
| Model override | `model: claude-haiku-3` | ✅ `AgentModelSettings` supports this |
| Tool restrictions | `tools: [Read, Glob]` | ✅ `default_tools` field exists |
| Explicit invocation | `@agent-name task` | ❌ Not implemented |
| Auto delegation | Based on description | ❌ Not implemented |
| Interactive management | `/agents` command | ❌ Partial (`penguin agent` exists but limited) |
| Two scopes | Project + User level | ❌ Only project level |

### Key Implementation Gaps

1. **No config examples** - The `agents:` section works but nobody knows about it
2. **No model specification in examples** - Users don't know they can use cheaper models
3. **No `@agent-name` syntax** - Can't explicitly invoke a persona
4. **No automatic delegation** - Agent must be manually spawned, no "Claude decides" mode


## 🔵 Future: Multi-Agent Design Pattern Implementation

*To be tackled AFTER resolving the config and infrastructure issues above*

**Reference:** See `context/multi_agent_design_patterns.md` for full source material from:
- Anthropic: Effective Context Engineering for AI Agents
- Anthropic: Building a Multi-Agent Research System  
- Manus: Wide Research

---

### 1. Implement Orchestrator-Worker Pattern

**Goal:** Enable a lead agent to spawn specialized subagents for specific tasks.

**From Anthropic:** *"Our Research system uses a multi-agent architecture with an orchestrator-worker pattern, where a lead agent coordinates the process while delegating to specialized subagents that operate in parallel."*

**Implementation:**
- [ ] Define clear delegation protocol: objective, output format, tool guidance, task boundaries
- [ ] Add `delegate_research` and `delegate_implementation` high-level actions
- [ ] Create default personas: `researcher`, `implementer`, `reviewer`
- [ ] Implement result synthesis - lead agent collects subagent outputs

**Estimated Effort:** Large

---

### 2. Add Effort Scaling Heuristics

**Goal:** Teach agents to scale resources based on task complexity.

**From Anthropic:** *"Simple fact-finding requires just 1 agent with 3-10 tool calls, direct comparisons might need 2-4 subagents with 10-15 calls each, and complex research might use more than 10 subagents."*

**Implementation:**
- [ ] Add task complexity classification (simple/medium/complex)
- [ ] Embed scaling rules in system prompt or persona configs
- [ ] Define resource budgets per complexity level:
  - Simple: 1 agent, 3-10 tool calls, 5K output tokens
  - Medium: 2-4 subagents, 10-15 calls each, 15K output tokens
  - Complex: 5+ subagents, divided responsibilities, 50K+ output tokens
- [ ] Add guardrails to prevent over-spawning (was a failure mode for Anthropic)

**Estimated Effort:** Medium

---

### 3. Implement Memory Persistence for Long-Horizon Tasks

**Goal:** Prevent context overflow by summarizing and persisting completed work.

**From Anthropic:** *"Agents summarize completed work phases and store essential information in external memory before proceeding to new tasks."*

**Implementation:**
- [ ] Add automatic phase summarization when context usage exceeds threshold (e.g., 70%)
- [ ] Store summaries in `context/` folder or memory system
- [ ] Implement "checkpoint and continue" pattern for long tasks
- [ ] Add `<save_progress>` and `<load_progress>` actions
- [ ] Consider spawning fresh subagent with clean context + handoff summary

**Estimated Effort:** Medium

---

### 4. Enable Parallel Subagent Execution

**Goal:** Run multiple subagents simultaneously for breadth-first tasks.

**From Anthropic:** *"We introduced two kinds of parallelization: (1) the lead agent spins up 3-5 subagents in parallel rather than serially; (2) the subagents use 3+ tools in parallel. These changes cut research time by up to 90%."*

**From Manus:** *"Each sub-task is assigned to a dedicated agent with its own fresh context window. Agents work simultaneously."*

**Implementation:**
- [ ] Add `parallel=True` option to `spawn_sub_agent`
- [ ] Implement async subagent execution in coordinator
- [ ] Add progress tracking for parallel agents
- [ ] Implement result collection and synthesis
- [ ] Handle partial failures gracefully (retry failed subagents)

**Estimated Effort:** Large

---

### 5. Address Context Rot with Just-in-Time Loading

**Goal:** Minimize context usage by loading data only when needed.

**From Anthropic:** *"Store lightweight identifiers (e.g., file paths, links) and dynamically load data via tools at runtime, as in Anthropic's Claude Code for large database analysis."*

**Implementation:**
- [ ] Audit current context loading patterns
- [ ] Replace eager file loading with path references
- [ ] Add `<load_context>` action for on-demand retrieval  
- [ ] Implement progressive disclosure - layer by layer understanding
- [ ] Add context usage warnings at 50%, 70%, 90% thresholds

**Estimated Effort:** Medium

---

### 6. Trim the System Prompt (Urgent - High Impact)

**Goal:** Reduce the 64KB system prompt to essential, high-signal content.

**From Anthropic:** *"Good context engineering means finding the smallest possible set of high-signal tokens that maximize the likelihood of some desired outcome."*

**Current State:**
- ~64,000 characters / ~16,000 tokens
- 10% of context window consumed before conversation starts
- 20+ mentions of `finish_response` alone
- Redundant sections and examples

**Implementation:**
- [ ] Audit and deduplicate all sections
- [ ] Remove redundant examples (keep 1-2 best)
- [ ] Consolidate code formatting rules (currently repeated 3+ times)
- [ ] Move tool documentation to on-demand loading
- [ ] Consider dynamic prompt assembly based on task type
- [ ] Target: <20KB system prompt (<5K tokens)

**Estimated Effort:** Medium (but high impact)

---

### 7. Add End-State Evaluation for Agents

**Goal:** Evaluate agents by outcome, not process.

**From Anthropic:** *"Instead of judging whether the agent followed a specific process, evaluate whether it achieved the correct final state."*

**Implementation:**
- [ ] Define success criteria for common task types
- [ ] Add `<evaluate_outcome>` action for self-assessment
- [ ] Implement LLM-as-judge for complex outputs
- [ ] Track success rates per agent/persona for tuning
- [ ] Add evaluation checkpoints for long tasks

**Estimated Effort:** Medium

---

### 8. Implement Subagent Output to Filesystem

**Goal:** Reduce token overhead by having subagents write directly to files.

**From Anthropic:** *"Rather than requiring subagents to communicate everything through the lead agent, implement artifact systems where specialized agents can create outputs that persist independently."*

**Implementation:**
- [ ] Define artifact conventions (e.g., `context/artifacts/<agent_id>/<task>.md`)
- [ ] Add `<create_artifact>` action for subagents
- [ ] Lead agent receives lightweight references, not full content
- [ ] Implement artifact cleanup after synthesis

**Estimated Effort:** Small

---

## Recommended Implementation Order

**Phase 1: Foundation (Current Sprint)**
1. Fix config issues (add agents section to config.example.yml)
2. Add CLI `penguin agent spawn --persona`
3. Create multi-agent quickstart tutorial

**Phase 2: Core Patterns**
4. Trim system prompt (highest ROI)
5. Implement memory persistence
6. Add effort scaling heuristics

**Phase 3: Advanced**
7. Orchestrator-worker pattern
8. Parallel subagent execution
9. End-state evaluation

**Phase 4: Optimization**
10. Just-in-time context loading
11. Subagent artifact system
12. Advanced delegation protocols



---

## 🟡 Permission Engine: Safe Execute for Read-Only Agents

*Added after discovering read_only mode blocks all execute*

### Problem

The permission engine blocks `process.execute` entirely in `read_only` mode. This prevents research sub-agents from using grep, find, cat, etc. in the project root.

### Solution: Two-Phase Approach

#### Phase 1: Safe Command Allowlist (Short-term)

Add a command allowlist to the permission engine. In `read_only` mode, only these commands are permitted:

```python
SAFE_READ_COMMANDS = {
    # File reading
    "cat", "head", "tail", "less", "more",
    # Searching
    "grep", "egrep", "fgrep", "rg", "ag", "ack",
    # Finding
    "find", "fd", "locate", "which", "whereis",
    # Listing
    "ls", "tree", "exa", "du", "df",
    # Text processing (read-only)
    "wc", "sort", "uniq", "diff", "comm",
    # Git (read operations)
    "git log", "git show", "git diff", "git status", "git branch",
    # Other safe commands
    "echo", "pwd", "whoami", "date", "env", "printenv",
}

BLOCKED_PATTERNS = [
    ">", ">>",           # Redirects
    "rm", "rmdir",       # Delete
    "mv", "cp",          # Move/copy (can overwrite)
    "chmod", "chown",    # Permissions
    "sudo", "su",        # Privilege escalation
    "curl.*-o", "wget",  # Downloads that write
    "touch", "mkdir",    # Create files/dirs
    "kill", "pkill",     # Process control
]
```

**Implementation location:** `penguin/security/policies/workspace.py` or new `command_filter.py`

**Estimated Effort:** Small-Medium

#### Phase 2: read_execute Permission Mode (Medium-term)

Add a new permission mode:

```python
class PermissionMode(Enum):
    READ_ONLY = "read_only"       # No execute, no writes
    READ_EXECUTE = "read_execute" # Safe execute, no writes  
    WORKSPACE = "workspace"       # Execute + writes in workspace
    FULL = "full"                 # Everything allowed
```

`read_execute` mode:
- Allows `process.execute` with command filtering (Phase 1)
- Blocks `filesystem.write`, `filesystem.delete`
- Allows all read operations

**Estimated Effort:** Medium

---

## 🟡 Dependabot Security Vulnerabilities

**Status:** 26 vulnerabilities on default branch
- 1 Critical
- 5 High  
- 17 Moderate
- 3 Low

**URL:** https://github.com/Maximooch/penguin/security/dependabot

**Action needed:**
1. Review and triage vulnerabilities
2. Update dependencies where safe
3. Document any that can't be updated (breaking changes)

**Estimated Effort:** Small-Medium (1 session)



---

## 🟢 Fixed: Sub-Agent Execution Loop

*Fixed during this session*

### Solution Implemented

When `spawn_sub_agent` is called with `initial_prompt`:
1. ✅ Sub-agent is registered with persona/config
2. ✅ Message is sent via MessageBus
3. ✅ `_agent_inbox` handler receives the message
4. ✅ Handler triggers `engine.run_agent_turn()` for sub-agents
5. ✅ Response is sent back to parent agent via MessageBus

### Code Change (core.py `_agent_inbox`)

Added automatic processing for sub-agents:
- Checks if agent has a parent (is a sub-agent)
- Calls `engine.run_agent_turn()` to process the message
- Sends response back to parent via `send_to_agent()`
- Uses `auto_process` metadata flag to prevent infinite loops

### Current Flow (Broken)
```
Parent Agent → spawn_sub_agent → registers agent → sends initial_prompt via MessageBus → ???
                                                                                         ↓
                                                              Message sits in bus, no consumer
```

### Expected Flow
```
Parent Agent → spawn_sub_agent → registers agent → starts sub-agent engine loop
                                                              ↓
                                              Sub-agent processes initial_prompt
                                                              ↓
                                              Sub-agent sends response to parent
                                                              ↓
                                              Parent receives and continues
```

### Required Implementation

1. **Sub-agent engine loop** - Each sub-agent needs its own processing loop
   - Could be async task spawned on creation
   - Or lazy-started when first message arrives

2. **Response routing** - Sub-agent results need to reach parent
   - Via MessageBus back to parent
   - Or via shared result queue
   - Or via callback mechanism

3. **Lifecycle management** - Track sub-agent state
   - Running / Paused / Completed
   - Timeout handling
   - Error propagation

### Workaround (Current)

The parent agent must do the work itself. Sub-agents are registered but not functional for autonomous work.

### Estimated Effort: Large

This is a significant architectural addition - essentially running multiple agent loops concurrently.

