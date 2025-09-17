---
sidebar_position: 8
---

# Sub-Agent Delegation

Sub-agents let a primary Penguin agent break large objectives into delegated tasks that can run with scoped permissions, tailored prompts, and isolated execution state.

## Delegation Model

1. **Primary agent** receives a user instruction and determines that a supporting workflow is needed.
2. **Sub-agent spawn** happens via the core orchestration pipeline. Each sub-agent inherits the parent's system prompt, tools, and conversation metadata unless explicitly overridden.
3. **Scoped execution** ensures the sub-agent can only act within its delegated objective. Results are streamed back to the parent for evaluation.
4. **Merge and respond**: The parent agent inspects the sub-agent's output (and optional partial checkpoints) and incorporates it into the final reply.

## Use Cases

- Running long-lived analysis in parallel with a main dialogue
- Executing read-only audits before the primary agent performs mutating actions
- Enlisting specialized prompts (security reviewer, documentation writer) without swapping personas for the entire session

## Capabilities

### Shared Context

Sub-agents have access to:

- Conversation history provided by the parent at time of spawn
- Registered tools (file editing, shell access, web search, etc.)
- Memory recall, including vector search results and semantic summaries

### Scoped State

- **Checkpoints**: Sub-agents can create checkpoints tagged with their identifier. Parents can choose to adopt or discard them.
- **Tokens and budgets**: Each sub-agent run maintains its own token accounting, allowing strict budgeting without impacting the parent run.
- **Streaming callbacks**: Streaming output from sub-agents is surfaced through the same event bus so UIs can display incremental progress.

## Working with Sub-Agents

### Python API

```python
import asyncio

from penguin.api_client import ChatOptions, PenguinClient


async def research_and_write(prompt: str) -> str:
    async with PenguinClient() as client:
        parent_id = "primary"
        researcher_id = "research"

        # Ensure a base conversation for the parent agent
        cm = client.core.conversation_manager
        cm.create_agent_conversation(parent_id)

        # Create a sub-agent that inherits the parent's context window budget
        cm.create_sub_agent(
            researcher_id,
            parent_agent_id=parent_id,
            shared_cw_max_tokens=512,
        )

        # Let the researcher gather information
        research_notes = await client.chat(
            prompt,
            options=ChatOptions(agent_id=researcher_id),
        )

        # Feed the findings back to the primary agent for synthesis
        return await client.chat(
            f"Summarize and refine: {research_notes}",
            options=ChatOptions(agent_id=parent_id),
        )


asyncio.run(research_and_write("Compile highlights from the latest changelog."))
```

Under the hood the conversation manager clones the parent's system and context state, optionally clamping context-window budgets so the delegated run cannot exceed agreed limits. Advanced setups can combine this with `PenguinCore.register_agent` to wire dedicated executors once the engine is running.

### REST and WebSocket

Today, REST and WebSocket interfaces expose the `agent_id` routing parameter. Sub-agent orchestration occurs through the core APIs shown above; API-level payloads for sub-agent creation are on the roadmap and will follow the same intent-but be explicit about that being future work.

## Best Practices

- **Keep scopes tight**: Sub-agents should have a singular, well-defined objective. Broad scopes reduce determinism.
- **Budget tokens**: Supply explicit limits when spawning analysis-heavy sub-agents to avoid runaway costs.
- **Audit results**: Treat sub-agent output as suggestions; validate before enacting irreversible changes.
- **Instrument**: Include sub-agent identifiers in your telemetry so you can monitor success rates and latency.

## Roadmap

- First-class CLI commands for configuring sub-agent templates
- Adaptive delegation heuristics that decide when to spawn sub-agents automatically
- Fine-grained permission profiles per sub-agent (read-only vs. write access)
- Visualizations in the web UI showing delegation trees and progress

Need to coordinate multiple top-level personas instead? Check out [Multi-Agent Orchestration](multi_agents.md).
