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

**Example - Adding a function:**
```
`apply_diff`src/utils.py:--- a/src/utils.py
+++ b/src/utils.py
@@ -15,6 +15,10 @@
 def existing_func():
     return 42

+def new_helper():
+    \"\"\"Helper function.\"\"\"
+    return True
+
 def another_func():
     pass`apply_diff`
```

**Example - Modifying existing code:**
```
`apply_diff`config.py:--- a/config.py
+++ b/config.py
@@ -8,7 +8,7 @@
-DEBUG = True
+DEBUG = False
 PORT = 8080`apply_diff`
```

**Important:**
- Uses unified diff format with `@@ -start,count +start,count @@` headers
- Include 2-3 lines of context around changes
- Automatic backup created (`.bak` file)


### multiedit
Apply multiple file edits atomically—all succeed or none are applied.

**When to use:** Coordinated changes across multiple files (e.g., renaming a function used in several places).

**Example:**
```
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
+service = UserService()</multiedit>
```

**Dry-run mode:** Omit `apply=true` to preview changes without applying.


### edit_with_pattern
Pattern-based find-and-replace using regex.

**When to use:** Simple replacements where diff format is overkill.

**Example:**
```
<edit_with_pattern>config.py:DEBUG = False:DEBUG = True:true</edit_with_pattern>
```

**Format:** `file_path:search_pattern:replacement:backup`


### replace_lines
Replace specific lines in a file with new content. Much simpler than apply_diff.

**When to use:** When you know exact line numbers to replace.

**Example:**
```
<replace_lines>src/main.py:10:15:new function content here</replace_lines>
```

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

**Example:**
```
`insert_lines`src/main.py:25:def new_helper():
    pass`insert_lines`
```

**Parameters:**
- `path` - File path
- `after_line` - Line number to insert after (0 = at beginning)
- `new_content` - Content to insert


### delete_lines
Delete a range of lines.

**When to use:** Removing code blocks by line number.

**Example:**
```
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
```
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
```
<enhanced_write>README.md:# Project Name

Description here.

## Usage
...
:true<enhanced_write>
```

**Parameters:**
- `path` - Target file path
- `content` - File contents
- `backup` (true/false) - Create `.bak` file if exists (default: true)


### list_files_filtered
List directory contents with clutter filtering (.git, __pycache__, etc. hidden).

**When to use:** Exploring project structure.

**Example:**
```
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
```
<find_files_enhanced>*.py:src:false:file<find_files_enhanced>
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
```
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

### execute
Run Python code in IPython environment.

**When to use:** 
- Complex logic and data processing
- Installing libraries (`pip install`)
- Multi-step workflows that need variables/conditionals
- File operations **when specialized tools fail** (secondary/brute force option)
- Anything requiring Python stdlib (pathlib, os, json, etc.)

**Example:**
```
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
```
<execute_command>pytest tests/test_auth.py -xvs</execute_command>
```

**Caution:** Use <execute> (Python) for file modifications when possible. Shell `cd` does not persist between calls—use full paths.


### process_start
Start a long-running background process.

**When to use:** Starting dev servers, background workers.

**Example:**
```
<process_start>dev-server: npm run dev</process_start>
```


### process_stop
Stop a running background process.

**Example:**
```
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
```
<search>def\\s+authenticate|class\\s+Auth</search>
```

**Pattern syntax:** Python regex. Use `|` to OR multiple patterns.


### perplexity_search
Web search via Perplexity API.

**When to use:** Researching documentation, best practices, current information.

**Example:**
```
<perplexity_search>FastAPI dependency injection best practices:3<perplexity_search>
```

**Parameters:**
- `query` - Search query
- `max_results` (1-5) - Number of results


### memory_search
Search conversation history and indexed notes.

**When to use:** Recalling previous discussions, requirements, decisions.

**Example:**
```
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
```
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
```
<add_summary_note>decisions:Chose SQLite over PostgreSQL for simplicity in MVP phase</add_summary_note>
```

**Categories:** decisions, progress, errors, architecture


### add_declarative_note
Record facts, requirements, or constraints.

**When to use:** Storing user preferences, system requirements, API contracts.

**Example:**
```
<add_declarative_note>requirements:API must support rate limiting of 100 req/min</add_declarative_note>
```

**Categories:** requirements, constraints, preferences, api_contracts


### reindex_workspace
Manually trigger workspace re-indexing for memory.

**When to use:** After large file changes to update search index.
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
```
<pydoll_browser_navigate>https://example.com</pydoll_browser_navigate>
```

### pydoll_browser_interact
Interact with page elements (click, input, submit).

**Actions:** click, input, submit  
**Selector types:** css, xpath, id, class_name

**Examples:**
```
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
```
<pydoll_browser_scroll>to:bottom</pydoll_browser_scroll>
```

### pydoll_browser_screenshot
Capture a screenshot of the current page.

**Example:**
```
<pydoll_browser_screenshot></pydoll_browser_screenshot>
```

### pydoll_debug_toggle
Enable/disable detailed debugging.

**Example:**
```
`pydoll_debug_toggle`on`pydoll_debug_toggle`
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

TOOL_GUIDE = "\n\n".join([
    FILE_EDITING_TOOLS,
FILE_OPERATION_TOOLS,
EXECUTION_TOOLS,
SEARCH_TOOLS,
MEMORY_TOOLS,
    COMPLETION_TOOLS,
])

# Export for prompt builder
def get_tool_guide() -> str:
    """Get the complete tool documentation."""
    return TOOL_GUIDE
