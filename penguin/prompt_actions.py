"""Prompt-facing tool guidance.

Tool contracts and schemas should come from shared registry metadata.
This module remains the fast-tweak prompt layer for usage advice, examples, and
strategy notes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from penguin.tools.editing.registry import (
    get_edit_tool_aliases,
    get_edit_tool_schema,
    get_patch_files_item_schema,
    get_patch_operation_types,
)


__all__ = [
    "AGENT_TOOLS",
    "BROWSER_TOOLS",
    "COMPLETION_TOOLS",
    "EXECUTION_TOOLS",
    "FILE_EDITING_TOOLS",
    "FILE_OPERATION_TOOLS",
    "MCP_TOOL_GUIDANCE",
    "MEMORY_TOOLS",
    "QUESTION_TOOLS",
    "SEARCH_TOOLS",
    "SKILL_TOOLS",
    "TODO_TOOLS",
    "TOOL_INVOCATION_PROTOCOL",
    "get_tool_guide",
]


@dataclass(frozen=True)
class ToolPromptExample:
    title: str
    body: str


@dataclass(frozen=True)
class ToolPromptHint:
    when_to_use: str
    strategy_notes: List[str] = field(default_factory=list)
    examples: List[ToolPromptExample] = field(default_factory=list)
    migration_note: str = ""


def _format_code_items(items: List[str]) -> str:
    return ", ".join(f"`{item}`" for item in items)


def _native_example_payload(tool_name: str, body: str) -> str:
    opening = f"<{tool_name}>"
    closing = f"</{tool_name}>"
    if body.startswith(opening) and body.endswith(closing):
        return body[len(opening) : -len(closing)]
    return body


def _render_tool_examples(
    tool_name: str, examples: List[ToolPromptExample]
) -> str:
    blocks: List[str] = []
    for example in examples:
        native_payload = _native_example_payload(tool_name, example.body)
        blocks.append(
            "\n".join(
                [
                    f"**Native tool call example - {example.title}:**",
                    f"Call provider tool `{tool_name}` with:",
                    "```json",
                    native_payload,
                    "```",
                    "",
                    f"**ActionXML fallback - {example.title}:**",
                    "```actionxml",
                    example.body,
                    "```",
                ]
            )
        )
    return "\n\n".join(blocks)


def _render_schema_facts(tool_name: str) -> str:
    schema = get_edit_tool_schema(tool_name)
    input_schema = schema.get("input_schema", {})
    properties = input_schema.get("properties", {})
    required = list(input_schema.get("required", []))
    aliases = get_edit_tool_aliases(tool_name)

    lines = ["**Contract:**"]
    if required:
        lines.append(f"- Required fields: {_format_code_items(required)}")

    canonical_fields = [
        key
        for key in properties.keys()
        if key not in {"file_path", "content"} or tool_name == "write_file"
    ]
    if tool_name == "read_file":
        canonical_fields = ["path", "show_line_numbers", "max_lines"]
    elif tool_name == "write_file":
        canonical_fields = ["path", "content", "backup"]
    elif tool_name == "patch_file":
        canonical_fields = ["path", "operation", "backup"]
    elif tool_name == "patch_files":
        canonical_fields = ["operations", "apply", "backup"]
    lines.append(f"- Canonical fields: {_format_code_items(canonical_fields)}")

    if tool_name == "patch_file":
        lines.append(
            f"- Operation types: {_format_code_items(get_patch_operation_types())}"
        )
    if tool_name == "patch_files":
        item_schema = get_patch_files_item_schema()
        item_required = list(item_schema.get("required", []))
        if item_required:
            lines.append(
                f"- Each `operations[]` item requires {_format_code_items(item_required)}"
            )

    if aliases:
        lines.append(f"- Legacy aliases: {_format_code_items(aliases)}")

    return "\n".join(lines)


def _render_tool_section(tool_name: str, hint: ToolPromptHint) -> str:
    schema = get_edit_tool_schema(tool_name)
    lines = [
        f"### {tool_name}",
        schema["description"],
        "",
        f"**When to use:** {hint.when_to_use}",
        "",
        f"**Preferred path:** native provider tool call named `{tool_name}` when available.",
        f"**ActionXML fallback:** `<{tool_name}>{{...}}</{tool_name}>`",
    ]

    example_block = _render_tool_examples(tool_name, hint.examples)
    if example_block:
        lines.extend(["", example_block])

    lines.extend(["", _render_schema_facts(tool_name)])

    if hint.strategy_notes:
        lines.append("")
        lines.append("**Important:**")
        lines.extend(f"- {note}" for note in hint.strategy_notes)

    if hint.migration_note:
        lines.extend(["", f"**Migration note:** {hint.migration_note}"])

    return "\n".join(lines)


TOOL_INVOCATION_PROTOCOL = """
## Tool Invocation Protocol

Penguin supports two tool-call protocols:

1. Native provider tools: when the API/runtime exposes tools as function calls,
   call the named tool through that provider tool channel. Do not print XML tags
   for that tool call.
2. ActionXML fallback: when native tools are not available, call tools by
   emitting the documented `<tool_name>...</tool_name>` ActionXML block.

The tool names, arguments, and completion semantics are the same in both paths.
Use native tool calls first when they are available; use ActionXML only as the
compatibility fallback.
"""


MCP_TOOL_GUIDANCE = """
## MCP-Hosted Tools

Penguin may expose external Model Context Protocol (MCP) server tools as normal
runtime tools. MCP-hosted tools use model-safe names like
`mcp__server_name__tool_name`, for example `mcp__chrome_devtools__navigate` or
`mcp__github__list_issues`.

**How to use MCP tools:**
- Use MCP tools when the external server has the best capability for the task:
  browser/page inspection, GitHub/Sentry/Linear data, databases, local
  filesystem sandboxes, documentation servers, or other configured services.
- Treat every `mcp__*` tool as an external third-party capability. Prefer
  read-only inspection first, and ask/confirm before destructive, expensive, or
  privacy-sensitive actions.
- Do not invent MCP tool names. Use only names that are actually present in the
  active tool schema/listing, and follow each tool's schema exactly.
- Keep MCP calls narrowly scoped. Avoid broad queries or dumping huge external
  datasets into context; request specific fields, pages, issues, traces, or
  screenshots when possible.
- If an MCP call returns a file path, image path, or artifact reference, summarize
  it and read/load it only when needed for the user goal.
- If an MCP tool fails because a server is disconnected, stale, or missing a
  tool, report that clearly. When appropriate for debugging, use MCP status or
  refresh/reconnect surfaces instead of repeatedly retrying the same failed call.

**Browser MCP pattern:**
- Navigate first, then verify with title/URL/evaluate, then capture screenshots
  or inspect the DOM/network as needed.
- Use isolated or non-sensitive browser profiles for browser MCP tasks. Browser
  MCP servers can inspect and modify page/browser state.
- Screenshots may return image data or a local file path depending on the MCP
  server; handle either shape without assuming one fixed format.

**Security posture:** MCP is powerful glue, not magic safety dust. Server-level
allow/deny policy, output caps, and normal Penguin permission checks still
matter. When in doubt, be explicit about the external system being accessed and
what action will be taken.
"""


READ_FILE_HINT = ToolPromptHint(
    when_to_use="Reading source files, configs, or documentation.",
    strategy_notes=[
        "Use `show_line_numbers` when you plan to patch by line number.",
        "Use `max_lines` when you only need the top of a large file.",
    ],
    examples=[
        ToolPromptExample(
            title="Read a file with line numbers",
            body='<read_file>{"path":"src/main.py","show_line_numbers":true,"max_lines":50}</read_file>',
        )
    ],
    migration_note="Legacy `enhanced_read` remains accepted temporarily, but `read_file` is the canonical name.",
)


EDIT_TOOL_HINTS: Dict[str, ToolPromptHint] = {
    "write_file": ToolPromptHint(
        when_to_use="Creating new files or replacing full file contents.",
        strategy_notes=[
            "Prefer this when replacing an entire file instead of editing fragments.",
            "Use `backup=true` unless you have a specific reason not to.",
        ],
        examples=[
            ToolPromptExample(
                title="Write a file",
                body="""<write_file>{
  "path": "README.md",
  "content": "# Project Name\n\nDescription here.\n",
  "backup": true
}</write_file>""",
            )
        ],
        migration_note="Legacy `enhanced_write` and `write_to_file` payloads remain accepted temporarily, but JSON `write_file` is preferred.",
    ),
    "patch_file": ToolPromptHint(
        when_to_use="Any single-file edit, including unified diffs, regex replacements, and line-based edits.",
        strategy_notes=[
            "Prefer the nested `operation` object over flat legacy fields.",
            "Use `unified_diff` when you need precise context-aware edits.",
            "Use `regex_replace` or line operations when that is clearer than a diff.",
        ],
        examples=[
            ToolPromptExample(
                title="Unified diff",
                body="""<patch_file>{
  "path": "src/utils.py",
  "backup": true,
  "operation": {
    "type": "unified_diff",
    "diff_content": "--- a/src/utils.py\n+++ b/src/utils.py\n@@ -15,6 +15,10 @@\n def existing_func():\n     return 42\n \n+def new_helper():\n+    \\\"\\\"\\\"Helper function.\\\"\\\"\\\"\n+    return True\n+\n def another_func():\n     pass\n"
  }
}</patch_file>""",
            ),
            ToolPromptExample(
                title="Replace lines",
                body="""<patch_file>{
  "path": "src/main.py",
  "operation": {
    "type": "replace_lines",
    "start_line": 10,
    "end_line": 12,
    "new_content": "def new_function():\n    return calculate() * 2\n",
    "verify": true
  },
  "backup": true
}</patch_file>""",
            ),
        ],
        migration_note="Legacy `apply_diff`, `edit_with_pattern`, `replace_lines`, `insert_lines`, and `delete_lines` still work temporarily as compatibility aliases.",
    ),
    "patch_files": ToolPromptHint(
        when_to_use="Coordinated changes across multiple files that should be applied together.",
        strategy_notes=[
            "Prefer the structured `operations` array over raw patch text.",
            "Use `apply=false` for dry-run previews when you want to validate the plan first.",
        ],
        examples=[
            ToolPromptExample(
                title="Structured multi-file patch",
                body="""<patch_files>{
  "apply": true,
  "backup": true,
  "operations": [
    {
      "path": "src/models.py",
      "operation": {
        "type": "replace_lines",
        "start_line": 25,
        "end_line": 25,
        "new_content": "class UserService:",
        "verify": true
      }
    },
    {
      "path": "src/api.py",
      "operation": {
        "type": "regex_replace",
        "search_pattern": "UserManager",
        "replacement": "UserService"
      }
    }
  ]
}</patch_files>""",
            )
        ],
        migration_note="Legacy `multiedit` / `multiedit_apply` raw patch content still works temporarily, but the structured `operations` array is now canonical.",
    ),
}


def _build_file_editing_tools() -> str:
    sections = ["## File Editing"]
    for tool_name in ["write_file", "patch_file", "patch_files"]:
        sections.append(_render_tool_section(tool_name, EDIT_TOOL_HINTS[tool_name]))
    return "\n\n".join(sections)


FILE_EDITING_TOOLS = _build_file_editing_tools()


# =============================================================================
# FILE OPERATIONS
# =============================================================================

FILE_OPERATION_STATIC_TOOLS = """
### list_files_filtered
List directory contents with clutter filtering (.git, __pycache__, etc. hidden).

**When to use:** Exploring project structure.

**Example:**
```actionxml
<list_files_filtered>src:true:false</list_files_filtered>
```

**Parameters:**
- `path` - Directory to list
- `group_by_type` (true/false) - Group files by extension
- `show_hidden` (true/false) - Include hidden files


### find_files_enhanced
Find files using glob patterns.

**When to use:** Locating specific file types or names.

**Example:**
```actionxml
<find_files_enhanced>*.py:src:false:file</find_files_enhanced>
```

**Parameters:**
- `pattern` - Glob pattern (e.g., `*.py`, `test_*.py`)
- `search_path` - Directory to search
- `include_hidden` (true/false)
- `file_type` - "file" or "directory"


### enhanced_diff
Compare two files with contextual diff output.

**When to use:** Reviewing changes between file versions.

**Example:**
```actionxml
<enhanced_diff>old_config.py:new_config.py:true</enhanced_diff>
```

**Parameters:**
- `file1` - Original file
- `file2` - Modified file  
- `semantic` (true/false) - For Python, show function/class changes
"""


IMAGE_OPERATION_TOOLS = """
### read_image
Load a local image file into the conversation as model-visible multimodal content.

**When to use:** Inspecting screenshots, diagrams, UI captures, generated images,
or artifacts from MCP/browser/test tools that returned a local image path.

**Native tool call:** call `read_image` with `{"path":"path/to/image.png"}`.

**ActionXML fallback example:**
```actionxml
<read_image>{"path":"/path/to/screenshot.png","prompt":"Describe the visible UI state."}</read_image>
```

**Payload fields:**
- `path` (required) - Image file path within allowed project/workspace roots.
- `prompt` (optional) - Question/instruction to pair with the image.
- `max_dim` (optional) - Max-dimension hint for downstream image handling.

**Important:** Use `read_image` when you need to actually see an image. Reading a
filename or JSON artifact path is not enough; promote the image into conversation
context with this tool.
"""


def _build_file_operation_tools() -> str:
    return "\n\n".join(
        [
            "## File Operations",
            _render_tool_section("read_file", READ_FILE_HINT),
            FILE_OPERATION_STATIC_TOOLS,
            IMAGE_OPERATION_TOOLS,
        ]
    )


FILE_OPERATION_TOOLS = _build_file_operation_tools()


# =============================================================================
# EXECUTION TOOLS
# =============================================================================

EXECUTION_TOOLS = """
## Execution

**Agent mode awareness:**
- In `plan` mode, mutating operations are policy-blocked. Prioritize read-only analysis and planning.
- If a user asks for implementation in `plan` mode, provide a concrete plan and ask to switch to `build` mode.

### execute
Run Python code in IPython environment.

**When to use:** 
- Complex logic and data processing
- Installing libraries (`pip install`)
- Multi-step workflows that need variables/conditionals
- File operations **when specialized tools fail** (secondary/brute force option)
- Anything requiring Python stdlib (pathlib, os, json, etc.)

**Example:**
```actionxml
<execute>
import os
from pathlib import Path

config_path = Path('config.yml')
if config_path.exists():
    content = config_path.read_text()
    print(f"Config size: {len(content)} chars")
else:
    print("Config not found")
</execute>
```

**Priority:** Prefer specialized tools (<patch_file>, <patch_files>, <write_file>, etc.) first. Use <execute> when those don't work or for complex logic that requires Python.


### execute_command
Run shell commands.

**When to use:** Git operations, running tests, build commands.

**Example:**
```actionxml
<execute_command>pytest tests/test_auth.py -xvs</execute_command>
```

**Caution:** Use <execute> (Python) for file modifications when possible. Shell `cd` does not persist between calls—use full paths.


### process_start
Start a long-running background process.

**When to use:** Starting dev servers, background workers.

**Example:**
```actionxml
<process_start>dev-server: npm run dev</process_start>
```


### process_stop
Stop a running background process.

**Example:**
```actionxml
<process_stop>dev-server</process_stop>
```


### process_status / process_list
Check if process is running or list all processes.
"""


# =============================================================================
# SEARCH TOOLS
# =============================================================================

SEARCH_TOOLS = """
## Search

### search
Grep-like regex search across project files.

**When to use:** Finding code patterns, function definitions, TODOs.

**Example:**
```actionxml
<search>def\\s+authenticate|class\\s+Auth</search>
```

**Pattern syntax:** Python regex. Use `|` to OR multiple patterns.


### perplexity_search
Web search via Perplexity API.

**When to use:** Researching documentation, best practices, current information.

**Example:**
```actionxml
<perplexity_search>FastAPI dependency injection best practices:3</perplexity_search>
```

**Parameters:**
- `query` - Search query
- `max_results` (1-5) - Number of results


### memory_search
Search conversation history and indexed notes.

**When to use:** Recalling previous discussions, requirements, decisions.

**Example:**
```actionxml
<memory_search>database connection string:5:all:database,config</memory_search>
```

**Parameters:**
- `query` - Search terms
- `k` - Number of results
- `memory_type` - "conversation", "notes", or "all"
- `categories` - Filter by category tags


### analyze_project
Analyze codebase structure using AST parsing.

**When to use:** Understanding large codebases, dependency mapping.

**Example:**
```actionxml
<analyze_project>src:false</analyze_project>
```

**Output:** File stats, imports, functions, classes.
"""


# =============================================================================
# MEMORY & NOTES
# =============================================================================

MEMORY_TOOLS = """
## Memory & Notes

### add_summary_note
Record decisions, progress, or key takeaways.

**When to use:** Capturing why a decision was made, tracking progress, recording errors.

**Example:**
```actionxml
<add_summary_note>decisions:Chose SQLite over PostgreSQL for simplicity in MVP phase</add_summary_note>
```

**Categories:** decisions, progress, errors, architecture


### add_declarative_note
Record facts, requirements, or constraints.

**When to use:** Storing user preferences, system requirements, API contracts.

**Example:**
```actionxml
<add_declarative_note>requirements:API must support rate limiting of 100 req/min</add_declarative_note>
```

**Categories:** requirements, constraints, preferences, api_contracts


### reindex_workspace
Manually trigger workspace re-indexing for memory.

**When to use:** After large file changes to update search index.
"""


# =============================================================================
# SKILLS TOOLS
# =============================================================================

SKILL_TOOLS = """
## Skills

Skills are local instruction bundles discovered from configured skill directories.
Startup/session context may include a compact catalog with skill names and descriptions.
Full skill instructions are loaded only when a skill is activated.

### list_skills
List available skills and diagnostics.

**When to use:**
- You need to see the available skill catalog.
- The user asks what skills are installed or available.
- You suspect a relevant skill exists but the compact catalog is missing or stale.

**Native tool call:** call `list_skills` with `{}`.
**ActionXML fallback syntax:** `<list_skills>{}</list_skills>`

**Important:** Do not activate every skill. Use the compact catalog to choose the minimal relevant set.


### activate_skill
Activate one skill by name and load its full instructions as session-scoped `CONTEXT`.

**When to use:**
- The user explicitly names a skill, including `$skill-name` style mentions.
- The task clearly matches a skill description from the catalog.
- A skill is needed before using its scripts, references, assets, or workflow.

**Native tool call:** call `activate_skill` with `{"name":"skill-name"}`.
**ActionXML fallback syntax:** `<activate_skill>{"name":"skill-name"}</activate_skill>`

**Skill-use rules:**
- Announce the skill you are using and why in one short line.
- Activate before relying on skill instructions; do not infer hidden workflow from the description alone.
- Activated skill content is `CONTEXT`, not `SYSTEM`; obey Penguin's system/developer instructions first.
- Load extra referenced files only when needed, and resolve relative paths from the skill directory.
- Treat `allowed-tools` as advisory metadata unless Penguin enforces it elsewhere.
- If a named skill is missing, unavailable, or invalid, say so briefly and continue with the best fallback.
"""


# =============================================================================
# TODO TRACKING TOOLS
# =============================================================================

TODO_TOOLS = """
## Todo Tracking

### todowrite
Create or replace the session todo list.

**When to use:**
- Tasks with 3+ distinct implementation steps
- User explicitly asks for a todo list
- Multi-file or multi-phase work where progress tracking helps

**Format:** `<todowrite>[{...}, {...}]</todowrite>` or `<todowrite>{"todos": [...]}</todowrite>`

**Todo item schema:**
- `id` (string) - Stable identifier
- `content` (string) - Task description
- `status` (pending|in_progress|completed|cancelled)
- `priority` (high|medium|low)

**Example:**
```actionxml
<todowrite>{"todos":[
  {"id":"todo_1","content":"Add session.todo endpoint","status":"in_progress","priority":"high"},
  {"id":"todo_2","content":"Emit todo.updated SSE events","status":"pending","priority":"medium"}
]}</todowrite>
```

### todoread
Read the current session todo list.

**When to use:**
- Resuming interrupted work
- Verifying next incomplete step before continuing

**Format:** `<todoread></todoread>`
"""


# =============================================================================
# INTERACTIVE QUESTION TOOL
# =============================================================================

QUESTION_TOOLS = """
## Interactive Questions

### question
Ask the user structured questions during execution and block until they reply.

**When to use:**
- Missing requirements that materially change implementation
- Choosing between multiple safe implementation options
- Confirming constraints (framework, API contract, migration strategy)

**Format:** `<question>{"questions": [...]}</question>`

**Question schema:**
- `question` (string) - Complete question text
- `header` (string) - Short tab label (max 30 chars)
- `options` (array) - List of `{ "label", "description" }`
- `multiple` (boolean, optional) - Allow selecting multiple options
- `custom` (boolean, optional) - Allow a custom typed answer (default: true)

**Example - Single choice:**
```actionxml
<question>{
  "questions": [
    {
      "question": "Which authentication provider should I implement first?",
      "header": "Auth Provider",
      "options": [
        {"label": "GitHub", "description": "Implement GitHub OAuth first"},
        {"label": "Google", "description": "Implement Google OAuth first"}
      ]
    }
  ]
}</question>
```

**Example - Multiple questions:**
```actionxml
<question>{
  "questions": [
    {
      "question": "Which database should be the default?",
      "header": "Database",
      "options": [
        {"label": "Postgres", "description": "Use PostgreSQL"},
        {"label": "SQLite", "description": "Use SQLite"}
      ]
    },
    {
      "question": "Which environments should get migrations now?",
      "header": "Environments",
      "multiple": true,
      "options": [
        {"label": "dev", "description": "Apply in development"},
        {"label": "staging", "description": "Apply in staging"},
        {"label": "prod", "description": "Apply in production"}
      ]
    }
  ]
}</question>
```

**Important:**
- Keep labels concise and unambiguous
- Do not include a generic "Other" option when custom input is enabled
- The tool pauses execution until the user replies or rejects
"""


# =============================================================================
# MULTI-AGENT / MESSAGING TOOLS
# =============================================================================

AGENT_TOOLS = """
## Multi-Agent & Messaging

### send_message
Send a message to another agent, a group of agents, or the human operator.

**When to use:**
- Agent-to-agent coordination
- Broadcasting progress updates
- Asking the user for clarification from an agent workflow

**Format:** `<send_message>{...}</send_message>`

**Payload fields:**
- `content` (required) - Message body
- `target` (optional) - Single recipient agent id
- `targets` (optional) - Multiple recipient agent ids
- `recipient` (optional) - Alias for `target`
- `message_type` (optional) - `message` (default), `status`, `action`, `event`
- `channel` (optional) - Logical room identifier
- `metadata` (optional) - Additional key/value data
- `sender` (optional) - Override sender label

**Examples:**
```actionxml
<send_message>{"target":"planner","content":"Implementation complete. Please review.","channel":"dev-room"}</send_message>
```

```actionxml
<send_message>{"targets":["planner","qa"],"content":"Build passed and tests are green.","message_type":"status"}</send_message>
```

**Note:** Message routing is push-based. There is no dedicated inbox polling action tag.


### spawn_sub_agent
Create a child agent for isolated or shared-session work.

**When to use:**
- Split work into parallel streams
- Isolate exploration/research from the main thread
- Create specialized helpers with focused instructions

**Format:** `<spawn_sub_agent>{...}</spawn_sub_agent>`

**Payload fields:**
- `id` (required) - Child agent id
- `parent` (optional) - Parent agent id (defaults to current agent)
- `persona`, `system_prompt` (optional)
- `share_session` (optional, default: `false`)
- `share_context_window` (optional, default: `false`)
- `shared_context_window_max_tokens` (optional int)
- `model_config_id`, `model_overrides`, `model_output_max_tokens` (optional)
- `default_tools` (optional list; metadata only)
- `initial_prompt` (optional)
- `background` (optional, default: `false`)

**Native tool call example (isolated child):** call `spawn_sub_agent` with
`{"id":"researcher","share_session":false,"share_context_window":false,"initial_prompt":"Summarize docs in /docs"}`.

**ActionXML fallback example (isolated child):**
```actionxml
<spawn_sub_agent>{"id":"researcher","share_session":false,"share_context_window":false,"initial_prompt":"Summarize docs in /docs"}</spawn_sub_agent>
```

**Native tool call example (background child):** call `spawn_sub_agent` with
`{"id":"analyzer","background":true,"initial_prompt":"Audit Python files for security issues"}`.

**ActionXML fallback example (background child):**
```actionxml
<spawn_sub_agent>{"id":"analyzer","background":true,"initial_prompt":"Audit Python files for security issues"}</spawn_sub_agent>
```


### stop_sub_agent
Pause a sub-agent, cancelling a running background task when applicable.

**Native tool call:** call `stop_sub_agent` with `{"id":"researcher"}`.
**ActionXML fallback syntax:** `<stop_sub_agent>{"id":"researcher"}</stop_sub_agent>`


### resume_sub_agent
Resume a previously paused sub-agent.

**Native tool call:** call `resume_sub_agent` with `{"id":"researcher"}`.
**ActionXML fallback syntax:** `<resume_sub_agent>{"id":"researcher"}</resume_sub_agent>`


### get_agent_status
Query background sub-agent status for one agent or all running agents.

**Native tool call:** call `get_agent_status` with the fields below.
**ActionXML fallback syntax:** `<get_agent_status>{...}</get_agent_status>`

**Payload fields:**
- `id` (optional) - Agent ID to query
- `agent_id` (optional alias for `id`)
- `include_result` (optional, default: `false`) - Include completed result payload

**ActionXML fallback examples:**
```actionxml
<get_agent_status>{"id":"analyzer"}</get_agent_status>
```

```actionxml
<get_agent_status>{"include_result":true}</get_agent_status>
```


### wait_for_agents
Wait for one or more background sub-agents to complete.

**Native tool call:** call `wait_for_agents` with the fields below.
**ActionXML fallback syntax:** `<wait_for_agents>{...}</wait_for_agents>`

**Payload fields:**
- `ids` (optional list) - Agent IDs to wait for (all if omitted)
- `agent_ids` (optional alias for `ids`)
- `timeout` (optional float seconds)

**ActionXML fallback example:**
```actionxml
<wait_for_agents>{"ids":["analyzer","researcher"],"timeout":60}</wait_for_agents>
```


### get_context_info
Inspect context-window sharing details for an agent.

**Native tool call:** call `get_context_info` with the fields below.
**ActionXML fallback syntax:** `<get_context_info>{...}</get_context_info>`

**Payload fields:**
- `id` (optional) - Agent ID (defaults to current/default)
- `agent_id` (optional alias for `id`)
- `include_stats` (optional, default: `false`) - Include token stats


### sync_context
Synchronize context from a parent agent to a child agent.

**Native tool call:** call `sync_context` with the fields below.
**ActionXML fallback syntax:** `<sync_context>{...}</sync_context>`

**Payload fields:**
- `parent` (required) - Parent/source agent
- `child` (required) - Child/destination agent
- `parent_agent_id` / `child_agent_id` (optional aliases)
- `replace` (optional, default: `false`) - Replace existing child context


### delegate
Send a concrete task to an existing sub-agent.

**When to use:**
- Assign follow-up work to a named child
- Run background delegated tasks with optional waiting

**Native tool call:** call `delegate` with the fields below.
**ActionXML fallback syntax:** `<delegate>{...}</delegate>`

**Payload fields:**
- `child` (required) - Target agent id
- `content` (required) - Task text
- `parent` (optional) - Parent agent id
- `channel` (optional) - Logical room/channel
- `metadata` (optional) - Additional task metadata
- `background` (optional, default: `false`)
- `wait` (optional, default: `false`) - Only relevant when `background=true`
- `timeout` (optional float seconds) - Only relevant when `wait=true`

**ActionXML fallback examples:**
```actionxml
<delegate>{"child":"researcher","content":"Audit README for missing setup steps.","channel":"dev-room"}</delegate>
```

```actionxml
<delegate>{"child":"researcher","content":"Analyze test coverage gaps.","background":true,"wait":true,"timeout":45}</delegate>
```


### delegate_explore_task
Spawn a lightweight exploration sub-agent that can list files, read files, and search,
then return a structured summary.

**Native tool call:** call `delegate_explore_task` with the fields below.
**ActionXML fallback syntax:** `<delegate_explore_task>{...}</delegate_explore_task>`

**Payload fields:**
- `task` (required) - Exploration objective
- `directory` (optional) - Starting path (default: current)
- `max_iterations` (optional int) - Exploration rounds (capped)

**ActionXML fallback example:**
```actionxml
<delegate_explore_task>{"task":"Map this repo architecture and identify entry points.","directory":".","max_iterations":40}</delegate_explore_task>
```
"""


# =============================================================================
# BROWSER AUTOMATION TOOLS
# =============================================================================

BROWSER_TOOLS = """
## Browser Automation

Penguin has two browser paths:
- `browser_*` tools backed by browser-harness when available. Prefer these for
  real logged-in Chrome sessions, screenshot-first workflows, and CDP escape hatches.
- `pydoll_browser_*` tools as the compatibility/fallback path.

**Default workflow:** open or identify the page → screenshot/page info → act with
coordinates or focused input → wait → screenshot/verify. Do not assume DOM state
from text alone when the visual state matters.

For documentation/static scraping, prefer scripting/HTTP/JS extraction over manual
browser interaction. Actual browser interaction is strongest for testing software
Penguin made, authenticated workflows, and dynamic UI verification.

If `browser_open_tab` or `browser_page_info` returns `domain_skills.matches`,
use those paths as opt-in references only when the current hostname-specific
problem needs them. Do not bulk-load or summarize all domain-skill files.

### browser_status
Report browser-harness identity, ownership, dependency, connection, and optional page state.

**Native tool call:** call `browser_status` with `{}` or `{"include_page":false}`.

**ActionXML fallback example:**
```actionxml
<browser_status>{"include_page":true}</browser_status>
```

Use this when browser setup fails, subagents may be sharing state accidentally,
or you need to verify the active `BU_NAME`/session/agent identity.

### browser_open_tab
Open a URL in a new browser-harness tab.

**Native tool call:** call `browser_open_tab` with `{"url":"https://example.com"}`.

**ActionXML fallback example:**
```actionxml
<browser_open_tab>{"url":"https://example.com","wait":true}</browser_open_tab>
```

### browser_page_info
Return active tab URL/title and page metadata.

**Native tool call:** call `browser_page_info` with `{}`.

**ActionXML fallback example:**
```actionxml
<browser_page_info>{}</browser_page_info>
```

### browser_harness_screenshot
Capture visible browser state as an image artifact and add it to conversation
when used through ActionXML.

**Native tool call:** call `browser_harness_screenshot` with `{}`.

**ActionXML fallback example:**
```actionxml
<browser_harness_screenshot>{"description":"What is visible on this page?"}</browser_harness_screenshot>
```

**Important:** If a screenshot or other tool returns only an image path/artifact,
use `read_image` to make that image visible in a later turn.

### browser_click
Click browser viewport coordinates. Prefer this after inspecting a screenshot.

**Native tool call:** call `browser_click` with `{"x":100,"y":200}`.

**ActionXML fallback example:**
```actionxml
<browser_click>{"x":100,"y":200,"button":"left","clicks":1}</browser_click>
```

### browser_type / browser_key / browser_fill
Enter text, press keys, or fill a selector-backed input.

**Native tool call examples:**
- `browser_type` with `{"text":"hello"}`
- `browser_key` with `{"key":"Enter"}`
- `browser_fill` with `{"selector":"#email","text":"user@example.com"}`

**ActionXML fallback examples:**
```actionxml
<browser_type>{"text":"hello"}</browser_type>
<browser_key>{"key":"Enter"}</browser_key>
<browser_fill>{"selector":"#email","text":"user@example.com"}</browser_fill>
```

### browser_wait
Wait for load, element, network idle, or a short sleep.

**Native tool call:** call `browser_wait` with
`{"mode":"load"}` / `{"mode":"element","selector":"#done"}` /
`{"mode":"network_idle"}` / `{"mode":"sleep","seconds":1}`.

**ActionXML fallback example:**
```actionxml
<browser_wait>{"mode":"element","selector":"#done","timeout":10,"visible":true}</browser_wait>
```

### browser_js
Evaluate JavaScript in the active tab. Use this as an escape hatch after visual
inspection, not as a replacement for user-visible verification.

**Native tool call:** call `browser_js` with `{"expression":"document.title"}`.

**ActionXML fallback example:**
```actionxml
<browser_js>{"expression":"document.title"}</browser_js>
```

### browser_list_tabs / browser_switch_tab
Inspect and switch browser-harness tabs.

**Native tool call examples:**
- `browser_list_tabs` with `{}`
- `browser_switch_tab` with `{"target_id":"..."}`

**ActionXML fallback examples:**
```actionxml
<browser_list_tabs>{}</browser_list_tabs>
<browser_switch_tab>{"target_id":"target-1"}</browser_switch_tab>
```

### PyDoll Compatibility Tools

Enhanced browser control without WebDriver dependencies. Better for sites with
anti-bot measures when browser-harness is unavailable or inappropriate.

### pydoll_browser_navigate
Navigate to a URL.

**Example:**
```actionxml
<pydoll_browser_navigate>https://example.com</pydoll_browser_navigate>
```

### pydoll_browser_interact
Interact with page elements (click, input, submit).

**Actions:** click, input, submit  
**Selector types:** css, xpath, id, class_name

**Native tool calls are preferred. ActionXML fallback examples:**
```actionxml
<pydoll_browser_interact>click:button.submit:css</pydoll_browser_interact>
<pydoll_browser_interact>input:search-box:id:search query</pydoll_browser_interact>
<pydoll_browser_interact>submit:form#login:xpath</pydoll_browser_interact>
```

### pydoll_browser_scroll
Scroll the page.

**Modes:**
- `to:bottom` - Scroll to bottom
- `page:down:2` - Page down twice
- `by:1200:0:1` - Scroll by x,y pixels, speed
- `element:#results:css:smooth` - Scroll to element

**ActionXML fallback example:**
```actionxml
<pydoll_browser_scroll>to:bottom</pydoll_browser_scroll>
```

### pydoll_browser_screenshot
Capture a screenshot of the current page.

**ActionXML fallback example:**
```actionxml
<pydoll_browser_screenshot></pydoll_browser_screenshot>
```

### pydoll_debug_toggle
Enable/disable detailed debugging.

**ActionXML fallback example:**
```actionxml
<pydoll_debug_toggle>on</pydoll_debug_toggle>
```

**When to use PyDoll:**
- Sites with sophisticated bot detection (Cloudflare, reCAPTCHA v3)
- When standard browser tools fail
- Need human-like interactions

**Workflow:** Navigate → Screenshot → Interact → Screenshot (verify result)
"""


# =============================================================================
# COMPLETION SIGNALS
# =============================================================================

COMPLETION_TOOLS = """
## Completion Signals

**Call these tools to signal completion. Do not output them as text.**

If native provider tools are available, call `finish_response` or `finish_task`
through the provider tool channel. If only ActionXML is available, use the XML
syntax shown below.

### finish_response
**Purpose:** End the conversation turn.
**When to use:** Done answering a question or providing information.
**Native tool call:** call `finish_response` with no parameters.
**ActionXML fallback syntax:** `<finish_response></finish_response>`
**Parameters:** None

**Important:** Put the final answer in normal assistant content before calling `finish_response`. Do not pass summary text here; summaries belong on `finish_task`.

### finish_task  
**Purpose:** Signal that formal task work is ready for human review.
**When to use:** Acceptance criteria are satisfied, or progress is partial/blocked and should stop.
**Native tool call:** call `finish_task` with `status` and optional `summary`.
**ActionXML fallback syntax:** `<finish_task>{"status":"done","summary":"What changed and how it was verified"}</finish_task>`
**Parameters:** JSON object or plain status string. Prefer JSON.
- `status`: "done" (default), "partial", or "blocked"
- `summary`: short review note describing what was accomplished

**Important:** Call this tool explicitly. Do not emit `TASK_COMPLETED` as plain text; that phrase is legacy compatibility only.
"""


# =============================================================================
# ASSEMBLE FULL TOOL GUIDE
# =============================================================================


def get_tool_guide() -> str:
    """Get the complete tool documentation."""
    return "\n\n".join(
        [
            TOOL_INVOCATION_PROTOCOL,
            MCP_TOOL_GUIDANCE,
            _build_file_editing_tools(),
            _build_file_operation_tools(),
            EXECUTION_TOOLS,
            SEARCH_TOOLS,
            MEMORY_TOOLS,
            TODO_TOOLS,
            SKILL_TOOLS,
            QUESTION_TOOLS,
            AGENT_TOOLS,
            BROWSER_TOOLS,
            COMPLETION_TOOLS,
        ]
    )
