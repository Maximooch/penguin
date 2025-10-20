# Gemini CLI Feature Analysis for Penguin CLI

*Generated from comprehensive analysis of the Gemini CLI codebase*

---

## 1. Commands (Slash Commands System)

### Core Architecture
- **Implementation**: Extensible slash command system with built-in and extension-provided commands
- **Features**: Subcommands, auto-completion, alternative names (aliases), command context injection
- **File**: `packages/cli/src/ui/commands/types.ts`

### Available Commands

#### `/chat` - Conversation Management
- **What**: Manage conversation history and checkpoints
- **Subcommands**:
  - `save <tag>` - Save current conversation as checkpoint with overwrite confirmation
  - `resume <tag>` (alias: `load`) - Resume from checkpoint with history restoration
  - `delete <tag>` - Delete checkpoint with completion support
  - `list` - List all saved checkpoints sorted by modification time
  - `share <file>` - Export conversation to markdown or JSON
- **Implementation**: File-based checkpoint system in `.gemini/checkpoint-<tag>.json`
- **Priority**: **HIGH** - Essential for session management
- **Dependencies**: File system, history serialization

#### `/mcp` - MCP Server Management
- **What**: Manage Model Context Protocol servers
- **Subcommands**:
  - `list` (aliases: `ls`, `nodesc`, `nodescription`) - List servers and tools
  - `desc` (alias: `description`) - List with descriptions
  - `schema` - List with full schemas
  - `auth <server>` - OAuth authentication for MCP servers
  - `refresh` - Restart MCP servers and rediscover tools
- **Implementation**:
  - Real-time server status tracking (CONNECTING, CONNECTED, ERROR)
  - OAuth token storage with expiration tracking
  - Dynamic tool discovery and registration
  - Server blocking/allowing via settings
- **Priority**: **HIGH** - Core MCP integration
- **Dependencies**: MCP SDK, OAuth provider, tool registry

#### `/memory` - Memory System
- **What**: Manage GEMINI.md hierarchical memory
- **Subcommands**:
  - `show` - Display current memory content
  - `add <text>` - Add to memory via save_memory tool
  - `refresh` - Reload memory from GEMINI.md files
  - `list` - List paths of GEMINI.md files in use
- **Implementation**:
  - Hierarchical file system traversal
  - Support for multiple GEMINI.md files
  - Tree or flat import formats
  - Integration with include directories
- **Priority**: **MEDIUM** - Nice context feature
- **Dependencies**: File system, GEMINI.md parser

#### `/extensions` - Extension Management
- **What**: Manage CLI extensions
- **Subcommands**:
  - `list` - List active extensions with metadata
  - `update <names>|--all` - Update extensions from source
- **Implementation**:
  - GitHub release downloads and Git cloning
  - Extension enablement/disablement system
  - Version tracking and update notifications
  - Extension sandbox configuration
- **Priority**: **LOW** - Advanced feature
- **Dependencies**: Git, GitHub API, extension loader

#### `/settings` - Settings Dialog
- **What**: Interactive settings editor
- **Implementation**: Opens dialog for editing user/workspace settings
- **Priority**: **MEDIUM** - UX improvement
- **Dependencies**: Settings schema, dialog system

#### `/vim` - Vim Mode Toggle
- **What**: Toggle vim keybindings on/off
- **Implementation**:
  - Normal and Insert modes
  - Custom key mapping system
  - Persistent setting
- **Priority**: **LOW** - Power user feature
- **Dependencies**: Vim mode context, key binding system

#### `/stats` - Session Statistics
- **What**: Display session and usage statistics
- **Subcommands**:
  - `model` - Model-specific usage stats
  - `tools` - Tool-specific usage stats
- **Implementation**: Session tracking, token counting, duration formatting
- **Priority**: **MEDIUM** - Useful analytics
- **Dependencies**: Session context, stats tracking

#### `/restore` - Tool Call Restoration
- **What**: Restore previous tool calls with state rewind
- **Implementation**:
  - Git-based project snapshots
  - Conversation history restoration
  - Tool call checkpointing
- **Priority**: **LOW** - Advanced feature, requires checkpointing
- **Dependencies**: Git service, checkpointing enabled

#### `/init` - Project Analysis
- **What**: Generate GEMINI.md for current project
- **Implementation**: AI-driven project analysis with 10-file iterative exploration
- **Priority**: **MEDIUM** - Good onboarding
- **Dependencies**: AI model, file system

#### `/directory` - Workspace Directories
- **What**: Manage workspace context directories
- **Subcommands**:
  - `add <paths>` - Add directories (comma-separated)
  - `remove <paths>` - Remove directories
  - `list` - List current directories
- **Implementation**: Dynamic workspace context updates with memory refresh
- **Priority**: **MEDIUM** - Context management
- **Dependencies**: Workspace context, memory loader

#### `/bug` - Bug Report
- **What**: Generate and open bug report with system info
- **Implementation**: Collects CLI version, OS, memory, model, session ID
- **Priority**: **LOW** - Support feature
- **Dependencies**: System info, browser open

#### `/theme` - Theme Selector
- **What**: Change color theme
- **Implementation**: Dialog-based theme picker
- **Priority**: **MEDIUM** - UX customization
- **Dependencies**: Theme manager, dialog system

#### Other Commands
- `/about` - Show version and info
- `/auth` - Authentication management
- `/clear` - Clear screen
- `/compress` - Context compression utilities
- `/copy` - Copy to clipboard
- `/docs` - Open documentation
- `/editor` - Set preferred editor
- `/help` - Show help
- `/ide` - IDE integration commands
- `/model` - Switch model
- `/permissions` - Permission settings
- `/privacy` - Privacy settings
- `/quit` - Exit CLI
- `/tools` - List available tools

---

## 2. UI/UX Features

### Layout & Rendering
- **Ink-based React Terminal UI**: Full React component system in terminal
- **Screen Reader Support**: ARIA-like accessibility features
- **Overflow Handling**: Smart text wrapping and scrolling
- **Spinner Components**: Loading states for async operations
- **ANSI Color Support**: Full 256-color terminal output
- **Priority**: **MEDIUM** - Penguin already has Ink

### Vim Mode
- **What**: Complete vim keybindings with Normal/Insert modes
- **Implementation**:
  - VimModeContext with state management
  - Custom key mapping per mode
  - Persistent toggle via settings
  - Visual mode indicator
- **Priority**: **LOW** - Power user feature
- **Dependencies**: Key binding system

### Key Bindings System
- **What**: Configurable keyboard shortcuts
- **Features**:
  - Data-driven binding configuration
  - Multi-key combinations (Ctrl, Shift, Meta)
  - Context-aware bindings
  - User customization support
- **Key Commands**: 50+ built-in shortcuts including:
  - Text editing (kill line, delete word, etc.)
  - History navigation (Ctrl+P/N, arrows)
  - Completion (Tab, Ctrl+N/P)
  - External editor (Ctrl+X)
  - Image paste (Ctrl+V)
  - Reverse search (Ctrl+R)
- **Priority**: **HIGH** - Great UX
- **Dependencies**: Ink key handling

### Theme System
- **What**: Customizable color themes
- **Features**:
  - 10+ built-in themes (Dracula, GitHub Dark/Light, Atom One Dark, etc.)
  - Custom theme support via settings
  - Semantic color tokens
  - ANSI color mapping
  - Theme persistence
- **Themes**: Default, Default Light, Ayu, Dracula, GitHub Dark/Light, Atom One Dark, Googlecode, Xcode, Shades of Purple, No Color
- **Priority**: **MEDIUM** - Nice to have
- **Dependencies**: Color utilities, settings system

### Accessibility
- **No Color Mode**: Full functionality without colors
- **Screen Reader Hints**: Contextual information for screen readers
- **Keyboard Navigation**: Full keyboard control
- **Priority**: **MEDIUM** - Important for inclusivity

---

## 3. Configuration & Settings

### Settings Architecture
- **Implementation**: Multi-layer settings with user/workspace scopes
- **File**: `settingsSchema.ts` defines 100+ settings
- **Features**:
  - JSON with comments support
  - Hierarchical merging (user + workspace)
  - Merge strategies (replace, concat, union, shallow_merge)
  - Type validation
  - Restart requirements tracking
  - Dialog visibility flags

### Key Settings Categories

#### General Settings
- `vimMode` - Enable vim keybindings
- `preferredEditor` - External editor command
- `disableAutoUpdate` - Turn off auto-updates
- `enablePromptCompletion` - AI-powered prompt suggestions
- `checkpointing.enabled` - Session checkpointing
- `retryFetchErrors` - Network error handling

#### Security Settings
- `folderTrust.enabled` - Trusted folder system
- `tools.autoAccept` - Auto-approve read-only tools
- `tools.allowed` - Explicitly allowed tools
- `tools.exclude` - Blocked tools

#### MCP Settings
- `mcpServers` - Server configurations with OAuth, trust, env vars
- `mcp.allowed` - Allowed server list
- `mcp.excluded` - Blocked server list

#### Context Settings
- `context.importFormat` - Tree or flat (for GEMINI.md)
- `context.maxDepth` - Directory traversal depth

#### Shell Settings
- `shell.allowedCommands` - Command whitelist
- `shell.blockedCommands` - Command blacklist
- `interactive` - Interactive shell mode

### Settings Dialog
- **What**: Interactive TUI for editing settings
- **Features**:
  - Category grouping
  - Toggle values (boolean, enum)
  - Free-form input (string, number)
  - Restart warnings
  - Real-time validation
- **Priority**: **HIGH** - Great UX
- **Dependencies**: Dialog manager, settings schema

---

## 4. Extension System

### Architecture
- **What**: Plugin system for third-party extensions
- **Location**: `~/.gemini/extensions/`
- **Config**: `gemini-extension.json` per extension

### Extension Features
- **Installation**:
  - GitHub releases (download tarball)
  - Git repositories (clone)
  - Local directories
  - Version tracking in `.gemini-extension-install.json`
- **Capabilities**:
  - Add MCP servers
  - Provide context files
  - Exclude tools
  - Define custom variables
- **Management**:
  - Enable/disable per extension
  - Update checking
  - Uninstall
  - Trust warnings

### Extension Components
- **Variable System**: Template variables like `${workspaceDir}`, `${homeDir}`
- **Context Files**: Extensions can provide GEMINI.md-style context
- **Tool Filtering**: Extensions can exclude specific tools
- **MCP Integration**: Extensions bundle MCP server configs

### Priority
- **Priority**: **LOW** - Complex, advanced feature
- **Dependencies**: Git, GitHub API, settings system, MCP

---

## 5. MCP Integration

### Server Management
- **Discovery**: Automatic tool and prompt discovery
- **Connection**:
  - Stdio transport
  - HTTP/SSE transport
  - OAuth authentication flow
- **Status Tracking**: CONNECTING, CONNECTED, ERROR states
- **Restart**: On-demand server restart with tool refresh

### OAuth Support
- **What**: OAuth 2.0 authentication for MCP servers
- **Features**:
  - Token storage with encryption
  - Expiration tracking
  - Refresh token handling
  - Browser-based authorization flow
  - Event-driven status updates
- **Priority**: **MEDIUM** - Important for cloud MCP servers
- **Dependencies**: OAuth library, secure storage

### Tool Registry
- **What**: Central registry of all available tools
- **Features**:
  - Tool discovery per server
  - Schema validation
  - Tool filtering (allowed/excluded)
  - Pattern matching (`serverName__*`)
  - Dynamic registration
- **Priority**: **HIGH** - Core MCP functionality

### Prompt Registry
- **What**: Registry of MCP-provided prompts
- **Features**:
  - Prompt discovery
  - Tab completion for prompts
  - Slash command generation from prompts
- **Priority**: **MEDIUM** - Useful MCP feature

---

## 6. Prompt Processing

### Prompt Pipeline
- **Architecture**: Chain of processors that transform prompts

### @File References (`@{filepath}`)
- **What**: Inject file contents into prompts
- **Implementation**: `atFileProcessor.ts`
- **Features**:
  - Glob pattern support
  - .gitignore/.geminiignore respect
  - Error handling with placeholder retention
  - Image embedding support
- **Priority**: **HIGH** - Essential feature
- **Dependencies**: File service

### Shell Command Execution (`!{command}`)
- **What**: Execute shell commands in prompts
- **Implementation**: `shellProcessor.ts`
- **Features**:
  - Security validation against allowed/blocked commands
  - Argument injection with `{{args}}`
  - Shell-escaped vs raw argument handling
  - Confirmation prompts for unsafe commands
  - Exit code and signal reporting
  - ANSI color preservation
- **Priority**: **HIGH** - Powerful feature
- **Dependencies**: Shell execution service, security policy

### Argument Injection (`{{args}}`)
- **What**: Inject command arguments into prompts
- **Implementation**: `argumentProcessor.ts`
- **Behavior**:
  - Inside `!{...}`: Shell-escaped
  - Outside `!{...}`: Raw text
- **Priority**: **MEDIUM** - Nice for custom commands
- **Dependencies**: Injection parser

### Injection Parser
- **What**: Robust parser for nested braces
- **Features**:
  - Handles escaped braces
  - Nested block support
  - Multiple injection types
- **Priority**: **HIGH** - Core infrastructure

---

## 7. Session Management

### Checkpoints
- **What**: Save/restore conversation state
- **Storage**: `.gemini/checkpoint-<tag>.json`
- **Contents**:
  - Full conversation history
  - Model context
  - System prompts
- **Features**:
  - Overwrite confirmation
  - Tag-based naming
  - Tab completion
- **Priority**: **HIGH** - User requested feature
- **Dependencies**: File storage

### Tool Call Checkpoints
- **What**: Save state before destructive tool calls
- **Storage**: `.gemini/tool-checkpoints/<id>.json`
- **Contents**:
  - Conversation history
  - Git commit hash (snapshot)
  - Tool call details
- **Features**:
  - Automatic on risky operations
  - Restore with `/restore <id>`
  - Project state rewind via Git
- **Priority**: **MEDIUM** - Safety feature
- **Dependencies**: Git service, checkpointing enabled

### Session Cleanup
- **What**: Automatic cleanup of old sessions
- **Features**:
  - Configurable retention (days)
  - Size-based cleanup
  - Session metadata tracking
- **Priority**: **LOW** - Maintenance feature

---

## 8. Security & Permissions

### Trusted Folders
- **What**: Folder-based trust system
- **File**: `~/.gemini/trustedFolders.json`
- **Trust Levels**:
  - `TRUST_FOLDER` - Trust this folder only
  - `TRUST_PARENT` - Trust parent directory
  - `DO_NOT_TRUST` - Explicit denial
- **Features**:
  - IDE integration (VS Code workspace trust)
  - Hierarchical trust inheritance
  - Interactive trust prompts
- **Priority**: **HIGH** - Security critical
- **Dependencies**: Settings, IDE context

### Policy Engine
- **What**: Rule-based tool permission system
- **Implementation**: `policy.ts`
- **Decisions**: ALLOW, DENY, ASK_USER
- **Priority System** (0-200):
  - 200: Explicitly excluded tools (highest)
  - 195: Excluded MCP servers
  - 100: Explicitly allowed tools
  - 90: Trusted MCP servers
  - 85: Allowed MCP servers
  - 50: Auto-accept read-only tools
  - 10: Write tools default to ASK_USER
  - 0: YOLO mode allow-all (lowest)
- **Features**:
  - Pattern matching (`server__*`)
  - Tool categorization (read-only vs write)
  - Approval modes (YOLO, AUTO_EDIT, standard)
- **Priority**: **HIGH** - Security critical
- **Dependencies**: Settings, tool registry

### Sandbox Configuration
- **What**: OS-level sandboxing
- **Implementation**: macOS sandbox profiles, Linux seccomp
- **Profiles**: Restrictive, moderate, permissive
- **Priority**: **LOW** - Platform-specific, complex

### Shell Command Security
- **What**: Whitelist/blacklist for shell commands
- **Features**:
  - Command parsing and validation
  - Regex pattern matching
  - Hard denials vs confirmations
  - Session-level allowlist (YOLO mode per-session)
- **Priority**: **HIGH** - Security critical
- **Dependencies**: Policy engine

---

## 9. Advanced Features

### Auto-Updates
- **What**: Automatic CLI updates from releases
- **Features**:
  - Update checking on startup
  - User consent prompts
  - Silent update in background
  - Update notifications
  - Disable via settings
- **Priority**: **LOW** - Nice to have
- **Dependencies**: GitHub API, download manager

### Prompt Completion
- **What**: AI-powered autocomplete while typing
- **Implementation**: Secondary model for suggestions
- **Features**:
  - Real-time suggestions
  - Configurable enable/disable
  - Requires restart to toggle
- **Priority**: **LOW** - Resource intensive
- **Dependencies**: AI model access

### External Editor
- **What**: Open external editor for long prompts
- **Shortcut**: Ctrl+X
- **Features**:
  - Configurable editor command
  - Temporary file handling
  - Image attachment support
  - Multi-line editing
- **Priority**: **MEDIUM** - Good UX
- **Dependencies**: File system, editor setting

### Clipboard Image Paste
- **What**: Paste images from clipboard
- **Shortcut**: Ctrl+V
- **Implementation**: Platform-specific clipboard access
- **Priority**: **MEDIUM** - Multimodal support
- **Dependencies**: Clipboard API

### Reverse Search
- **What**: Search command history
- **Shortcut**: Ctrl+R
- **Implementation**: Fuzzy search through history
- **Priority**: **MEDIUM** - Shell-like UX
- **Dependencies**: History context

### Context Compression
- **What**: Compress conversation context when near limits
- **Features**:
  - Automatic or manual compression
  - Configurable compression ratio
  - Summary generation
- **Priority**: **MEDIUM** - Token management
- **Dependencies**: AI model

### Telemetry
- **What**: Anonymous usage analytics
- **Features**:
  - Opt-in/opt-out
  - Extension usage tracking
  - Error reporting
  - Privacy-preserving
- **Priority**: **LOW** - Product analytics

### IDE Integration
- **What**: Deep integration with VS Code and other IDEs
- **Features**:
  - Workspace context sharing
  - Trust inheritance
  - Active file detection
  - Git integration
- **Priority**: **MEDIUM** - Good for VS Code users
- **Dependencies**: IDE protocol

### Memory Usage Tracking
- **What**: Monitor and report memory consumption
- **Implementation**: Process memory stats in `/stats`
- **Priority**: **LOW** - Diagnostics

---

## 10. Priority Recommendations

### Must-Have (Implement First)
1. **Checkpoint System** (`/chat save/resume`) - User explicitly requested
2. **@File References** - Essential prompt enhancement
3. **Shell Command Execution** (`!{command}`) - Power feature
4. **Policy Engine** - Security foundation
5. **Trusted Folders** - Security requirement
6. **Settings System** - Configuration management
7. **Key Bindings** - UX improvement
8. **MCP Tool Registry** - Core MCP functionality

### Should-Have (Next Priority)
1. **Theme System** - UI customization
2. **Settings Dialog** - User-friendly config
3. **Memory System** (`/memory`) - Context management
4. **Statistics** (`/stats`) - Usage insights
5. **External Editor** - Better editing UX
6. **OAuth for MCP** - Cloud server support
7. **Workspace Directories** (`/directory`) - Context control

### Nice-to-Have (Later)
1. **Vim Mode** - Power user feature
2. **Extension System** - Extensibility (complex)
3. **Tool Call Restoration** - Advanced feature
4. **Auto-Updates** - Convenience
5. **Prompt Completion** - AI-powered typing
6. **Reverse Search** - Shell UX
7. **Context Compression** - Token optimization
8. **IDE Integration** - Editor integration
9. **Bug Report** (`/bug`) - Support tooling
10. **Init Command** (`/init`) - Onboarding

### Skip (Too Complex or Low Value)
1. **Sandbox Profiles** - Platform-specific, complex
2. **Telemetry** - Privacy concerns, complex
3. **Extension GitHub Integration** - Complex, low initial need

---

## Implementation Notes

### Architecture Patterns
- **Service-based architecture**: Config, Settings, FileService, GitService, etc.
- **React Context providers**: Settings, Vim Mode, Session, UI State
- **Event system**: App-wide events for cross-component communication
- **Command pattern**: Slash commands with context injection
- **Pipeline pattern**: Prompt processors chain

### Key Dependencies
- **Ink**: React-based terminal UI
- **Genai SDK**: Google AI model access
- **MCP SDK**: Model Context Protocol
- **chalk**: Terminal colors
- **strip-json-comments**: Config parsing
- **open**: Browser launching
- **node-fetch**: HTTP requests

### Testing Strategy
- **Unit tests**: Extensive coverage for processors, parsers, settings
- **Integration tests**: Full CLI workflows
- **Test utilities**: File system mocking, test helpers

### File Organization
```
packages/cli/src/
├── config/           # Settings, policy, extensions, trust
├── services/         # Command loaders, prompt processors
├── ui/
│   ├── commands/     # Slash command implementations
│   ├── components/   # React components
│   ├── contexts/     # React contexts
│   └── themes/       # Theme definitions
└── utils/           # Helpers, formatters, errors
```

---

## Penguin-Specific Considerations

### Already Implemented in Penguin
- Basic Ink UI
- MCP server integration
- Tool execution
- Message rendering

### Quick Wins for Penguin
1. **Checkpoint system** - File-based, simple to add
2. **@File processor** - Straightforward prompt transformer
3. **Settings schema** - Structure already exists
4. **Theme system** - Drop-in color schemes
5. **Key bindings** - Map to Ink handlers

### Challenges
1. **Extension system** - Complex, needs careful design
2. **OAuth flow** - Requires browser interaction
3. **Sandbox profiles** - Platform-specific, skip for now
4. **Policy engine** - Security-critical, needs thorough testing

### Integration Points
- Settings can extend existing `.claude/settings.local.json`
- Checkpoints can use `.penguin/checkpoints/`
- Themes can integrate with existing color system
- Commands can extend current command palette

---

## Summary Statistics

- **Total Commands**: 20+ slash commands with 50+ subcommands
- **Settings**: 100+ configurable options
- **Themes**: 10+ built-in themes
- **Key Bindings**: 50+ keyboard shortcuts
- **Prompt Processors**: 4 (file, shell, argument, injection parser)
- **Security Levels**: 7 priority levels in policy engine
- **Trust Levels**: 3 (trust folder, trust parent, do not trust)
- **Extension Capabilities**: MCP servers, context files, tool filtering

---

*End of Analysis*
