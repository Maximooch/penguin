# Checkpoint & Context Window Guide

Learn how to use Penguin's powerful checkpoint and context window monitoring features.

---

## Checkpoints: Time-Travel Debugging

Checkpoints let you save conversation state and roll back when needed - perfect for experimentation!

### Creating Checkpoints

```bash
# Create a simple checkpoint
> /checkpoint

# Create a named checkpoint
> /checkpoint important_decision

# Create checkpoint with name and description
> /checkpoint before_refactor "About to refactor auth module"
```

**Aliases**: You can also use `/cp` or `/save`

### Viewing Checkpoints

```bash
> /checkpoints
```

This shows a beautiful table:

```
📍 Checkpoints
┌──────────────┬────────┬─────────────────┬──────────────────┬──────────┐
│ ID           │ Type   │ Name            │ Timestamp        │ Messages │
├──────────────┼────────┼─────────────────┼──────────────────┼──────────┤
│ cp_202511... │ manual │ before_refactor │ 2025-11-06 17:24 │ 12       │
│ cp_202511... │ auto   │ -               │ 2025-11-06 17:20 │ 8        │
└──────────────┴────────┴─────────────────┴──────────────────┴──────────┘

Use `/rollback <id>` to restore or `/branch <id>` to create a new branch
```

Limit results:
```bash
> /checkpoints 10    # Show only 10 most recent
```

**Aliases**: `/cps` or `/list-checkpoints`

### Rolling Back

Made a mistake? Roll back to any checkpoint:

```bash
> /rollback cp_20251106_172448_0f315d2f
✓ Rolled back to checkpoint: cp_20251106_172448_0f315d2f
```

Your conversation is now restored to that exact point! All messages after the checkpoint are removed.

**Aliases**: `/revert` or `/undo`

### Branching

Want to explore different approaches? Branch from a checkpoint:

```bash
> /branch cp_20251106_172448_0f315d2f experimental_approach
✓ Branch created: cp_20251106_172650_22e51a64
```

This creates a new conversation branch - you can explore alternatives without losing your main conversation path.

**Alias**: `/fork`

---

## Context Window Monitoring

Keep track of your token usage and context window health.

### Viewing Token Usage

```bash
> /tokens
```

Shows detailed breakdown:

```
📊 Token Usage
┌──────────┬───────────────┬────────────┐
│ Category │ Tokens        │ Percentage │
├──────────┼───────────────┼────────────┤
│ SYSTEM   │ 450           │ 0.0%       │
│ DIALOG   │ 2,340         │ 0.2%       │
│ CONTEXT  │ 890           │ 0.1%       │
│ TOTAL    │ 3,680 /       │ 0.4%       │
│          │ 1,000,000     │            │
└──────────┴───────────────┴────────────┘
```

If context trimming is active, you'll see a warning:

```
╭─ Truncation Active ────────────────────────────╮
│ ⚠️ Context trimming is active                  │
│ Messages removed: 12                           │
│ Tokens freed: 4,230                            │
│ Use `/truncations` to see details              │
╰────────────────────────────────────────────────╯
```

### Viewing Truncation Events

When your conversation gets too long, Penguin automatically trims older messages to stay within the context window. View what was trimmed:

```bash
> /truncations
```

Shows recent trimming activity:

```
╭─ Context Trimming Summary ─────────────────────╮
│ Total Events: 3                                │
│ Messages Removed: 12                           │
│ Tokens Freed: 4,230                            │
╰────────────────────────────────────────────────╯

Recent Truncation Events
┌──────────┬──────────┬──────────────┬───────────┐
│ Category │ Messages │ Tokens Freed │ Timestamp │
├──────────┼──────────┼──────────────┼───────────┤
│ CONTEXT  │ 5        │ 1,240        │ 17:30:15  │
│ DIALOG   │ 4        │ 1,850        │ 17:32:40  │
│ DIALOG   │ 3        │ 1,140        │ 17:35:20  │
└──────────┴──────────┴──────────────┴───────────┘
```

Limit results:
```bash
> /truncations 5    # Show only 5 most recent events
```

**Alias**: `/trunc`

---

## Real-World Workflows

### Safe Experimentation

```bash
# 1. Create checkpoint before risky work
> /checkpoint before_major_change "Trying new architecture approach"

# 2. Try your experiment
> Refactor the entire codebase to use async/await

# 3a. If it works - great! Continue...
> That worked well, let's continue

# 3b. If it fails - rollback instantly
> /rollback cp_20251106_172448_0f315d2f
> Let's try a different approach instead
```

### Exploring Alternatives

```bash
# 1. Create checkpoint at decision point
> /checkpoint decision_point "Choosing between approaches"

# 2. Try approach A
> Implement using approach A

# 3. Branch back to explore approach B
> /branch cp_20251106_172448_0f315d2f approach_b
> Implement using approach B instead

# 4. Compare results, choose best one
```

### Monitoring Long Conversations

```bash
# Check token usage periodically
> /tokens

# If getting close to limit, check what's being trimmed
> /truncations

# Create checkpoint before trimming gets aggressive
> /checkpoint before_trimming

# Continue conversation with peace of mind
```

---

## Tips & Best Practices

1. **Create checkpoints before risky operations**
   - Major refactorings
   - Complex multi-file changes
   - Experimental approaches

2. **Use descriptive names**
   - `/checkpoint auth_complete` better than `/checkpoint`
   - Future you will thank present you

3. **Monitor context window**
   - Run `/tokens` occasionally in long conversations
   - Create checkpoint before hitting 80% usage

4. **Branch for exploration**
   - Use `/branch` when exploring alternatives
   - Keep your main conversation clean

5. **Review truncations**
   - If Penguin seems to "forget" context, check `/truncations`
   - Important context might have been trimmed
   - Consider creating checkpoint before continuing

---

## Technical Details

### Checkpoint Storage

- **Location**: `~/.penguin/checkpoints/`
- **Format**: Compressed JSON (gzip)
- **Indexing**: Fast lookup via checkpoint index
- **Retention**: Configurable (default: keep all for 24h, then every 10th)

### Automatic Checkpoints

Penguin also creates automatic checkpoints:
- Every message by default (configurable)
- Before rollback operations
- When branching

These auto-checkpoints have `type: "auto"` in the listing.

### Context Window Management

Penguin automatically manages context window to stay within model limits:
1. Tracks tokens by category (SYSTEM, DIALOG, CONTEXT)
2. Trims older messages when approaching limit
3. Preserves important messages (system prompts, recent context)
4. Logs all trimming events for transparency

You can monitor this with `/tokens` and `/truncations`.

---

## Command Reference

| Command | Aliases | Description |
|---------|---------|-------------|
| `/checkpoint [name] [desc]` | `/cp`, `/save` | Create manual checkpoint |
| `/rollback <id>` | `/revert`, `/undo` | Rollback to checkpoint |
| `/checkpoints [limit]` | `/cps` | List available checkpoints |
| `/branch <id> [name]` | `/fork` | Create branch from checkpoint |
| `/tokens` | - | Show token usage by category |
| `/truncations [limit]` | `/trunc` | Show context trimming events |

---

## FAQ

**Q: How long are checkpoints kept?**  
A: By default, all checkpoints from the last 24 hours, then every 10th checkpoint, up to 30 days max. Configurable in settings.

**Q: Can I rollback after closing Penguin?**  
A: Yes! Checkpoints persist across sessions. Use `/checkpoints` to see available checkpoints.

**Q: What's the difference between checkpoint and branch?**  
A: Rollback **replaces** your current conversation. Branch **creates a new copy** you can explore without losing the original.

**Q: Why don't I see my checkpoint immediately after creating it?**  
A: Checkpoints are processed asynchronously (~0.5s delay). Wait a moment then run `/checkpoints`.

**Q: Can I export/import checkpoints?**  
A: Not yet - coming in a future update!

**Q: Will truncations affect my conversation quality?**  
A: Penguin intelligently trims less important messages first. System prompts and recent context are preserved. If you notice issues, create a checkpoint and start a fresh conversation.

---

## Getting Help

- Type `/help` in Penguin to see all commands
- Visit [Penguin Documentation](https://penguin.ai/docs) for more guides
- Report issues on [GitHub](https://github.com/your-repo/penguin)

---

**Happy checkpointing!** 🐧✨

