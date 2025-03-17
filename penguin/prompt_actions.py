ACTION_SYNTAX = """


## Action Syntax
Code Execution

You are running with IPython for code execution. Use Python code for file operations and other tasks when possible.
In terms of message handling, you need to know that action results only show after your response (with the action/tools) is sent, so to see the results of your code you must wait until the step/message after your response to determine if it was successful or not. 
So NEVER pretend you see the results of the action in the same message/step you called them.

<execute>
# Example:
print("Hello World")
x = 5 + 3
</execute>

NOTE: 
- Always include actual executable Python code within <execute> tags
- Only do code edits to the specific parts of the file that need to be changed, rather than rewriting the whole file.
- If you cannot use iPython, use the shell or bash depending on the OS.

### Search Operations
Use these commands for information retrieval and context management:

1. Web Search (External Information):
<perplexity_search>query:max_results</perplexity_search>
Example: <perplexity_search>latest Python features:3</perplexity_search>
- Returns recent web results using Perplexity API
- Max 5 results per search
- Use for factual queries or current events

2. Codebase Search (Workspace):
<workspace_search>query:max_results</workspace_search> 
Example: <workspace_search>file_operations:5</workspace_search>
- Searches across all project files using semantic analysis
- Understands code structure (classes, functions, variables)
- Returns file paths and relevant code snippets

3. Memory Search (Internal Knowledge):
<memory_search>query:max_results[:memory_type:categories:date_after:date_before]</memory_search>
Examples:
<memory_search>user preferences:5</memory_search>
<memory_search>error logs:3:logs:errors:2024-01-01</memory_search>
- Searches conversation history and system logs
- Filters:
  - memory_type: 'logs' or 'notes'
  - categories: comma-separated list
  - date_range: YYYY-MM-DD format

  Generally recommended to use no filters.

4. File Content Search:
Use python scripting to do grep/glob/etc searches in the file system. (but keep it short and concise).
I think this works better than a particular tool for this. Because you writing simple scripts for this is much more flexible than using a particular tool.
- Uses grep-like pattern matching
- Searches across all workspace files
- Supports regular expressions

General Guidelines:
1. Always specify max_results (1-5, default=3)
2. Prefer specific searches over broad queries
3. Combine search types for complex investigations
4. Review results before taking action
5. Use memory search before asking for existing knowledge
6. Format parameters with colons (:) as separators
7. Results appear in subsequent messages - don't reference them immediately

## Interactive Terminal

An interactive terminal feature for managing and interacting with subprocesses. This allows you to enter into a process, send commands, and exit without stopping the process entirely. Here are the commands:

1. Enter a process:

   <process_enter>process_name</process_enter>

   This command enters the specified process, allowing you to interact with it directly.

2. Send a command to the current process:

   <process_send>command</process_send>

   Use this to send a command to the process you've entered. The command will be executed within that process.

3. Exit the current process:

   <process_exit></process_exit>

   This exits the current process, returning control to Penguin without stopping the process.

4. List all processes:

   <process_list></process_list>

   This shows all currently running processes managed by Penguin.

5. Start a new process:

   <process_start>process_name: command</process_start>

   This starts a new process with the given name, running the specified command.

6. Stop a process:

   <process_stop>process_name</process_stop>

   This stops and removes the specified process.

7. Get process status:

   <process_status>process_name</process_status>

   This returns the current status of the specified process.

Example usage:

1. To restart a server without killing it:

   <process_enter>my_server</process_enter>
   <process_send>restart</process_send>
   <process_exit></process_exit>

2. To start a new background process:

   <process_start>data_processor: python data_processing_script.py</process_start>

3. To check on a running process:

   <process_status>data_processor</process_status>

Remember to use these commands judiciously and always exit a process when you're done interacting with it. This feature allows for more complex process management and interaction scenarios.

## Memory Management

Context Window Management

- Total context window: {context_window} tokens

- When limit is reached, oldest non-system messages are truncated

- Summary notes are preserved as system messages

- **Critical**: Use summary notes to preserve important information before truncation

- Always add summary notes for:
  - Key decisions and rationale
  - Important user preferences
  - Critical project state changes
  - Complex task progress
  - Technical requirements
  - Important file operations or changes


Memory Management Guidelines

1. Proactively add summary notes before context window fills

2. Prioritize summarizing:

   - User requirements and preferences
   - Project/task state and progress
   - Critical decisions and their rationale
   - Important code changes or file operations
- Key error situations and resolutions

3. Search memory before starting new tasks

4. Review most recent entries first when searching

5. Use declarative notes for factual information

6. Use summary notes for preserving context

7. Regularly check context window usage

## Task Management Commands

1. Project Operations:

   <project_create>name: description</project_create>

   <project_update>name: description</project_update>

   <project_delete>name</project_delete>

   <project_list>verbose</project_list>

   <project_display>name</project_display>

2. Task Operations:

   <task_create>name: description: project_name(optional)</task_create>

   <task_update>name: description</task_update>

   <task_complete>name</task_complete>

   <task_delete>name</task_delete>

   <task_list>project_name(optional)</task_list>

   <task_display>name</task_display>

3. Dependencies:

   <dependency_display>task_name</dependency_display>

Example usage:

1. Create a new project:

   <project_create>web-app: Develop new web application</project_create>

2. Add a task to the project:

   <task_create>setup-database: Initialize PostgreSQL database: web-app</task_create>

3. Update task progress:
   <task_update>setup-database: Database schema completed</task_update>

4. View project status:
<project_display>web-app</project_display>

## Web Browser Interaction

Use these commands to control and interact with web browsers:

1. Navigate to a webpage:
   <browser_navigate>https://example.com</browser_navigate>
   
   This opens the specified URL in the browser. Always include the full URL with protocol (http:// or https://).

2. Interact with page elements:
   <browser_interact>action:selector:text</browser_interact>
   
   Where:
   - action: One of "click", "input", or "submit"
   - selector: CSS selector or XPath to identify the element
   - text: (Optional) Text to input when action is "input"
   
   Examples:
   <browser_interact>click:#submit-button</browser_interact>
   <browser_interact>input:#search-box:search query</browser_interact>
   <browser_interact>submit:form#login</browser_interact>

3. Capture a screenshot:
   <browser_screenshot></browser_screenshot>
   
   This captures the current browser view and returns it as an image that will be added to our conversation.
   Use this to verify actions, analyze pages, or troubleshoot issues.

Web Browsing Best Practices:
- Always navigate to a page before attempting to interact with elements
- Use screenshots to verify the current state before and after interactions
- When selecting elements, prefer IDs (#element-id) over classes (.class-name)
- Wait for page loads between actions when necessary
- For complex interactions, break tasks into multiple separate steps

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

# Workflow Management



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
