# Cache-stable context and Codex routing

Penguin derives budgeted request context without deleting the saved transcript.
Within an engine run, selected message boundaries remain stable as tool results
are appended. Source edits, new instructions, model limits and overflow trigger
an explicit rebase; tool definitions remain freshly authorized each step.
Existing large-tool-output artifacts retain recoverable full results.

For Codex OAuth, the session-id header supplies stable session affinity.
The first x-codex-turn-state response header is replayed only within that engine
run and conversation. Credential changes clear the token. It is not saved to
conversation history or logged. Standalone adapter calls without an engine run
do not invent shared routing state.

Codex HTTP requests reuse Penguin's connection pool, closed by the web server
at shutdown, with the existing unbounded streaming read timeout retained.
Usage includes nested cache-write tokens; whole-turn totals include all model
iterations. Lifecycle data distinguishes service_tier (requested) from
served_service_tier (reported by the provider, absent if not returned).

Look for engine.context.prefix and cwm.epoch.rebase logs when diagnosing prefix
changes. Diagnostics contain hashes/counts, not prompt contents. Cache reuse
still depends on backend availability: these changes do not guarantee a hit.
API cache TTL and comparison-response controls are not sent to Codex OAuth.
No live performance improvement has yet been measured for this implementation.
