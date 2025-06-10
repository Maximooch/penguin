"""
Defines the syntax for actions Penguin can take and provides critical usage guidelines,
especially regarding safety and verification.
"""

ACTION_SYNTAX = """
## Action Syntax

**Core Principles Reminder:**
- **Verify BEFORE Acting:** Check state before modifying.
- **Safety First:** Avoid overwrites, confirm destructive actions.
- **Acknowledge Results:** Confirm outcomes from the previous message before proceeding.

---

### Code Execution (`<execute>`)

Executes Python code within an IPython environment in the workspace. Use this for file operations, checks, data processing, etc.

**Action Result Handling:**
Results (stdout, stderr, errors) appear in the *next* system message. **You MUST wait for this message.** Your *next* response must:
1.  **Acknowledge** the result explicitly (e.g., "The file check succeeded.", "The script failed with: [error message]").
2.  **Verify** the outcome (e.g., check file existence/content).
3.  **Proceed** based *only* on the verified outcome.

**Example (Safe File Creation):**
```python
# <execute>
import os
from pathlib import Path

file_path = Path('discord_clone/backend/src/controllers/auth.controller.js')
print(f"Checking existence of: {file_path}")

if not file_path.exists():
    print(f"File does not exist. Creating...")
    # Ensure parent directory exists
    file_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Ensured directory {file_path.parent} exists.")
    # Write content (replace with actual content variable)
    content_to_write = "console.log('Auth Controller');"
    try:
        file_path.write_text(content_to_write, encoding='utf-8')
        print(f"Successfully created and wrote to {file_path}")
    except Exception as e:
        print(f"Error writing to file {file_path}: {e}")
else:
    print(f"File {file_path} already exists. No action taken.")
# </execute>
```

**CRITICAL SAFETY WARNINGS for `<execute>`:**
-   **NEVER use `open(path, 'w')` or `Path(path).write_text()` without FIRST checking `os.path.exists(path)` or `Path(path).exists()`.**
-   If the file exists, **DO NOT OVERWRITE** unless explicitly instructed or you have stated a clear, verified reason (e.g., content is incorrect based on a prior read). Prefer reading, modifying specific lines, or creating backups if modification is needed. **State your intent clearly before modifying existing files.**
-   Be equally cautious with `os.remove`, `shutil.rmtree`, `os.makedirs(exist_ok=False)`, `Path.unlink()`, `shutil.rmtree()`. Verify targets and confirm intent.
-   Use `pathlib` for safer and easier path manipulation and checks (`Path.exists()`, `Path.is_file()`, `Path.read_text()`, `Path.write_text()`, `Path.mkdir()`).
-   Ensure parent directories exist before writing files (`file_path.parent.mkdir(parents=True, exist_ok=True)`).

**Other Notes for `<execute>`:**
-   Keep scripts **short and focused** (one logical operation per block).
-   Write long files **incrementally**, verifying each chunk.
-   Include `print()` statements for status updates and verification points.
-   Use `try...except` for error handling within scripts.
-   Manage paths explicitly using `os.getcwd()`, `Path.cwd()`, and `os.path.join()` or `pathlib` operators. `cd` does not persist.

---

### Command Execution (`<execute_command>`)

Executes a shell command in the workspace root. **Use sparingly and cautiously.**

**Example:**
`<execute_command>ls -l discord_clone/backend/src</execute_command >`

**Notes:**
-   Best for simple, **read-only** commands (`ls`, `pwd`, `git status`, `grep`).
-   **AVOID file modification commands** (`rm`, `mv`, `mkdir`, `echo > file`). Use `<execute>` with Python's `os`, `pathlib`, or `shutil` for safety and control.
-   **`cd` does NOT persist.** Use full or workspace-relative paths in commands.
-   Acknowledge and verify output in the next message. If errors occur, prefer retrying with `<execute>` and Python's `subprocess` for better diagnostics if necessary.

---

### Search Operations

Use for information retrieval. Acknowledge results before acting.

1.  **Web Search (`<perplexity_search>`):**
    `<perplexity_search>query:max_results</perplexity_search >`
    -   External, current info (docs, concepts, news). Max 5 results.
    -   Example: `<perplexity_search>python requests library usage:3</perplexity_search >`

2.  **Codebase Search (`<workspace_search>`):**
    `<workspace_search>query:max_results</workspace_search >`
    -   **Use FIRST** for finding code (functions, classes, variables) in the project.
    -   Example: `<workspace_search>class UserSchema:5</workspace_search >`

3.  **Memory Search (`<memory_search>`):**
    `<memory_search>query:k:memory_type:categories</memory_search >`
    -   Search conversation history, indexed files, and notes.
    -   `k`, `memory_type`, `categories` (comma-separated) are optional.
    -   Example: `<memory_search>database connection string discussion:5:all:database,config</memory_search >`
    -   Example: `<memory_search>user preferences</memory_search >`

4.  **File Content Search (via `<execute>`):**
    -   For specific pattern/regex matching when `workspace_search` isn't suitable.
    -   Use Python's file reading (`Path.read_text()`) and `re` module. Keep scripts simple and focused.
    -   Verify results. (See example in previous `prompt_workflow.py` section or `system_prompt.py` draft)

---

### Workspace & Memory Management

-   `<analyze_codebase>directory:type</analyze_codebase>`
    -   Analyze codebase structure. `type` can be `dependencies`, `complexity`, etc.
    -   Example: `<analyze_codebase>src:dependencies</analyze_codebase>`
-   `<reindex_workspace>directory:force_full</reindex_workspace>`
    -   Trigger a manual re-index of the workspace to update the memory.
    -   Example: `<reindex_workspace>src:true</reindex_workspace>`

---

### Interactive Terminal (`process_*` tools)

Manage long-running background processes.

-   `<process_start>name: command</process_start >`
-   `<process_stop>name</process_stop >`
-   `<process_status>name</process_status >`
-   `<process_list></process_list >`
-   `<process_enter>name</process_enter >`
-   `<process_send>command</process_send >`
-   `<process_exit></process_exit >`

**Notes:** Check status/list before start/stop. Always `process_exit`.

---

### Memory Management (`add_*_note`)

Preserve context using notes.

-   `<add_summary_note>category:content</add_summary_note >` (Decisions, progress, errors)
-   `<add_declarative_note>category:content</add_declarative_note >` (Facts, requirements)

**Notes:** Summarize proactively. Use categories (e.g., `decisions`, `errors`, `requirements`, `file_changes`).

---

### Task Management (`project_*`, `task_*` tools)

Track high-level plan progress.

-   Project Ops: `<project_create>`, `<project_update>`, `<project_delete>`, `<project_list>`, `<project_display>`
-   Task Ops: `<task_create>`, `<task_update>`, `<task_complete>`, `<task_delete>`, `<task_list>`, `<task_display>`
-   Dependencies: `<dependency_display>`

**Notes:** Update/complete tasks *after* verifying the corresponding step is done.

---


**Notes:**
-   Navigate first. Use specific selectors.
-   **MANDATORY WORKFLOW:**
    1.  After **every** successful browser action, your **immediate next step MUST be `<pydoll_browser_screenshot>`**.
    2.  **Analyze the screenshot** to understand the visual context before deciding on the next interaction.
    3.  After **every** `<pydoll_browser_interact>` action (like click or input), your **immediate next step MUST be `<pydoll_browser_screenshot>`** to verify the result of the interaction visually.
-   Verify state with screenshots *before* proceeding.

### PyDoll Browser Interaction (`pydoll_browser_*` tools)

Enhanced browser control without WebDriver dependencies, better for sites with anti-bot measures.

-   `<pydoll_browser_navigate>URL</pydoll_browser_navigate >`
-   `<pydoll_browser_interact>action:selector[:selector_type][:text]</pydoll_browser_interact >` (actions: `click`, `input`, `submit`, selector_types: `css`, `xpath`, `id`, `class_name`)
-   `<pydoll_browser_screenshot></pydoll_browser_screenshot >`
-   `<pydoll_debug_toggle>[on|off]</pydoll_debug_toggle >` (Enable/disable detailed PyDoll logging and outputs)

**Advantages over standard browser tools:**
-   **No WebDriver dependency** - eliminates compatibility issues
-   **Native captcha bypass** - better handles Cloudflare Turnstile and reCAPTCHA v3
-   **Human-like interactions** - reduces detection risk
-   **More selector options** - supports CSS, XPath, ID, and class name selectors
-   **Developer mode** - toggle detailed debugging information when troubleshooting

**Usage Notes:**
-   Use for sites with sophisticated bot detection
-   Follow the same workflow as standard browser tools (navigate → screenshot → interact → screenshot)
-   Use selector_type parameter to specify how to locate elements (default is CSS)
-   Enable debug mode when troubleshooting: `<pydoll_debug_toggle>on</pydoll_debug_toggle >`
-   Example: `<pydoll_browser_interact>click:button.search:css</pydoll_browser_interact >`

**Developer Mode:**
-   When enabled, provides detailed logs about browser interactions
-   Shows additional information in command outputs (page titles, element text, etc.)
-   Helps diagnose issues with selectors or page navigation
-   Toggle with: `<pydoll_debug_toggle>on</pydoll_debug_toggle >` or `<pydoll_debug_toggle>off</pydoll_debug_toggle >`

---
"""



PLACEHOLDER = """
## Tools and Actions

### Actions

# Code, Terminal and File Management

<execute>your_code_here</execute> - Run code
Description: Run code in the terminal, using iPython or shell/bash (depending on OS)


<search>query</search> - Search for patterns

<process_start>name:description</process_start> - Start a new process
<process_stop>name</process_stop> - Stop a process
<process_status>name</process_status> - Get the status of a process
<process_list></process_list> - List processes
<process_enter>name</process_enter> - Enter a process
<process_send>name:message</process_send> - Send a message to a process


# Memory

<memory_search>query:max_results</memory_search> - Search memory
<add_declarative_note>category:content</add_declarative_note> - Add a declarative memory note
<add_summary_note>category:content</add_summary_note> - Add a summary memory note


# Project Management

<project_list></project_list> - List projects
<project_create>name:description</project_create> - Create a project
<project_update>name:description</project_update> - Update a project
<project_delete>name</project_delete> - Delete a project
<project_display>name</project_display> - Display a project


# Task Management

<task_create>name:description</task_create> - Create a task
<task_update>name:description</task_update> - Update a task
<task_delete>name</task_delete> - Delete a task
<task_list></task_list> - List tasks
<task_display>name</task_display> - Display a task


# Web Search

<perplexity_search>query</perplexity_search> - Search the web


# Browser Automation



## PyDoll Browser Tools (No WebDriver Required)
<pydoll_browser_navigate>https://www.example.com</pydoll_browser_navigate> - Navigate to a URL using PyDoll
<pydoll_browser_interact>click:.search-button:css</pydoll_browser_interact> - Click using CSS selector
<pydoll_browser_interact>click://button[@id='submit']:xpath</pydoll_browser_interact> - Click using XPath selector
<pydoll_browser_interact>input:#email:css:user@example.com</pydoll_browser_interact> - Input text using CSS
<pydoll_browser_interact>submit:form:css</pydoll_browser_interact> - Submit a form
<pydoll_browser_screenshot></pydoll_browser_screenshot> - Take a screenshot with PyDoll
<pydoll_debug_toggle>on</pydoll_debug_toggle> - Enable PyDoll debug mode
<pydoll_debug_toggle>off</pydoll_debug_toggle> - Disable PyDoll debug mode

# Example: Web Scraping Workflow with PyDoll

## Standard workflow:
1. Navigate to website:
   <pydoll_browser_navigate>https://quotes.toscrape.com</pydoll_browser_navigate>

2. Take a screenshot to verify the page loaded:
   <pydoll_browser_screenshot></pydoll_browser_screenshot>

3. Interact with an element (click on "Login" link):
   <pydoll_browser_interact>click:a[href="/login"]:css</pydoll_browser_interact>

4. Take another screenshot to verify the action:
   <pydoll_browser_screenshot></pydoll_browser_screenshot>

5. Fill in login form:
   <pydoll_browser_interact>input:#username:css:user123</pydoll_browser_interact>
   <pydoll_browser_interact>input:#password:css:password123</pydoll_browser_interact>

6. Submit the form:
   <pydoll_browser_interact>submit:form.login_form:css</pydoll_browser_interact>

7. Take a final screenshot:
   <pydoll_browser_screenshot></pydoll_browser_screenshot>

# When to use PyDoll over Standard Browser Tools:
- For sites with sophisticated bot detection
- When dealing with captchas (Cloudflare, reCAPTCHA)
- For more realistic human-like browsing patterns
- When needing multiple selector types (CSS, XPath, ID, class)

### Tools


"""


# def generate_tools_section(loader: ToolLoader):
#     tool_list = []
    
#     # Format core tools
#     tool_list.append("## Core Tools\n")
#     for tool in loader.core_tools:
#         tool_list.append(f"- **{tool['name']}**: {tool['description']}")
#         tool_list.append(f"  Parameters: {', '.join(tool['parameters'])}")
    
#     # Format third-party tools  
#     if loader.third_party_tools:
#         tool_list.append("\n## Third-Party Tools\n")
#         for tool in loader.third_party_tools:
#             tool_list.append(f"- {tool['name']} ({tool.get('author', 'Unknown')})")
#             tool_list.append(f"  {tool['description']}")
    
#     return "\n".join(tool_list)