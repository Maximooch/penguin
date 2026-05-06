# Model Context Protocol (MCP)

Penguin supports MCP in two directions:

1. **Penguin as an MCP host/client** — Penguin connects to external MCP servers and uses their tools.
2. **Penguin as an MCP server** — external MCP hosts connect to Penguin and use Penguin's tools/runtime surface.

MCP support is optional. Install Penguin with MCP support when you want this functionality:

```bash
uv sync --extra mcp
# or for package installs
pip install "penguin-ai[mcp]"
```

## Penguin As MCP Host / Client

Penguin can consume local STDIO MCP servers and expose their tools through Penguin's ToolManager.

Example config shape:

```yaml
mcp:
  enabled: true
  servers:
    chrome-devtools:
      command: npx
      args:
        - -y
        - chrome-devtools-mcp@latest
        - --no-usage-statistics
        - --no-update-checks
        - --slim
      startup_timeout_sec: 60
      tool_timeout_sec: 120
```

Penguin also accepts common aliases:

```yaml
mcpServers:
  everything:
    command: npx
    args:
      - -y
      - "@modelcontextprotocol/server-everything"
```

Discovered tools use model-safe names:

```text
mcp__chrome_devtools__navigate
mcp__chrome_devtools__evaluate
mcp__everything__echo
```

### Host Smoke Script

A control-plane smoke script exercises Penguin's MCP server over real MCP stdio:

```bash
uv run --python 3.11 --extra mcp python scripts/mcp_control_plane_smoke.py
```

## Penguin As MCP Server

Run Penguin's MCP stdio server:

```bash
uv run --python 3.11 --extra mcp python scripts/penguin_mcp_server.py
```

Use MCP Inspector:

```bash
npx -y @modelcontextprotocol/inspector \
  --cli \
  uv -- run --python 3.11 --extra mcp python scripts/penguin_mcp_server.py \
  --method tools/list
```

### Default-On Tools

Default-on tools are exposed when a user intentionally starts Penguin's MCP server.

Safe workspace/read tools:

- `read_file`
- `list_files`
- `find_file`
- `grep_search`
- `analyze_project`

Project Management tools:

- `penguin_pm_list_projects`
- `penguin_pm_create_project`
- `penguin_pm_get_project`
- `penguin_pm_list_tasks`
- `penguin_pm_create_task`
- `penguin_pm_get_task`

Blueprint tools:

- `penguin_blueprint_lint`
- `penguin_blueprint_graph`
- `penguin_blueprint_status`
- `penguin_blueprint_sync`

`penguin_blueprint_sync` defaults to dry-run.

### Runtime-Gated Tools

Runtime tools are exposed only with:

```bash
uv run --python 3.11 --extra mcp python scripts/penguin_mcp_server.py --allow-runtime-tools
```

RunMode tools:

- `penguin_runmode_capabilities`
- `penguin_runmode_list_jobs`
- `penguin_runmode_get_job`
- `penguin_runmode_start_task`
- `penguin_runmode_start_project`
- `penguin_runmode_cancel_job`
- `penguin_runmode_resume_clarification`

ITUV tools:

- `penguin_ituv_capabilities`
- `penguin_ituv_status`
- `penguin_ituv_frontier`
- `penguin_ituv_signal`
- `penguin_ituv_mark_ready_for_review`
- `penguin_ituv_record_artifact`

Runtime mutation tools default to dry-run where applicable. Callers must explicitly pass `dry_run=false` to apply lifecycle or artifact changes.

## Example: Blueprint Control Plane

Create a project, dry-run sync a Blueprint, apply the sync, then inspect tasks:

```text
penguin_pm_create_project
penguin_blueprint_sync { dry_run: true }
penguin_blueprint_sync { dry_run: false }
penguin_pm_list_tasks
penguin_blueprint_status
```

This is the recommended first product-path test before starting autonomous RunMode execution.

## Example: Chrome DevTools MCP

Chrome DevTools MCP is a strong real-world test target for Penguin as host/client.

Recommended first config uses slim mode:

```yaml
mcp:
  enabled: true
  servers:
    chrome-devtools:
      command: npx
      args:
        - -y
        - chrome-devtools-mcp@latest
        - --no-usage-statistics
        - --no-update-checks
        - --slim
```

Privacy/safety note: Chrome DevTools MCP can inspect browser state. Use an isolated test profile for serious testing.

## Security Model

- External MCP host tools route through Penguin's tool permission path.
- Penguin-as-server denies dangerous low-level tools by default.
- Shell execution, file writes, browser automation, sub-agent spawning, and delegation are not exposed unless explicitly allowlisted.
- RunMode/ITUV tools require `--allow-runtime-tools`.
- Local STDIO MCP servers are trusted enough to run as local subprocesses; configure them deliberately.

## Current Limitations

- STDIO host/client support is implemented; remote Streamable HTTP/OAuth support is future work.
- Runtime job records persist locally in ProjectStorage when a ProjectManager is available; orphaned non-terminal records survive restarts but are not controllable.
- ITUV artifact writes currently use task storage directly from the MCP tool layer; a ProjectManager helper should be added.
- Phase transition policy for ITUV mutation tools is currently MCP-local and should move into ProjectManager if it becomes a broader API contract.

## Related Internal Docs

- `context/tasks/mcp.md`
- `context/architecture/mcp-runtime-surface.md`
- `context/architecture/mcp-runtime-job-records.md`
- `context/architecture/runmode-project-ituv-system-map.md`


## Runtime Job Durability

RunMode MCP jobs are persisted locally in Penguin's project database (`projects.db`) when a `ProjectManager` is available. The live MCP server still owns cancellation handles, so a restarted server can recover job history but cannot force-control an orphaned non-terminal Python thread from a dead process. Orphaned records are returned as `live=false`, `controllable=false`, with metadata explaining the missing live handle.


### Session, Artifact, And Checkpoint Reads

Penguin MCP also exposes default-on read-only handoff tools:

- `penguin_session_list`
- `penguin_session_summary`
- `penguin_artifacts_list`
- `penguin_checkpoints_list`

These tools do not restore checkpoints or mutate sessions. Restore/rollback remains intentionally gated future work.


### MCP Resources And Prompts

Penguin's MCP server exposes conservative resources and prompts by default:

Resources:

- `penguin://projects`
- `penguin://project/{project_id}`
- `penguin://task/{task_id}`
- `penguin://session/{session_id}/summary`
- `penguin://docs-cache/{source}/{page}`

Prompts:

- `penguin_task_brief`
- `penguin_blueprint_outline`
- `penguin_runmode_handoff`

Disable them with `--no-resources` or `--no-prompts` when running `scripts/penguin_mcp_server.py`.
