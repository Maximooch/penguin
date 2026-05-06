# MCP Tool Catalog

## Status

- Created: 2026-05-04
- Scope: currently implemented Penguin MCP server tools

## Exposure Classes

| Class | Meaning |
| --- | --- |
| default-on | exposed when Penguin MCP server starts normally |
| runtime-gated | exposed only with `--allow-runtime-tools` |
| mutating | can change project/task/runtime state |
| dry-run default | mutation requires explicit `dry_run=false` |

## Safe Workspace Tools

Default-on, read-oriented.

| Tool | Mutates | Notes |
| --- | --- | --- |
| `read_file` | no | Read workspace file content |
| `list_files` | no | List files/directories |
| `find_file` | no | Find files by name/glob |
| `grep_search` | no | Search workspace text |
| `analyze_project` | no | AST/project analysis |

## Project Management Tools

Default-on.

| Tool | Mutates | Notes |
| --- | --- | --- |
| `penguin_pm_list_projects` | no | List projects with optional status filter |
| `penguin_pm_create_project` | yes | Create project |
| `penguin_pm_get_project` | no | Get project by ID; can include tasks |
| `penguin_pm_list_tasks` | no | List tasks by project/status/parent |
| `penguin_pm_create_task` | yes | Create rich task; unsupported rich fields preserved as metadata where possible |
| `penguin_pm_get_task` | no | Get task by ID |

## Blueprint Tools

Default-on.

| Tool | Mutates | Dry-Run Default | Notes |
| --- | --- | --- | --- |
| `penguin_blueprint_lint` | no | n/a | Parse/lint Blueprint file or inline content |
| `penguin_blueprint_graph` | no | n/a | Return nodes/edges and optional DOT |
| `penguin_blueprint_status` | no | n/a | Report Blueprint-derived project/task DAG state |
| `penguin_blueprint_sync` | yes | yes | Sync Blueprint into PM tasks; refuses lint errors |

## RunMode Tools

Runtime-gated with `--allow-runtime-tools`.

| Tool | Mutates | Notes |
| --- | --- | --- |
| `penguin_runmode_capabilities` | no | Reports runtime support and caveats |
| `penguin_runmode_list_jobs` | no | Merges ProjectStorage-backed durable jobs with live in-process jobs |
| `penguin_runmode_get_job` | no | Inspect one in-memory job |
| `penguin_runmode_start_task` | yes | Starts background RunMode task job |
| `penguin_runmode_start_project` | yes | Starts background project-scoped execution |
| `penguin_runmode_cancel_job` | yes | Cooperative cancellation; not hard thread kill |
| `penguin_runmode_resume_clarification` | yes | Resume waiting clarification flow |

## ITUV Tools

Runtime-gated with `--allow-runtime-tools`.

| Tool | Mutates | Dry-Run Default | Notes |
| --- | --- | --- | --- |
| `penguin_ituv_capabilities` | no | n/a | Statuses, phases, transitions, dependency policies |
| `penguin_ituv_status` | no | n/a | Project/task ITUV status, readiness, artifact evidence |
| `penguin_ituv_frontier` | no | n/a | Dependency-aware ready task frontier |
| `penguin_ituv_signal` | yes | yes | `set_status`, `set_phase`, `block`, `unblock` with guards |
| `penguin_ituv_mark_ready_for_review` | yes | yes | ProjectManager-owned bridge to `phase=done` + `status=pending_review` |
| `penguin_ituv_record_artifact` | yes | yes | Attach `ArtifactEvidence`; ProjectManager helper still needed |

## External MCP Host Tools

When Penguin consumes external MCP servers, names use:

```text
mcp__<server>__<tool>
```

Examples:

- `mcp__chrome_devtools__navigate`
- `mcp__chrome_devtools__evaluate`
- `mcp__everything__echo`

These route through Penguin's ToolManager and permission semantics.

## Known Documentation Gaps

- Full JSON input/output examples should be added before public release.
- Runtime job records persist locally in ProjectStorage when a ProjectManager is available. Live records are merged with durable records; orphaned non-terminal records are visible but not controllable.
- Remote MCP transport/OAuth docs are future work.
