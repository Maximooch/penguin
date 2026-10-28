# Inspecting and steering subagents

`send_message` queues messages for registered agents in the current runtime.
Its `message_ids` receipt means the message was accepted, not that the model has
read it. At the next model step, the child saves the message in its own session
before building the provider request. Messages arriving during a tool call wait
until the tool result has been recorded. A running multi-step child processes
pending steering before accepting completion, within its existing budgets.

`get_agent_status` includes start/finish timestamps and `messaging` diagnostics:
queue depth, last progress time and phase, and last delivered message ID. Pending
messages in a stopped or budget-limited child wait for its next model step.
Queues are in memory and do not survive a backend restart.

`delegate` rejects a second background task for a busy child with `agent_busy`.
Use `send_message` to steer it, `get_agent_status` to inspect it, or
`stop_sub_agent` to cancel it. Failed delivery includes recovery guidance.

`wait_for_agents` waits for selected child task completion events. A timeout or
cancelled wait leaves the children running. Executors without event support use
bounded exponential backoff, up to two seconds between status scans.

`conversation_open` pages raw persisted message indices, including tool,
assistant, user, and system records. `total_messages`, `message_start`, and
`next_message_start` refer to that same index space. This preserves indices from
`conversation_search` even when an entire page consists of tool results. Text
is bounded and may be truncated; the archive itself is never modified. Active
children are visible up to their latest saved archive snapshot.
