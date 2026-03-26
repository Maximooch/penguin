# Sub-Agent Simplification Proposal

*Created after debugging session revealed complex MessageBus routing issues*

---

## Current Problem

The existing `spawn_sub_agent` / MessageBus approach is overengineered:
- MessageBus handlers not registered for 'default' agent
- Complex routing between agents
- No clear way to get responses back
- Too much infrastructure for a simple task

## The Real Question

What do you want the sub-agent to be able to do?

### Option A: Just Analyze Provided Content (No Tools)

- Parent reads files, passes content to haiku
- Haiku analyzes and returns summary
- Simple, works now

**Example usage:**
```xml
<delegate_read_task>{
  "task": "Summarize the architecture",
  "files": ["README.md", "src/main.js", "package.json"]
}</delegate_read_task>
```

Parent reads the files, sends content + task to haiku, gets summary back.

**Pros:**
- Simple to implement (can do right now)
- No tool loop complexity
- Predictable behavior

**Cons:**
- Parent must know which files to read
- Can't discover files autonomously

### Option B: Explore Autonomously (Needs Tools)

- Haiku can call list_files, read_file, search
- Requires tool loop implementation
- More complex

**Pros:**
- Sub-agent can explore independently
- Discovers relevant files on its own

**Cons:**
- Requires mini action loop
- More complex to implement
- Potential for runaway tool calls

---

## Proposed Solution: `delegate_read_task`

A simple tool that:
1. Takes a task prompt and optional file list
2. Reads the specified files (or uses provided context)
3. Calls haiku with the context + task
4. Returns haiku's response directly

**No MessageBus, no handler registration, no complex routing.**

### Implementation

```python
async def _delegate_read_task(self, params: str) -> str:
    """Delegate a read-only task to haiku.

    JSON body:
      - task (required): What to analyze
      - files (optional): Files to read first
      - context (optional): Additional context string
    """
    payload = json.loads(params)
    task = payload.get("task")
    files = payload.get("files", [])

    # Read files
    file_contents = []
    for f in files[:5]:
        content = Path(f).read_text()[:10000]
        file_contents.append(f"=== {f} ===\n{content}")

    # Build prompt
    context = "\n\n".join(file_contents)
    prompt = f"Context:\n{context}\n\nTask: {task}"

    # Call haiku directly
    gateway = create_gateway(provider="openrouter", model="anthropic/claude-haiku-4.5")
    response = await gateway.chat(messages=[{"role": "user", "content": prompt}])

    return f"[Haiku response]:\n{response}"
```

---

## For Autonomous Exploration (Future)

If we want haiku to explore autonomously, we need a mini action loop:

```python
async def _delegate_explore_task(self, params: str) -> str:
    """Delegate exploration task with tool access."""

    # Create temporary agent with haiku
    # Run mini engine loop with limited tools
    # Return final response

    for iteration in range(max_iterations):
        response = await haiku_call(messages)

        if has_tool_calls(response):
            results = await execute_tools(response.tool_calls)
            messages.append(results)
        else:
            return response.content
```

This is more complex but enables true autonomous exploration.

---

## Recommendation

Start with **Option A** (`delegate_read_task`):
1. Simple to implement
2. Covers 80% of use cases
3. No complex infrastructure

Add **Option B** later if needed.

---

## Next Steps

1. Implement `delegate_read_task` in parser.py
2. Register the action type
3. Add to prompt_actions.py documentation
4. Test with simple file analysis tasks
