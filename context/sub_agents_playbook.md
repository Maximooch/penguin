# Sub-Agent Playbook (Phase C/D Learnings)

## Findings

- **Backend Wiring Solid**: REST (`/api/v1/agents`, `/messages`, `/telemetry`) and WebSocket (`/api/v1/ws/messages`, `/api/v1/ws/telemetry`) flows work end-to-end. `phaseC_rest_smoke.py` and `phaseC_ws_smoke.py` confirm spawn → pause → delegate → resume → history → telemetry.
- **Python Client Ready**: `PenguinClient` exposes `create_sub_agent`, `pause_agent`, `resume_agent`, and the live `phaseD_live_sub_agent_demo.py` script spawns research-type children successfully.
- **Telemetry Enriched**: Collector now reports totals, per-agent tokens/context usage, and message rates; `/ws/telemetry` streams snapshots.
- **Docs Updated**: Sub-agent guide includes ActionXML, REST routes, CLI pointers, and the live demo script; multi-agent overview references the new API surfaces.
- **Model Configuration**: `moonshotai/kimi-k2-0905` added to config; clamp notices mirrored to parent/child conversations.

## Approach & Lessons for Future Agents

- **Start with Discovery**: read context files (`penguin_todo_multi_agents`, scripts, config) before coding. Map existing behaviour and open TODOs so you build on, not against, prior work.
- **Tight Feedback Loops**: alternate edits with quick validation (`phaseC_rest_smoke.py`, `phaseC_ws_smoke.py`, ad-hoc Python snippets) to keep changes reversible and verified.
- **Expose Diagnostics Early**: add targeted logging (e.g., available `model_configs`, richer error details) as soon as ambiguity appears. It saves time when issues surface later.
- **Script First, UI Later**: when CLI/TUI support is missing, create focused scripts (`phaseD_live_sub_agent_demo.py`) to exercise behaviour. These evolve into regression tests and documentation examples.
- **Document While Hot**: update docs and notes in the same session as code changes. Future agents shouldn’t reverse-engineer what just shipped.
- **Respect External Constraints**: Moonshot’s 262k limit and similar provider caps require careful prompts and `shared_cw_max_tokens`. Guardrails in code and docs prevent repeated context overflows.

## Recommendations for Future Agents

1. **Always check `model_configs`** before spawning. Prefer a known `model_config_id`; fall back to `model_overrides` only when necessary.
2. **Use REST/WebSocket endpoints** for orchestration when CLI/TUI lags behind. The smoke scripts are good templates (REST: `phaseC_rest_smoke.py`, WS: `phaseC_ws_smoke.py`).
3. **Rely on telemetry** to monitor multi-agent runs: pull `/api/v1/telemetry` for dashboards, or subscribe to `/api/v1/ws/telemetry` for live counters.
4. **Script complex scenarios early**. `phaseD_live_sub_agent_demo.py` shows how to drive sub-agents programmatically even before UI work lands.
5. **Mind context limits**. Moonshot’s 262k cap can still overflow if prompts + outputs exceed it; clamp shared CW and tighten prompts for large tasks.
6. **CLI/TUI gap**: pause/resume/list are wired, but UI spawn/delegate helpers remain TODO. Use scripts or REST while those surfaces catch up.

## Future Strategy

- **UI parity**: extend CLI/TUI to expose spawn/delegate/pause/resume and show channel-aware transcripts.
- **Telemetry consumers**: build dashboards or notifications atop `/ws/telemetry` and `/ws/messages` to catch anomalies automatically.
- **Scenario library**: curate more `phaseD`-style scripts (e.g., bug triage, doc drafting) so future agents have ready-made playbooks.
- **Rate limiting & auth**: roadmap includes auth tokens, CORS refinement, and eventual throttling once external integrations go live.
- **Docs & Recipes**: continue evolving the sub-agent doc with real examples, REST snippets, and troubleshooting (e.g., context overflow).

Keep these notes handy when iterating on multi-agent experiences—the core is stable, so the next wins are polish, UI affordances, richer playbooks, and maintaining the disciplined workflow outlined above.
