"""
Proposed Tools v2.0 - Comprehensive with Examples
Target: ~3,000 tokens
Clear descriptions + concrete usage examples for every tool
"""

# =============================================================================
# FILE EDITING TOOLS
# =============================================================================

FILE_EDITING_TOOLS = """
## File Editing

### apply_diff
Edit a single file using unified diff format. Creates automatic backup.

**When to use:** Making precise line-based changes to existing files.

**Format:** `<apply_diff>path:diff_content[:true|false]</apply_diff>`

**Example - Adding a function:**
```actionxml
<apply_diff>src/utils.py:--- a/src/utils.py
+++ b/src/utils.py
@@ -15,6 +15,10 @@
 def existing_func():
     return 42

+def new_helper():
+    \"\"\"Helper function.\"\"\"
+    return True
+
 def another_func():
     pass</apply_diff>
```

**Example - Modifying existing code:**
```actionxml
<apply_diff>config.py:--- a/config.py
+++ b/config.py
@@ -8,7 +8,7 @@
-DEBUG = True
+DEBUG = False
 PORT = 8080</apply_diff>
```

**Important:**
- Uses unified diff format with `@@ -start,count +start,count @@` headers
- Include 2-3 lines of context around changes
- `diff_content` may be multi-line and can be wrapped in ```diff fences
- Parser splits on the first `:` for the path; a trailing `:true`/`:false` with no newline toggles backup
- Automatic backup created (`.bak` file)


### multiedit
Apply multiple file edits atomically—all succeed or none are applied.

**When to use:** Coordinated changes across multiple files (e.g., renaming a function used in several places).

**Example:**
```actionxml
<multiedit>
apply=true
src/models.py:
@@ -25,7 +25,7 @@
-class UserManager:
+class UserService:
     def get_user(self, id):
         pass

src/api.py:
@@ -10,7 +10,7 @@
-from models import UserManager
+from models import UserService

-manager = UserManager()
+service = UserService()
</multiedit>
```

**Dry-run mode:** Omit `apply=true` to preview changes without applying.


### edit_with_pattern
Pattern-based find-and-replace using regex.

**When to use:** Simple replacements where diff format is overkill.

**Example:**
```actionxml
<edit_with_pattern>config.py:DEBUG = False:DEBUG = True:true</edit_with_pattern>
```

**Format:** `file_path:search_pattern:replacement:backup`


### replace_lines
Replace specific lines in a file with new content. Much simpler than apply_diff.

**When to use:** When you know exact line numbers to replace.

**Format:** `<replace_lines>path:start_line:end_line:new_content[:true|false]</replace_lines>`

**Example (multi-line replacement):**
```actionxml
<replace_lines>src/main.py:10:12:def new_function():
    \"\"\"Docstring.\"\"\"
    return calculate() * 2
</replace_lines>
```

**Notes:**
- `new_content` is inserted verbatim; include a trailing newline if you want to avoid concatenating the next line
- Parser splits on the first 3 `:` characters; additional `:` are treated as content
- A trailing `:true`/`:false` with no newline toggles verification

**Parameters:**
- `path` - File path
- `start_line` - First line to replace (1-indexed)
- `end_line` - Last line to replace (inclusive, 1-indexed)
- `new_content` - Content to insert
- `verify` - If True, confirms change with hash (default: true)

**Returns:** Success message with backup location and verification hash


### insert_lines
Insert new lines after a specific line.

**When to use:** Adding new code without replacing existing lines.

**Format:** `<insert_lines>path:after_line:new_content</insert_lines>`

**Example:**
```actionxml
<insert_lines>src/main.py:25:def new_helper():
    pass</insert_lines>
```

**Parameters:**
- `path` - File path
- `after_line` - Line number to insert after (0 = at beginning)
- `new_content` - Content to insert


### delete_lines
Delete a range of lines.

**When to use:** Removing code blocks by line number.

**Format:** `<delete_lines>path:start_line:end_line</delete_lines>`

**Example:**
```actionxml
<delete_lines>src/main.py:40:50</delete_lines>
```

**Parameters:**
- `path` - File path
- `start_line` - First line to delete (1-indexed)
- `end_line` - Last line to delete (inclusive, 1-indexed)
"""


# =============================================================================
# FILE OPERATIONS
# =============================================================================

FILE_OPERATION_TOOLS = """
## File Operations

### enhanced_read
Read file contents with exact path resolution and optional line numbers.

**When to use:** Reading source files, configs, or documentation.

**Example:**
```actionxml
<enhanced_read>src/main.py:true:50</enhanced_read>
```

**Parameters:**
- `path` - File to read
- `show_line_numbers` (true/false) - Include line numbers
- `max_lines` (optional) - Limit to first N lines


### enhanced_write
Write file with automatic backup and diff generation for existing files.

**When to use:** Creating new files or overwriting existing ones.

**Example:**
```actionxml
<enhanced_write>README.md:# Project Name

Description here.

## Usage
...
:true</enhanced_write>
```

**Parameters:**
- `path` - Target file path
- `content` - File contents
- `backup` (true/false) - Create `.bak` file if exists (default: true)


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

**Priority:** Prefer specialized tools (<apply_diff>, <enhanced_write>, etc.) first. Use <execute> when those don't work or for complex logic that requires Python.


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

**Example (isolated child):**
```actionxml
<spawn_sub_agent>{"id":"researcher","share_session":false,"share_context_window":false,"initial_prompt":"Summarize docs in /docs"}</spawn_sub_agent>
```

**Example (background child):**
```actionxml
<spawn_sub_agent>{"id":"analyzer","background":true,"initial_prompt":"Audit Python files for security issues"}</spawn_sub_agent>
```


### stop_sub_agent
Pause a sub-agent, cancelling a running background task when applicable.

**Format:** `<stop_sub_agent>{"id":"researcher"}</stop_sub_agent>`


### resume_sub_agent
Resume a previously paused sub-agent.

**Format:** `<resume_sub_agent>{"id":"researcher"}</resume_sub_agent>`


### delegate
Send a concrete task to an existing sub-agent.

**When to use:**
- Assign follow-up work to a named child
- Run background delegated tasks with optional waiting

**Format:** `<delegate>{...}</delegate>`

**Payload fields:**
- `child` (required) - Target agent id
- `content` (required) - Task text
- `parent` (optional) - Parent agent id
- `channel` (optional) - Logical room/channel
- `metadata` (optional) - Additional task metadata
- `background` (optional, default: `false`)
- `wait` (optional, default: `false`) - Only relevant when `background=true`
- `timeout` (optional float seconds) - Only relevant when `wait=true`

**Examples:**
```actionxml
<delegate>{"child":"researcher","content":"Audit README for missing setup steps.","channel":"dev-room"}</delegate>
```

```actionxml
<delegate>{"child":"researcher","content":"Analyze test coverage gaps.","background":true,"wait":true,"timeout":45}</delegate>
```


### delegate_explore_task
Spawn a lightweight exploration sub-agent that can list files, read files, and search,
then return a structured summary.

**Format:** `<delegate_explore_task>{...}</delegate_explore_task>`

**Payload fields:**
- `task` (required) - Exploration objective
- `directory` (optional) - Starting path (default: current)
- `max_iterations` (optional int) - Exploration rounds (capped)

**Example:**
```actionxml
<delegate_explore_task>{"task":"Map this repo architecture and identify entry points.","directory":".","max_iterations":40}</delegate_explore_task>
```
"""


# =============================================================================
# BROWSER AUTOMATION TOOLS
# =============================================================================

BROWSER_TOOLS = """
## Browser Automation (PyDoll)

Enhanced browser control without WebDriver dependencies. Better for sites with anti-bot measures.

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

**Examples:**
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

**Example:**
```actionxml
<pydoll_browser_scroll>to:bottom</pydoll_browser_scroll>
```

### pydoll_browser_screenshot
Capture a screenshot of the current page.

**Example:**
```actionxml
<pydoll_browser_screenshot></pydoll_browser_screenshot>
```

### pydoll_debug_toggle
Enable/disable detailed debugging.

**Example:**
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

### finish_response
**Purpose:** End the conversation turn.  
**When to use:** Done answering a question or providing information.  
**Tool call syntax:** `<finish_response></finish_response>`  
**Parameters:** None

### finish_task  
**Purpose:** Mark a formal task as complete.  
**When to use:** Finished implementing a feature or resolving a task.  
**Tool call syntax:** `<finish_task>status</finish_task>`  
**Parameters:**
- `status`: "done" (default), "partial", or "blocked"

**Important:** Call these tools explicitly. Never rely on implicit completion.
"""


# =============================================================================
# ASSEMBLE FULL TOOL GUIDE
# =============================================================================

TOOL_GUIDE = "\n\n".join(
    [
        FILE_EDITING_TOOLS,
        FILE_OPERATION_TOOLS,
        EXECUTION_TOOLS,
        SEARCH_TOOLS,
        MEMORY_TOOLS,
        TODO_TOOLS,
        QUESTION_TOOLS,
        AGENT_TOOLS,
        BROWSER_TOOLS,
        COMPLETION_TOOLS,
    ]
)


# Export for prompt builder
def get_tool_guide() -> str:
    """Get the complete tool documentation."""
    return TOOL_GUIDE
