# Claude Code Sub-Agents & Tools Reference

*Scraped reference for how Anthropic implements sub-agents in Claude Code*

---

## Executive Summary

### Key Patterns from Claude Code Sub-Agents

1. **YAML-based configuration** - Subagents defined in `.claude/agents/*.yaml` files
2. **Three required fields**: `name`, `description`, `prompt`
3. **Optional model override** - Can specify cheaper/faster models (e.g., `claude-haiku-3-20240307`)
4. **Tool restrictions** - Explicit list of allowed tools per subagent
5. **Two scopes**: Project-level (`.claude/agents/`) and User-level (`~/.config/claude-code/agents/`)
6. **Automatic delegation** - Claude decides when to use subagents based on description
7. **Explicit invocation** - `@subagent-name` syntax for direct calls

### Tool Configuration Patterns

1. **Granular tool list**: `Read`, `Write`, `Edit`, `Bash`, `Glob`, `Grep`, `LS`, `WebFetch`, `WebSearch`, etc.
2. **Permission rules**: `allow`, `deny`, `ask` arrays with pattern matching
3. **Hierarchical settings**: User → Project → Project-local → Enterprise managed
4. **Bash prefix matching**: `Bash(npm run test:*)` matches commands starting with `npm run test`

### Example Subagent Config (from Claude Code)

```yaml
# .claude/agents/code-reviewer.yaml
name: code-reviewer
description: Reviews code for quality, security, and best practices
model: claude-sonnet-4-20250514  # Optional: specify a different model
tools:  # Optional: restrict available tools
  - Read
  - Glob
  - Grep
  - LS
prompt: |
  You are an expert code reviewer. Your role is to:
  1. Identify potential bugs and security vulnerabilities
  2. Suggest improvements for code quality and readability
  3. Check for adherence to best practices
  4. Provide constructive, actionable feedback
```

### Implications for Penguin

1. **Adopt YAML format** for agent personas (already using this in config.yml)
2. **Add `tools` field** to AgentPersonaConfig for tool restrictions
3. **Add `model` field** to specify cheaper models for subagents
4. **Consider `@agent-name` syntax** for explicit invocation
5. **Implement automatic delegation** based on description matching
6. **Add `/agents` command** for interactive agent management

---

## Source 1: Claude Code - Sub-agents

**URL:** https://code.claude.com/docs/en/sub-agents

- Subagents - Claude Code Docs Skip to main content Claude Code Docs home page 
English
 
 Search... ⌘ K Search... Navigation Build with Claude Code Subagents Getting started Build with Claude Code Deployment Administration Configuration Reference Resources Build with Claude Code Subagents 
- Plugins 
- Agent Skills 
- Output styles 
- Hooks 
- Headless mode 
- Model Context Protocol (MCP) 
- Migrate to Claude Agent SDK 
- Troubleshooting On this page 
- What are subagents? 
- Key benefits 
- Quick start 
- Subagent configuration 
- File locations 
- Plugin agents 
- CLI-based configuration 
- File format 
- Configuration fields 
- Model selection 
- Available tools 
- Managing subagents 
- Using the /agents command (Recommended) 
- Direct file management 
- Using subagents effectively 
- Automatic delegation 
- Explicit invocation 
- Built-in subagents 
- General-purpose subagent 
- Plan subagent 
- Explore subagent 
- Example subagents 
- Code reviewer 
- Debugger 
- Data scientist 
- Best practices 
- Advanced usage 
- Chaining subagents 
- Dynamic subagent selection 
- Resumable subagents 
- Performance considerations 
- Related documentation Build with Claude Code 
# Subagents
 Copy page Create and use specialized AI subagents in Claude Code for task-specific workflows and improved context management.
 
 Copy page Custom subagents in Claude Code are specialized AI assistants that can be invoked to handle specific types of tasks. They enable more efficient problem-solving by providing task-specific configurations with customized system prompts, tools and a separate context window. 

## ​ What are subagents? 

 Subagents are pre-configured AI personalities that Claude Code can delegate tasks to. Each subagent: 

- Has a specific purpose and expertise area

- Uses its own context window separate from the main conversation

- Can be configured with specific tools it’s allowed to use

- Includes a custom system prompt that guides its behavior
 
 When Claude Code encounters a task that matches a subagent’s expertise, it can delegate that task to the specialized subagent, which works independently and returns results. 

## ​ Key benefits 

## Context preservation
 Each subagent operates in its own context, preventing pollution of the main conversation and keeping it focused on high-level objectives. 
## Specialized expertise
 Subagents can be fine-tuned with detailed instructions for specific domains, leading to higher success rates on designated tasks. 
## Reusability
 Once created, you can use subagents across different projects and share them with your team for consistent workflows. 
## Flexible permissions
 Each subagent can have different tool access levels, allowing you to limit powerful tools to specific subagent types. 

## ​ Quick start 

 To create your first subagent: 
 1 Open the subagents interface
 Run the following command: 
 Copy Ask AI ` /agents 
 ` 2 Select 'Create New Agent'
 Choose whether to create a project-level or user-level subagent 3 
Define the subagent

- Recommended : generate with Claude first, then customize to make it yours

- Describe your subagent in detail, including when Claude should use it

- Select the tools you want to grant access to, or leave this blank to inherit all tools

- The interface shows all available tools

- If you’re generating with Claude, you can also edit the system prompt in your own editor by pressing `e`
 4 
Save and use
 Your subagent is now available. Claude uses it automatically when appropriate, or you can invoke it explicitly: 
 Copy Ask AI ` > Use the code-reviewer subagent to check my recent changes 
 ` 

## ​ Subagent configuration 

### ​ File locations 

 Subagents are stored as Markdown files with YAML frontmatter in two possible locations: 
 Type Location Scope Priority Project subagents `.claude/agents/` Available in current project Highest User subagents `~/.claude/agents/` Available across all projects Lower 
 When subagent names conflict, project-level subagents take precedence over user-level subagents. 

### ​ Plugin agents 

 Plugins can provide custom subagents that integrate seamlessly with Claude Code. Plugin agents work identically to user-defined agents and appear in the `/agents` interface. 
 Plugin agent locations : plugins include agents in their `agents/` directory (or custom paths specified in the plugin manifest). 
 Using plugin agents : 

- Plugin agents appear in `/agents` alongside your custom agents

- Can be invoked explicitly: “Use the code-reviewer agent from the security-plugin”

- Can be invoked automatically by Claude when appropriate

- Can be managed (viewed, inspected) through `/agents` interface
 
 See the plugin components reference for details on creating plugin agents. 

### ​ CLI-based configuration 

 You can also define subagents dynamically using the `--agents` CLI flag, which accepts a JSON object: 
 Copy Ask AI ` claude --agents '{ 
 "code-reviewer": { 
 "description": "Expert code reviewer. Use proactively after code changes.", 
 "prompt": "You are a senior code reviewer. Focus on code quality, security, and best practices.", 
 "tools": ["Read", "Grep", "Glob", "Bash"], 
 "model": "sonnet" 
 } 
 }' 
` 
 Priority : CLI-defined subagents have lower priority than project-level subagents but higher priority than user-level subagents. 
 Use case : This approach is useful for: 

- Quick testing of subagent configurations

- Session-specific subagents that don’t need to be saved

- Automation scripts that need custom subagents

- Sharing subagent definitions in documentation or scripts
 
 For detailed information about the JSON format and all available options, see the CLI reference documentation . 

### ​ File format 

 Each subagent is defined in a Markdown file with this structure: 
 Copy Ask AI ` --- 
 name : your-sub-agent-name 
 description : Description of when this subagent should be invoked 
 tools : tool1, tool2, tool3 # Optional - inherits all tools if omitted 
 model : sonnet # Optional - specify model alias or 'inherit' 
 permissionMode : default # Optional - permission mode for the subagent 
 skills : skill1, skill2 # Optional - skills to auto-load 
 --- 
 
 Your subagent's system prompt goes here. This can be multiple paragraphs 
 and should clearly define the subagent's role, capabilities, and approach 
 to solving problems. 
 
 Include specific instructions, best practices, and any constraints 
 the subagent should follow. 
` 

#### ​ Configuration fields 

 Field Required Description `name` Yes Unique identifier using lowercase letters and hyphens `description` Yes Natural language description of the subagent’s purpose `tools` No Comma-separated list of specific tools. If omitted, inherits all tools from the main thread `model` No Model to use for this subagent. Can be a model alias (`sonnet`, `opus`, `haiku`) or `'inherit'` to use the main conversation’s model. If omitted, defaults to the configured subagent model `permissionMode` No Permission mode for the subagent. Valid values: `default`, `acceptEdits`, `bypassPermissions`, `plan`, `ignore`. Controls how the subagent handles permission requests `skills` No Comma-separated list of skill names to auto-load when the subagent starts. Skills are loaded into the subagent’s context automatically 

### ​ Model selection 

 The `model` field allows you to control which AI model the subagent uses: 

- Model alias : Use one of the available aliases: `sonnet`, `opus`, or `haiku`

- `'inherit'` : Use the same model as the main conversation (useful for consistency)

- Omitted : If not specified, uses the default model configured for subagents (`sonnet`)
 
 Using `'inherit'` is particularly useful when you want your subagents to adapt to the model choice of the main conversation, ensuring consistent capabilities and response style throughout your session. 

### ​ Available tools 

 Subagents can be granted access to any of Claude Code’s internal tools. See the tools documentation for a complete list of available tools. 
 Recommended: Use the `/agents` command to modify tool access - it provides an interactive interface that lists all available tools, including any connected MCP server tools, making it easier to select the ones you need. 
 You have two options for configuring tools: 

- Omit the `tools` field to inherit all tools from the main thread (default), including MCP tools

- Specify individual tools as a comma-separated list for more granular control (can be edited manually or via `/agents`)
 
 MCP Tools : Subagents can access MCP tools from configured MCP servers. When the `tools` field is omitted, subagents inherit all MCP tools available to the main thread. 

## ​ Managing subagents 

### ​ Using the /agents command (Recommended) 

 The `/agents` command provides a comprehensive interface for subagent management: 
 Copy Ask AI ` /agents 
 ` 
 This opens an interactive menu where you can: 

- View all available subagents (built-in, user, and project)

- Create new subagents with guided setup

- Edit existing custom subagents, including their tool access

- Delete custom subagents

- See which subagents are active when duplicates exist

- Manage tool permissions with a complete list of available tools

### ​ Direct file management 

 You can also manage subagents by working directly with their files: 
 Copy Ask AI ` # Create a project subagent 
 mkdir -p .claude/agents 
 echo '--- 
 name: test-runner 
 description: Use proactively to run tests and fix failures 
 --- 
 
 You are a test automation expert. When you see code changes, proactively run the appropriate tests. If tests fail, analyze the failures and fix them while preserving the original test intent.' > .claude/agents/test-runner.md 
 
 # Create a user subagent 
 mkdir -p ~/.claude/agents 
 # ... create subagent file 
` 
 Subagents created by manually adding files will be loaded the next time you start a Claude Code session. To create and use a subagent immediately without restarting, use the `/agents` command instead. 

## ​ Using subagents effectively 

### ​ Automatic delegation 

 Claude Code proactively delegates tasks based on: 

- The task description in your request

- The `description` field in subagent configurations

- Current context and available tools
 
 To encourage more proactive subagent use, include phrases like “use PROACTIVELY” or “MUST BE USED” in your `description` field. 

### ​ Explicit invocation 

 Request a specific subagent by mentioning it in your command: 
 Copy Ask AI ` > Use the test-runner subagent to fix failing tests 
 > Have the code-reviewer subagent look at my recent changes 
 > Ask the debugger subagent to investigate this error 
 ` 

## ​ Built-in subagents 

 Claude Code includes built-in subagents that are available out of the box: 

### ​ General-purpose subagent 

 The general-purpose subagent is a capable agent for complex, multi-step tasks that require both exploration and action. Unlike the Explore subagent, it can modify files and execute a wider range of operations. 
 Key characteristics: 

- Model : Uses Sonnet for more capable reasoning

- Tools : Has access to all tools

- Mode : Can read and write files, execute commands, make changes

- Purpose : Complex research tasks, multi-step operations, code modifications
 
 When Claude uses it: 
 Claude delegates to the general-purpose subagent when: 

- The task requires both exploration and modification

- Complex reasoning is needed to interpret search results

- Multiple strategies may be needed if initial searches fail

- The task has multiple steps that depend on each other
 
 Example scenario: 
 Copy Ask AI ` User: Find all the places where we handle authentication and update them to use the new token format 
 
 Claude: [Invokes general-purpose subagent] 
 [Agent searches for auth-related code across codebase] 
 [Agent reads and analyzes multiple files] 
 [Agent makes necessary edits] 
 [Returns detailed writeup of changes made] 
 ` 

### ​ Plan subagent 

 The Plan subagent is a specialized built-in agent designed for use during plan mode. When Claude is operating in plan mode (non-execution mode), it uses the Plan subagent to conduct research and gather information about your codebase before presenting a plan. 
 Key characteristics: 

- Model : Uses Sonnet for more capable analysis

- Tools : Has access to Read, Glob, Grep, and Bash tools for codebase exploration

- Purpose : Searches files, analyzes code structure, and gathers context

- Automatic invocation : Claude automatically uses this agent when in plan mode and needs to research the codebase
 
 How it works: 
When you’re in plan mode and Claude needs to understand your codebase to create a plan, it delegates research tasks to the Plan subagent. This prevents infinite nesting of agents (subagents cannot spawn other subagents) while still allowing Claude to gather the necessary context. 
 Example scenario: 
 Copy Ask AI ` User: [In plan mode] Help me refactor the authentication module 
 
 Claude: Let me research your authentication implementation first... 
 [Internally invokes Plan subagent to explore auth-related files] 
 [Plan subagent searches codebase and returns findings] 
 Claude: Based on my research, here's my proposed plan... 
 ` 
 The Plan subagent is only used in plan mode. In normal execution mode, Claude uses the general-purpose agent or other custom subagents you’ve created. 

### ​ Explore subagent 

 The Explore subagent is a fast, lightweight agent optimized for searching and analyzing codebases. It operates in strict read-only mode and is designed for rapid file discovery and code exploration. 
 Key characteristics: 

- Model : Uses Haiku for fast, low-latency searches

- Mode : Strictly read-only - cannot create, modify, or delete files

- Tools available : 
 
 Glob - File pattern matching

- Grep - Content searching with regular expressions

- Read - Reading file contents

- Bash - Read-only commands only (ls, git status, git log, git diff, find, cat, head, tail)

 When Claude uses it: 
 Claude will delegate to the Explore subagent when it needs to search or understand a codebase but doesn’t need to make changes. This is more efficient than the main agent running multiple search commands directly, as content found during the exploration process doesn’t bloat the main conversation. 
 Thoroughness levels: 
 When invoking the Explore subagent, Claude specifies a thoroughness level: 

- Quick - Fast searches with minimal exploration. Good for targeted lookups.

- Medium - Moderate exploration. Balances speed and thoroughness.

- Very thorough - Comprehensive analysis across multiple locations and naming conventions. Used when the target might be in unexpected places.
 
 Example scenarios: 
 Copy Ask AI ` User: Where are errors from the client handled? 
 
 Claude: [Invokes Explore subagent with "medium" thoroughness] 
 [Explore uses Grep to search for error handling patterns] 
 [Explore uses Read to examine promising files] 
 [Returns findings with absolute file paths] 
 Claude: Client errors are handled in src/services/process.ts:712... 
 ` 
 Copy Ask AI ` User: What's the codebase structure? 
 
 Claude: [Invokes Explore subagent with "quick" thoroughness] 
 [Explore uses Glob and ls to map directory structure] 
 [Returns overview of key directories and their purposes] 
 ` 

## ​ Example subagents 

### ​ Code reviewer 

 Copy Ask AI ` --- 
 name : code-reviewer 
 description : Expert code review specialist. Proactively reviews code for quality, security, and maintainability. Use immediately after writing or modifying code. 
 tools : Read, Grep, Glob, Bash 
 model : inherit 
 --- 
 
 You are a senior code reviewer ensuring high standards of code quality and security. 
 
 When invoked: 
 1. Run git diff to see recent changes 
 2. Focus on modified files 
 3. Begin review immediately 
 
 Review checklist: 
 - Code is clear and readable 
 - Functions and variables are well-named 
 - No duplicated code 
 - Proper error handling 
 - No exposed secrets or API keys 
 - Input validation implemented 
 - Good test coverage 
 - Performance considerations addressed 
 
 Provide feedback organized by priority: 
 - Critical issues (must fix) 
 - Warnings (should fix) 
 - Suggestions (consider improving) 
 
 Include specific examples of how to fix issues. 
` 

### ​ Debugger 

 Copy Ask AI ` --- 
 name : debugger 
 description : Debugging specialist for errors, test failures, and unexpected behavior. Use proactively when encountering any issues. 
 tools : Read, Edit, Bash, Grep, Glob 
 --- 
 
 You are an expert debugger specializing in root cause analysis. 
 
 When invoked: 
 1. Capture error message and stack trace 
 2. Identify reproduction steps 
 3. Isolate the failure location 
 4. Implement minimal fix 
 5. Verify solution works 
 
 Debugging process: 
 - Analyze error messages and logs 
 - Check recent code changes 
 - Form and test hypotheses 
 - Add strategic debug logging 
 - Inspect variable states 
 
 For each issue, provide: 
 - Root cause explanation 
 - Evidence supporting the diagnosis 
 - Specific code fix 
 - Testing approach 
 - Prevention recommendations 
 
 Focus on fixing the underlying issue, not the symptoms. 
` 

### ​ Data scientist 

 Copy Ask AI ` --- 
 name : data-scientist 
 description : Data analysis expert for SQL queries, BigQuery operations, and data insights. Use proactively for data analysis tasks and queries. 
 tools : Bash, Read, Write 
 model : sonnet 
 --- 
 
 You are a data scientist specializing in SQL and BigQuery analysis. 
 
 When invoked: 
 1. Understand the data analysis requirement 
 2. Write efficient SQL queries 
 3. Use BigQuery command line tools (bq) when appropriate 
 4. Analyze and summarize results 
 5. Present findings clearly 
 
 Key practices: 
 - Write optimized SQL queries with proper filters 
 - Use appropriate aggregations and joins 
 - Include comments explaining complex logic 
 - Format results for readability 
 - Provide data-driven recommendations 
 
 For each analysis: 
 - Explain the query approach 
 - Document any assumptions 
 - Highlight key findings 
 - Suggest next steps based on data 
 
 Always ensure queries are efficient and cost-effective. 
` 

## ​ Best practices 

- 
 Start with Claude-generated agents : We highly recommend generating your initial subagent with Claude and then iterating on it to make it personally yours. This approach gives you the best results - a solid foundation that you can customize to your specific needs. 

- 
 Design focused subagents : Create subagents with single, clear responsibilities rather than trying to make one subagent do everything. This improves performance and makes subagents more predictable. 

- 
 Write detailed prompts : Include specific instructions, examples, and constraints in your system prompts. The more guidance you provide, the better the subagent will perform. 

- 
 Limit tool access : Only grant tools that are necessary for the subagent’s purpose. This improves security and helps the subagent focus on relevant actions. 

- 
 Version control : Check project subagents into version control so your team can benefit from and improve them collaboratively. 

## ​ Advanced usage 

### ​ Chaining subagents 

 For complex workflows, you can chain multiple subagents: 
 Copy Ask AI ` > First use the code-analyzer subagent to find performance issues, then use the optimizer subagent to fix them 
 ` 

### ​ Dynamic subagent selection 

 Claude Code intelligently selects subagents based on context. Make your `description` fields specific and action-oriented for best results. 

### ​ Resumable subagents 

 Subagents can be resumed to continue previous conversations, which is particularly useful for long-running research or analysis tasks that need to be continued across multiple invocations. 
 How it works: 

- Each subagent execution is assigned a unique `agentId`

- The agent’s conversation is stored in a separate transcript file: `agent-{agentId}.jsonl`

- You can resume a previous agent by providing its `agentId` via the `resume` parameter

- When resumed, the agent continues with full context from its previous conversation
 
 Example workflow: 
 Initial invocation: 
 Copy Ask AI ` > Use the code-analyzer agent to start reviewing the authentication module 
 
 [Agent completes initial analysis and returns agentId: "abc123"] 
 ` 
 Resume the agent: 
 Copy Ask AI ` > Resume agent abc123 and now analyze the authorization logic as well 
 
 [Agent continues with full context from previous conversation] 
 ` 
 Use cases: 

- Long-running research : Break down large codebase analysis into multiple sessions

- Iterative refinement : Continue refining a subagent’s work without losing context

- Multi-step workflows : Have a subagent work on related tasks sequentially while maintaining context
 
 Technical details: 

- Agent transcripts are stored in your project directory

- Recording is disabled during resume to avoid duplicating messages

- Both synchronous and asynchronous agents can be resumed

- The `resume` parameter accepts the agent ID from a previous execution
 
 Programmatic usage: 
 If you’re using the Agent SDK or interacting with the AgentTool directly, you can pass the `resume` parameter: 
 Copy Ask AI ` { 
 "description" : "Continue analysis" , 
 "prompt" : "Now examine the error handling patterns" , 
 "subagent_type" : "code-analyzer" , 
 "resume" : "abc123" // Agent ID from previous execution 
 } 
` 
 Keep track of agent IDs for tasks you may want to resume later. Claude Code displays the agent ID when a subagent completes its work. 

## ​ Performance considerations 

- Context efficiency : Agents help preserve main context, enabling longer overall sessions

- Latency : Subagents start off with a clean slate each time they are invoked and may add latency as they gather context that they require to do their job effectively.

## ​ Related documentation 

- Plugins - Extend Claude Code with custom agents through plugins

- Slash commands - Learn about other built-in commands

- Settings - Configure Claude Code behavior

- Hooks - Automate workflows with event handlers
 Was this page helpful?
 Yes No Plugins ⌘ I

---

## Source 2: Claude Code - Settings & Tools

**URL:** https://code.claude.com/docs/en/settings

- Claude Code settings - Claude Code Docs Skip to main content Claude Code Docs home page 
English
 
 Search... ⌘ K Search... Navigation Configuration Claude Code settings Getting started Build with Claude Code Deployment Administration Configuration Reference Resources Configuration Settings 
- Terminal configuration 
- Model configuration 
- Memory management 
- Status line configuration On this page 
- Settings files 
- Available settings 
- Permission settings 
- Sandbox settings 
- Attribution settings 
- Settings precedence 
- Key points about the configuration system 
- System prompt 
- Excluding sensitive files 
- Subagent configuration 
- Plugin configuration 
- Plugin settings 
- enabledPlugins 
- extraKnownMarketplaces 
- Managing plugins 
- Environment variables 
- Tools available to Claude 
- Bash tool behavior 
- Extending tools with hooks 
- See also Configuration 
# Claude Code settings
 Copy page Configure Claude Code with global and project-level settings, and environment variables.
 
 Copy page Claude Code offers a variety of settings to configure its behavior to meet your needs. You can configure Claude Code by running the `/config` command when using the interactive REPL, which opens a tabbed Settings interface where you can view status information and modify configuration options. 

## ​ Settings files 

 The `settings.json` file is our official mechanism for configuring Claude
Code through hierarchical settings: 

- User settings are defined in `~/.claude/settings.json` and apply to all
projects.

- Project settings are saved in your project directory: 
 
 `.claude/settings.json` for settings that are checked into source control and shared with your team

- `.claude/settings.local.json` for settings that are not checked in, useful for personal preferences and experimentation. Claude Code will configure git to ignore `.claude/settings.local.json` when it is created.

- For enterprise deployments of Claude Code, we also support enterprise
managed policy settings . These take precedence over user and project
settings. System administrators can deploy policies to: 
 
 macOS: `/Library/Application Support/ClaudeCode/managed-settings.json`

- Linux and WSL: `/etc/claude-code/managed-settings.json`

- Windows: `C:\Program Files\ClaudeCode\managed-settings.json`
 
 `C:\ProgramData\ClaudeCode\managed-settings.json` will be deprecated in a future version.

- Enterprise deployments can also configure managed MCP servers that override
user-configured servers. See Enterprise MCP configuration : 
 
 macOS: `/Library/Application Support/ClaudeCode/managed-mcp.json`

- Linux and WSL: `/etc/claude-code/managed-mcp.json`

- Windows: `C:\Program Files\ClaudeCode\managed-mcp.json`
 
 `C:\ProgramData\ClaudeCode\managed-mcp.json` will be deprecated in a future version.

- Other configuration is stored in `~/.claude.json`. This file contains your preferences (theme, notification settings, editor mode), OAuth session, MCP server configurations for user and local scopes, per-project state (allowed tools, trust settings), and various caches. Project-scoped MCP servers are stored separately in `.mcp.json`.
 
 Example settings.json Copy Ask AI ` { 
 "permissions" : { 
 "allow" : [ 
 "Bash(npm run lint)" , 
 "Bash(npm run test:*)" , 
 "Read(~/.zshrc)" 
 ], 
 "deny" : [ 
 "Bash(curl:*)" , 
 "Read(./.env)" , 
 "Read(./.env.*)" , 
 "Read(./secrets/**)" 
 ] 
 }, 
 "env" : { 
 "CLAUDE_CODE_ENABLE_TELEMETRY" : "1" , 
 "OTEL_METRICS_EXPORTER" : "otlp" 
 }, 
 "companyAnnouncements" : [ 
 "Welcome to Acme Corp! Review our code guidelines at docs.acme.com" , 
 "Reminder: Code reviews required for all PRs" , 
 "New security policy in effect" 
 ] 
 } 
` 

### ​ Available settings 

 `settings.json` supports a number of options: 
 Key Description Example `apiKeyHelper` Custom script, to be executed in `/bin/sh`, to generate an auth value. This value will be sent as `X-Api-Key` and `Authorization: Bearer` headers for model requests `/bin/generate_temp_api_key.sh` `cleanupPeriodDays` Sessions inactive for longer than this period are deleted at startup. Setting to `0` immediately deletes all sessions. (default: 30 days) `20` `companyAnnouncements` Announcement to display to users at startup. If multiple announcements are provided, they will be cycled through at random. `["Welcome to Acme Corp! Review our code guidelines at docs.acme.com"]` `env` Environment variables that will be applied to every session `{"FOO": "bar"}` `attribution` Customize attribution for git commits and pull requests. See Attribution settings `{"commit": "🤖 Generated with Claude Code", "pr": ""}` `includeCoAuthoredBy` Deprecated : Use `attribution` instead. Whether to include the `co-authored-by Claude` byline in git commits and pull requests (default: `true`) `false` `permissions` See table below for structure of permissions. `hooks` Configure custom commands to run before or after tool executions. See hooks documentation `{"PreToolUse": {"Bash": "echo 'Running command...'"}}` `disableAllHooks` Disable all hooks `true` `model` Override the default model to use for Claude Code `"claude-sonnet-4-5-20250929"` `statusLine` Configure a custom status line to display context. See `statusLine` documentation `{"type": "command", "command": "~/.claude/statusline.sh"}` `outputStyle` Configure an output style to adjust the system prompt. See output styles documentation `"Explanatory"` `forceLoginMethod` Use `claudeai` to restrict login to Claude.ai accounts, `console` to restrict login to Claude Console (API usage billing) accounts `claudeai` `forceLoginOrgUUID` Specify the UUID of an organization to automatically select it during login, bypassing the organization selection step. Requires `forceLoginMethod` to be set `"xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"` `enableAllProjectMcpServers` Automatically approve all MCP servers defined in project `.mcp.json` files `true` `enabledMcpjsonServers` List of specific MCP servers from `.mcp.json` files to approve `["memory", "github"]` `disabledMcpjsonServers` List of specific MCP servers from `.mcp.json` files to reject `["filesystem"]` `allowedMcpServers` When set in managed-settings.json, allowlist of MCP servers users can configure. Undefined = no restrictions, empty array = lockdown. Applies to all scopes. Denylist takes precedence. See Enterprise MCP configuration `[{ "serverName": "github" }]` `deniedMcpServers` When set in managed-settings.json, denylist of MCP servers that are explicitly blocked. Applies to all scopes including enterprise servers. Denylist takes precedence over allowlist. See Enterprise MCP configuration `[{ "serverName": "filesystem" }]` `awsAuthRefresh` Custom script that modifies the `.aws` directory (see advanced credential configuration ) `aws sso login --profile myprofile` `awsCredentialExport` Custom script that outputs JSON with AWS credentials (see advanced credential configuration ) `/bin/generate_aws_grant.sh` `alwaysThinkingEnabled` Enable extended thinking by default for all sessions. Typically configured via the `/config` command rather than editing directly `true` 

### ​ Permission settings 

 Keys Description Example `allow` Array of permission rules to allow tool use. Note: Bash rules use prefix matching, not regex `[ "Bash(git diff:*)" ]` `ask` Array of permission rules to ask for confirmation upon tool use. `[ "Bash(git push:*)" ]` `deny` Array of permission rules to deny tool use. Use this to also exclude sensitive files from Claude Code access. Note: Bash patterns are prefix matches and can be bypassed (see Bash permission limitations ) `[ "WebFetch", "Bash(curl:*)", "Read(./.env)", "Read(./secrets/**)" ]` `additionalDirectories` Additional working directories that Claude has access to `[ "../docs/" ]` `defaultMode` Default permission mode when opening Claude Code `"acceptEdits"` `disableBypassPermissionsMode` Set to `"disable"` to prevent `bypassPermissions` mode from being activated. This disables the `--dangerously-skip-permissions` command-line flag. See managed policy settings `"disable"` 

### ​ Sandbox settings 

 Configure advanced sandboxing behavior. Sandboxing isolates bash commands from your filesystem and network. See Sandboxing for details. 
 Filesystem and network restrictions are configured via Read, Edit, and WebFetch permission rules, not via these sandbox settings. 
 Keys Description Example `enabled` Enable bash sandboxing (macOS/Linux only). Default: false `true` `autoAllowBashIfSandboxed` Auto-approve bash commands when sandboxed. Default: true `true` `excludedCommands` Commands that should run outside of the sandbox `["git", "docker"]` `allowUnsandboxedCommands` Allow commands to run outside the sandbox via the `dangerouslyDisableSandbox` parameter. When set to `false`, the `dangerouslyDisableSandbox` escape hatch is completely disabled and all commands must run sandboxed (or be in `excludedCommands`). Useful for enterprise policies that require strict sandboxing. Default: true `false` `network.allowUnixSockets` Unix socket paths accessible in sandbox (for SSH agents, etc.) `["~/.ssh/agent-socket"]` `network.allowLocalBinding` Allow binding to localhost ports (macOS only). Default: false `true` `network.httpProxyPort` HTTP proxy port used if you wish to bring your own proxy. If not specified, Claude will run its own proxy. `8080` `network.socksProxyPort` SOCKS5 proxy port used if you wish to bring your own proxy. If not specified, Claude will run its own proxy. `8081` `enableWeakerNestedSandbox` Enable weaker sandbox for unprivileged Docker environments (Linux only). Reduces security. Default: false `true` 
 Configuration example: 
 Copy Ask AI ` { 
 "sandbox" : { 
 "enabled" : true , 
 "autoAllowBashIfSandboxed" : true , 
 "excludedCommands" : [ "docker" ], 
 "network" : { 
 "allowUnixSockets" : [ 
 "/var/run/docker.sock" 
 ], 
 "allowLocalBinding" : true 
 } 
 }, 
 "permissions" : { 
 "deny" : [ 
 "Read(.envrc)" , 
 "Read(~/.aws/**)" 
 ] 
 } 
 } 
` 
 Filesystem and network restrictions use standard permission rules: 

- Use `Read` deny rules to block Claude from reading specific files or directories

- Use `Edit` allow rules to let Claude write to directories beyond the current working directory

- Use `Edit` deny rules to block writes to specific paths

- Use `WebFetch` allow/deny rules to control which network domains Claude can access

### ​ Attribution settings 

 Claude Code adds attribution to git commits and pull requests. These are configured separately: 

- Commits use git trailers (like `Co-Authored-By`) by default, which can be customized or disabled

- Pull request descriptions are plain text
 
 Keys Description `commit` Attribution for git commits, including any trailers. Empty string hides commit attribution `pr` Attribution for pull request descriptions. Empty string hides pull request attribution 
 Default commit attribution: 
 Copy Ask AI ` 🤖 Generated with [Claude Code](https://claude.com/claude-code) 
 
 Co-Authored-By: Claude Sonnet 4.5 < [email protected] > 
 ` 
 Default pull request attribution: 
 Copy Ask AI ` 🤖 Generated with [Claude Code](https://claude.com/claude-code) 
 ` 
 Example: 
 Copy Ask AI ` { 
 "attribution" : { 
 "commit" : "Generated with AI \n\n Co-Authored-By: AI < [email protected] >" , 
 "pr" : "" 
 } 
 } 
` 
 The `attribution` setting takes precedence over the deprecated `includeCoAuthoredBy` setting. To hide all attribution, set `commit` and `pr` to empty strings. 

### ​ Settings precedence 

 Settings apply in order of precedence. From highest to lowest: 

- 
 Enterprise managed policies (`managed-settings.json`) 
 
 Deployed by IT/DevOps

- Can’t be overridden

- 
 Command line arguments 
 
 Temporary overrides for a specific session

- 
 Local project settings (`.claude/settings.local.json`) 
 
 Personal project-specific settings

- 
 Shared project settings (`.claude/settings.json`) 
 
 Team-shared project settings in source control

- 
 User settings (`~/.claude/settings.json`) 
 
 Personal global settings

 This hierarchy ensures that enterprise security policies are always enforced while still allowing teams and individuals to customize their experience. 
 For example, if your user settings allow `Bash(npm run:*)` but a project’s shared settings deny it, the project setting takes precedence and the command is blocked. 

### ​ Key points about the configuration system 

- Memory files (`CLAUDE.md`) : Contain instructions and context that Claude loads at startup

- Settings files (JSON) : Configure permissions, environment variables, and tool behavior

- Slash commands : Custom commands that can be invoked during a session with `/command-name`

- MCP servers : Extend Claude Code with additional tools and integrations

- Precedence : Higher-level configurations (Enterprise) override lower-level ones (User/Project)

- Inheritance : Settings are merged, with more specific settings adding to or overriding broader ones

### ​ System prompt 

 Claude Code’s internal system prompt is not published. To add custom instructions, use `CLAUDE.md` files or the `--append-system-prompt` flag. 

### ​ Excluding sensitive files 

 To prevent Claude Code from accessing files containing sensitive information like API keys, secrets, and environment files, use the `permissions.deny` setting in your `.claude/settings.json` file: 
 Copy Ask AI ` { 
 "permissions" : { 
 "deny" : [ 
 "Read(./.env)" , 
 "Read(./.env.*)" , 
 "Read(./secrets/**)" , 
 "Read(./config/credentials.json)" , 
 "Read(./build)" 
 ] 
 } 
 } 
` 
 This replaces the deprecated `ignorePatterns` configuration. Files matching these patterns will be completely invisible to Claude Code, preventing any accidental exposure of sensitive data. 

## ​ Subagent configuration 

 Claude Code supports custom AI subagents that can be configured at both user and project levels. These subagents are stored as Markdown files with YAML frontmatter: 

- User subagents : `~/.claude/agents/` - Available across all your projects

- Project subagents : `.claude/agents/` - Specific to your project and can be shared with your team
 
 Subagent files define specialized AI assistants with custom prompts and tool permissions. Learn more about creating and using subagents in the subagents documentation . 

## ​ Plugin configuration 

 Claude Code supports a plugin system that lets you extend functionality with custom commands, agents, hooks, and MCP servers. Plugins are distributed through marketplaces and can be configured at both user and repository levels. 

### ​ Plugin settings 

 Plugin-related settings in `settings.json`: 
 Copy Ask AI ` { 
 "enabledPlugins" : { 
 "formatter@company-tools" : true , 
 "deployer@company-tools" : true , 
 "analyzer@security-plugins" : false 
 }, 
 "extraKnownMarketplaces" : { 
 "company-tools" : { 
 "source" : "github" , 
 "repo" : "company/claude-plugins" 
 } 
 } 
 } 
` 

#### ​ `enabledPlugins` 

 Controls which plugins are enabled. Format: `"plugin-name@marketplace-name": true/false` 
 Scopes : 

- User settings (`~/.claude/settings.json`): Personal plugin preferences

- Project settings (`.claude/settings.json`): Project-specific plugins shared with team

- Local settings (`.claude/settings.local.json`): Per-machine overrides (not committed)
 
 Example : 
 Copy Ask AI ` { 
 "enabledPlugins" : { 
 "code-formatter@team-tools" : true , 
 "deployment-tools@team-tools" : true , 
 "experimental-features@personal" : false 
 } 
 } 
` 

#### ​ `extraKnownMarketplaces` 

 Defines additional marketplaces that should be made available for the repository. Typically used in repository-level settings to ensure team members have access to required plugin sources. 
 When a repository includes `extraKnownMarketplaces` : 

- Team members are prompted to install the marketplace when they trust the folder

- Team members are then prompted to install plugins from that marketplace

- Users can skip unwanted marketplaces or plugins (stored in user settings)

- Installation respects trust boundaries and requires explicit consent
 
 Example : 
 Copy Ask AI ` { 
 "extraKnownMarketplaces" : { 
 "company-tools" : { 
 "source" : { 
 "source" : "github" , 
 "repo" : "company-org/claude-plugins" 
 } 
 }, 
 "security-plugins" : { 
 "source" : { 
 "source" : "git" , 
 "url" : "https://git.company.com/security/plugins.git" 
 } 
 } 
 } 
 } 
` 
 Marketplace source types : 

- `github`: GitHub repository (uses `repo`)

- `git`: Any git URL (uses `url`)

- `directory`: Local filesystem path (uses `path`, for development only)

### ​ Managing plugins 

 Use the `/plugin` command to manage plugins interactively: 

- Browse available plugins from marketplaces

- Install/uninstall plugins

- Enable/disable plugins

- View plugin details (commands, agents, hooks provided)

- Add/remove marketplaces
 
 Learn more about the plugin system in the plugins documentation . 

## ​ Environment variables 

 Claude Code supports the following environment variables to control its behavior: 
 All environment variables can also be configured in `settings.json` . This is useful as a way to automatically set environment variables for each session, or to roll out a set of environment variables for your whole team or organization. 
 Variable Purpose `ANTHROPIC_API_KEY` API key sent as `X-Api-Key` header, typically for the Claude SDK (for interactive usage, run `/login`) `ANTHROPIC_AUTH_TOKEN` Custom value for the `Authorization` header (the value you set here will be prefixed with `Bearer `) `ANTHROPIC_CUSTOM_HEADERS` Custom headers you want to add to the request (in `Name: Value` format) `ANTHROPIC_DEFAULT_HAIKU_MODEL` See Model configuration `ANTHROPIC_DEFAULT_OPUS_MODEL` See Model configuration `ANTHROPIC_DEFAULT_SONNET_MODEL` See Model configuration `ANTHROPIC_FOUNDRY_API_KEY` API key for Microsoft Foundry authentication (see Microsoft Foundry ) `ANTHROPIC_MODEL` Name of the model setting to use (see Model Configuration ) `ANTHROPIC_SMALL_FAST_MODEL` [DEPRECATED] Name of Haiku-class model for background tasks `ANTHROPIC_SMALL_FAST_MODEL_AWS_REGION` Override AWS region for the Haiku-class model when using Bedrock `AWS_BEARER_TOKEN_BEDROCK` Bedrock API key for authentication (see Bedrock API keys ) `BASH_DEFAULT_TIMEOUT_MS` Default timeout for long-running bash commands `BASH_MAX_OUTPUT_LENGTH` Maximum number of characters in bash outputs before they are middle-truncated `BASH_MAX_TIMEOUT_MS` Maximum timeout the model can set for long-running bash commands `CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR` Return to the original working directory after each Bash command `CLAUDE_CODE_API_KEY_HELPER_TTL_MS` Interval in milliseconds at which credentials should be refreshed (when using `apiKeyHelper`) `CLAUDE_CODE_CLIENT_CERT` Path to client certificate file for mTLS authentication `CLAUDE_CODE_CLIENT_KEY_PASSPHRASE` Passphrase for encrypted CLAUDE_CODE_CLIENT_KEY (optional) `CLAUDE_CODE_CLIENT_KEY` Path to client private key file for mTLS authentication `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS` Set to `1` to disable Anthropic API-specific `anthropic-beta` headers. Use this if experiencing issues like “Unexpected value(s) for the `anthropic-beta` header” when using an LLM gateway with third-party providers `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` Equivalent of setting `DISABLE_AUTOUPDATER`, `DISABLE_BUG_COMMAND`, `DISABLE_ERROR_REPORTING`, and `DISABLE_TELEMETRY` `CLAUDE_CODE_DISABLE_TERMINAL_TITLE` Set to `1` to disable automatic terminal title updates based on conversation context `CLAUDE_CODE_IDE_SKIP_AUTO_INSTALL` Skip auto-installation of IDE extensions `CLAUDE_CODE_MAX_OUTPUT_TOKENS` Set the maximum number of output tokens for most requests `CLAUDE_CODE_SHELL_PREFIX` Command prefix to wrap all bash commands (for example, for logging or auditing). Example: `/path/to/logger.sh` will execute `/path/to/logger.sh <command>` `CLAUDE_CODE_SKIP_BEDROCK_AUTH` Skip AWS authentication for Bedrock (for example, when using an LLM gateway) `CLAUDE_CODE_SKIP_FOUNDRY_AUTH` Skip Azure authentication for Microsoft Foundry (for example, when using an LLM gateway) `CLAUDE_CODE_SKIP_VERTEX_AUTH` Skip Google authentication for Vertex (for example, when using an LLM gateway) `CLAUDE_CODE_SUBAGENT_MODEL` See Model configuration `CLAUDE_CODE_USE_BEDROCK` Use Bedrock `CLAUDE_CODE_USE_FOUNDRY` Use Microsoft Foundry `CLAUDE_CODE_USE_VERTEX` Use Vertex `CLAUDE_CONFIG_DIR` Customize where Claude Code stores its configuration and data files `DISABLE_AUTOUPDATER` Set to `1` to disable automatic updates. `DISABLE_BUG_COMMAND` Set to `1` to disable the `/bug` command `DISABLE_COST_WARNINGS` Set to `1` to disable cost warning messages `DISABLE_ERROR_REPORTING` Set to `1` to opt out of Sentry error reporting `DISABLE_NON_ESSENTIAL_MODEL_CALLS` Set to `1` to disable model calls for non-critical paths like flavor text `DISABLE_PROMPT_CACHING` Set to `1` to disable prompt caching for all models (takes precedence over per-model settings) `DISABLE_PROMPT_CACHING_HAIKU` Set to `1` to disable prompt caching for Haiku models `DISABLE_PROMPT_CACHING_OPUS` Set to `1` to disable prompt caching for Opus models `DISABLE_PROMPT_CACHING_SONNET` Set to `1` to disable prompt caching for Sonnet models `DISABLE_TELEMETRY` Set to `1` to opt out of Statsig telemetry (note that Statsig events do not include user data like code, file paths, or bash commands) `HTTP_PROXY` Specify HTTP proxy server for network connections `HTTPS_PROXY` Specify HTTPS proxy server for network connections `MAX_MCP_OUTPUT_TOKENS` Maximum number of tokens allowed in MCP tool responses. Claude Code displays a warning when output exceeds 10,000 tokens (default: 25000) `MAX_THINKING_TOKENS` Enable extended thinking and set the token budget for the thinking process. Extended thinking improves performance on complex reasoning and coding tasks but impacts prompt caching efficiency . Disabled by default. `MCP_TIMEOUT` Timeout in milliseconds for MCP server startup `MCP_TOOL_TIMEOUT` Timeout in milliseconds for MCP tool execution `NO_PROXY` List of domains and IPs to which requests will be directly issued, bypassing proxy `SLASH_COMMAND_TOOL_CHAR_BUDGET` Maximum number of characters for slash command metadata shown to SlashCommand tool (default: 15000) `USE_BUILTIN_RIPGREP` Set to `0` to use system-installed `rg` instead of `rg` included with Claude Code `VERTEX_REGION_CLAUDE_3_5_HAIKU` Override region for Claude 3.5 Haiku when using Vertex AI `VERTEX_REGION_CLAUDE_3_7_SONNET` Override region for Claude 3.7 Sonnet when using Vertex AI `VERTEX_REGION_CLAUDE_4_0_OPUS` Override region for Claude 4.0 Opus when using Vertex AI `VERTEX_REGION_CLAUDE_4_0_SONNET` Override region for Claude 4.0 Sonnet when using Vertex AI `VERTEX_REGION_CLAUDE_4_1_OPUS` Override region for Claude 4.1 Opus when using Vertex AI 

## ​ Tools available to Claude 

 Claude Code has access to a set of powerful tools that help it understand and modify your codebase: 
 Tool Description Permission Required AskUserQuestion Asks the user multiple choice questions to gather information or clarify ambiguity No Bash Executes shell commands in your environment (see Bash tool behavior below) Yes BashOutput Retrieves output from a background bash shell No Edit Makes targeted edits to specific files Yes ExitPlanMode Prompts the user to exit plan mode and start coding Yes Glob Finds files based on pattern matching No Grep Searches for patterns in file contents No KillShell Kills a running background bash shell by its ID No NotebookEdit Modifies Jupyter notebook cells Yes Read Reads the contents of files No Skill Executes a skill within the main conversation Yes SlashCommand Runs a custom slash command Yes Task Runs a sub-agent to handle complex, multi-step tasks No TodoWrite Creates and manages structured task lists No WebFetch Fetches content from a specified URL Yes WebSearch Performs web searches with domain filtering Yes Write Creates or overwrites files Yes 
 Permission rules can be configured using `/allowed-tools` or in permission settings . Also see Tool-specific permission rules . 

### ​ Bash tool behavior 

 The Bash tool executes shell commands with the following persistence behavior: 

- Working directory persists : When Claude changes the working directory (for example, `cd /path/to/dir`), subsequent Bash commands will execute in that directory. You can use `CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR=1` to reset to the project directory after each command.

- Environment variables do NOT persist : Environment variables set in one Bash command (for example, `export MY_VAR=value`) are not available in subsequent Bash commands. Each Bash command runs in a fresh shell environment.
 
 To make environment variables available in Bash commands, you have three options : 
 Option 1: Activate environment before starting Claude Code (simplest approach) 
 Activate your virtual environment in your terminal before launching Claude Code: 
 Copy Ask AI ` conda activate myenv 
 # or: source /path/to/venv/bin/activate 
 claude 
` 
 This works for shell environments but environment variables set within Claude’s Bash commands will not persist between commands. 
 Option 2: Set CLAUDE_ENV_FILE before starting Claude Code (persistent environment setup) 
 Export the path to a shell script containing your environment setup: 
 Copy Ask AI ` export CLAUDE_ENV_FILE = / path / to / env-setup . sh 
 claude 
` 
 Where `/path/to/env-setup.sh` contains: 
 Copy Ask AI ` conda activate myenv 
 # or: source /path/to/venv/bin/activate 
 # or: export MY_VAR=value 
` 
 Claude Code will source this file before each Bash command, making the environment persistent across all commands. 
 Option 3: Use a SessionStart hook (project-specific configuration) 
 Configure in `.claude/settings.json`: 
 Copy Ask AI ` { 
 "hooks" : { 
 "SessionStart" : [{ 
 "matcher" : "startup" , 
 "hooks" : [{ 
 "type" : "command" , 
 "command" : "echo 'conda activate myenv' >> \" $CLAUDE_ENV_FILE \" " 
 }] 
 }] 
 } 
 } 
` 
 The hook writes to `$CLAUDE_ENV_FILE`, which is then sourced before each Bash command. This is ideal for team-shared project configurations. 
 See SessionStart hooks for more details on Option 3. 

### ​ Extending tools with hooks 

 You can run custom commands before or after any tool executes using
 Claude Code hooks . 
 For example, you could automatically run a Python formatter after Claude
modifies Python files, or prevent modifications to production configuration
files by blocking Write operations to certain paths. 

## ​ See also 

- Identity and Access Management - Learn about Claude Code’s permission system

- IAM and access control - Enterprise policy management

- Troubleshooting - Solutions for common configuration issues
 Was this page helpful?
 Yes No Terminal configuration ⌘ I

---

*Last updated: Scraped during Penguin development session*
