# Penguin Journal 247 System - Implementation Plan

## Vision

A session-aware journaling and memory system for Penguin that provides continuity across conversations while supporting multi-agent collaboration and eventual integration with Link (chat/orchestration platform).

## Core Principles

1. **Continuity**: AI agents should remember context across sessions
2. **Flexibility**: Works for single-user local, VPS, and eventually multi-user/team scenarios
3. **Efficiency**: Only load what's needed, keep tokens manageable
4. **Write-heavy**: "If you want to remember it, write it down"
5. **Security**: Long-term memory only in trusted contexts

---

## Phase 1: Single-User Local Foundation (MVP)

**Goal**: Core journaling for individual developers using Penguin locally

### Files & Structure
```
working_project_dir/                  # Where user runs penguin
├── context/                          # Existing context folder
│   ├── journal/                      # Daily session logs (NEW)
│   │   ├── 2025-01-27.md            # Auto-created per day
│   │   ├── 2025-01-28.md
│   │   └── ...
│   └── ...                          # Other context files
└── .penguin/                        # Penguin state (existing)
    └── sessions/
```

### Journal Entry Format (YAML Frontmatter)
```markdown
---
timestamp: 2025-01-27T15:30:00Z
entry_type: chat_message
session_id: session-abc123
agent_id: main
tokens: 150
---
User asked about Python async/await patterns.
```

### Loading Strategy
- Load **last 50 entries** from today's journal (1-3 lines each)
- Journals located in `context/journal/` (part of project directory)
- Agent prompted to check journals at session start (similar to Clawdbot AGENTS.md pattern)
- No tight integration with context system - journals are just files agent can read

### Auto-Writing (During Session)
- **Chat messages** → streamed to today's journal in real-time
- **Important events** (checkpoints, errors, completions) → appended to journal
- **Key insights** → agent can suggest updates to memory files

### CLI Commands
```bash
/journal today              # Show today's log
/journal yesterday          # Show yesterday
/journal last N             # Show last N days
/journal search <query>     # Search across all journals
/journal write "<text>"     # Add note to today

/memory read <category>     # Read specific memory file
/memory write <category> "<text>"   # Add to memory
/memory list                # List available categories
/memory init                # Create default memory files
```

### Config
```yaml
journal:
  enabled: true
  auto_load: true
  auto_save: true
  max_history_days: 7        # How many days of journals to keep in context
  token_budget: 6000         # Max tokens for journal context
  categories:
    - user
    - projects
    - lessons
    - decisions
  security:
    long_term_in_shared: false   # Don't load memory/ in shared contexts
```

### Headless Mode
When `headless: true` in config:
- Journaling disabled by default
- Can enable with `journal.headless_logging: true` (logs to files only, not loaded)
- Logs stored in `journal/headless/` by task/session ID

---

## Phase 2: Multi-Agent Coordination

**Goal**: Support multiple Penguin agents working simultaneously

### Challenges
1. **Concurrent writes**: Two agents writing to same journal file
2. **Context isolation**: Agents shouldn't see each other's internal work
3. **Shared memory**: Some memory should be shared, some agent-specific

### Solution: Branching & Merging

```
penguin_workspace/
├── journal/
│   ├── main/                    # Main conversation journal
│   │   ├── 2025-01-27.md
│   │   └── ...
│   ├── agents/                  # Per-agent journals
│   │   ├── agent-abc123/
│   │   │   ├── 2025-01-27.md
│   │   │   └── ...
│   │   └── agent-def456/
│   │       └── ...
│   └── sessions/                # Session-specific (ephemeral)
│       └── session-xxx/
│           └── log.md
└── memory/
    ├── shared/                  # All agents can read/write
    │   ├── user.md
    │   ├── projects.md
    │   └── decisions.md
    └── agents/                  # Agent-specific
        ├── agent-abc123/
        │   ├── lessons.md
        │   └── notes.md
        └── agent-def456/
            └── ...
```

### Branching Model
- **Main branch**: Human's direct conversation
- **Agent branches**: Each sub-agent gets its own journal space
- **Merge on completion**: Agent summaries merged back to main journal

### Coordination
```python
# When spawning sub-agent
parent_agent.journal.branch(agent_id="sub-123")

# When sub-agent completes
sub_agent.journal.merge_to_parent(summary="Key findings...")
```

### CLI
```bash
/agents list                # List active agent branches
/agent <id> journal         # View specific agent's journal
/merge <agent_id>           # Merge agent branch back to main
```

---

## Phase 3: Link Integration Prep

**Goal**: Architecture that can integrate with Link platform

### Design for Link Compatibility

1. **Pluggable Storage Backend**
   ```python
   class JournalBackend(ABC):
       def read(self, path: str) -> str: ...
       def write(self, path: str, content: str): ...
       def list(self, prefix: str) -> List[str]: ...
       def search(self, query: str) -> List[Result]: ...

   # Implementations
   - LocalFilesystemBackend (Phase 1-2)
   - S3Backend (for VPS/cloud)
   - LinkAPIBackend (for Link integration)
   - DatabaseBackend (PostgreSQL for teams)
   ```

2. **Event-Driven Architecture**
   ```python
   # Journal events that Link can subscribe to
   - JournalEntryCreated
   - MemoryFileUpdated
   - AgentBranchCreated
   - AgentBranchMerged
   ```

3. **Schema Versioning**
   ```yaml
   # Each journal entry has metadata
   ---
   schema_version: "1.0"
   entry_type: "chat_message"  # or "checkpoint", "error", "completion"
   timestamp: "2025-01-27T15:30:00Z"
   agent_id: "main"           # or specific agent ID
   session_id: "session-abc"
   tokens: 150
   ---
   Content here...
   ```

### Multi-User Support (Future)
```yaml
# For teams/orgs
journal:
  mode: "multi_user"  # vs "single_user"

  # Per-user isolation with shared project memory
  user_isolation: true

  # Shared spaces
  shared_projects: true
  shared_lessons: true

  # Permissions
  permissions:
    user: ["read_own", "write_own", "read_shared"]
    admin: ["read_all", "write_all", "manage"]
```

---

## Phase 4: Advanced Features (Post-Link)

### Smart Summarization
- Auto-summarize old journals (compress 10k tokens → 1k tokens)
- Extract key insights to memory files
- Semantic search across all history

### Vector Memory Integration
- Embeddings for journal entries
- Semantic similarity search
- "What did we discuss about X?"

### Cross-Session Learning
- Pattern recognition across sessions
- "You often ask about Y after working on X"
- Proactive suggestions

---

## Context Message Ordering (Future)

**Phase 3/4**: When we integrate with Link and have a better understanding of how journals fit into the overall context window, we can revisit how context messages are loaded. For now (Phase 1), journals are simply loaded as CONTEXT category messages like any other context file.

---

## Implementation Checklist

### Phase 1 Tasks
- [ ] Create `JournalManager` class
- [ ] Implement daily journal file creation
- [ ] Add auto-loading on session start
- [ ] Add auto-writing during session
- [ ] Create `/journal` CLI commands
- [ ] Create `/memory` CLI commands
- [ ] Add config options
- [ ] Write tests
- [ ] Update documentation

### Phase 2 Tasks
- [ ] Design branching model
- [ ] Implement agent-specific journals
- [ ] Add merge functionality
- [ ] Handle concurrent writes (file locking)
- [ ] Add `/agents` CLI commands

### Phase 3 Tasks
- [ ] Abstract storage backend
- [ ] Implement event system
- [ ] Add schema versioning
- [ ] Design Link integration points
- [ ] Multi-user architecture design

---

## Questions to Resolve

1. **Token management**: How aggressively should we summarize old journals?
2. **Privacy**: What should NEVER be written to journals (passwords, secrets)?
3. **Retention**: How long to keep daily journals before archiving/summarizing?
4. **Migration**: How to migrate from Phase 1 → Phase 2 → Phase 3 without data loss?

---

## Next Steps

1. Review this plan
2. Decide on Phase 1 scope
3. Create detailed technical spec for Phase 1
4. Begin implementation


## Feature Considerations

1. **Show session ID**: current it just says "cli", not very helpful.
2. **Consider markdown?**: markdown is the industry standard, the reasons for yml can easily be done in markdown. 
3. **Consider git config**: That way we can introduce some sort of RBAC while still keeping it very minimal
4. **move to `.penguin`**: I think .penguin/memory (or journal) is a better spot than context/journal. Well there are reasons for keeping it where it is for auditing purposes. Kind of but not really.
5. **amplify by consolidating**: General consolidation across multiple prompt files (system_prompt.py, prompt_workflow.py, prompt_actions.py) is needed. By having less we can give more (likely attention) given to the journal system. 
6. **invoke commands**: commands that can invoke the Penguin to write entries manually. Then later as parts of stages we can do the same for after it finishes a phase of a project. 

This also could be done in a slightly different form factor of "time logs" (or something like that) for things specific 

---

**Document Version**: 1.0  
**Created**: 2025-01-27  
**Status**: Draft - Awaiting review
