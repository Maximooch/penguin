---
sidebar_position: 3
---

# Configuring Penguin

Penguin can be configured through environment variables and YAML configuration files. This guide documents the configuration surface that the code actually reads: core model settings, project/workspace paths, security, prompt composition, output style, diagnostics, theme, tools, and the web server.

Simplest way is to run `penguin config setup`.

## Configuration Architecture

Penguin uses a two-tier configuration system:

1. **Startup Configuration** (Immutable): Loaded from environment variables and YAML files at startup
2. **Runtime Configuration** (Mutable): Can be changed dynamically during operation without restart (`RuntimeConfig`, observer pattern)

### Configuration Precedence

YAML configuration is merged from multiple locations. Precedence is **lowest → highest**:

| # | Source | Location |
| --- | --- | --- |
| 1 | Package default | `penguin/config.yml` (inside the installed package) |
| 2 | Dev repo default | `<repo_root>/config.yml` (source checkouts only) |
| 3 | User config | `~/.config/penguin/config.yml` (or `%APPDATA%/penguin/config.yml`) |
| 4 | Project config | `<project_root>/.penguin/config.yml` |
| 5 | Project local overrides | `<project_root>/.penguin/settings.local.yml` |
| 6 | Explicit override | `PENGUIN_CONFIG_PATH` (highest single-file override) |

Each higher layer overrides the same keys in lower layers. The one exception:
**security lists** (`security.allowed_paths`, `security.denied_paths`,
`security.require_approval`) are merged **additively** (combined and
deduplicated), so a project can always add to the deny list even when a
lower-precedence layer set one.

`/config set <key> <value>` writes to the project scope
(`.penguin/settings.local.yml`); `/config --global set <key> <value>` writes to
the user config (`~/.config/penguin/config.yml`).

### Runtime Configuration

The `RuntimeConfig` system allows you to change critical settings while the server is running:

- **Project Root**: The directory where your code/project lives (typically a git repository)
- **Workspace Root**: The Penguin workspace directory (for conversations, notes, memory)
- **Execution Mode**: Where file operations target (`project` or `workspace`)

**Key Features:**
- ✅ Changes take effect immediately without restart
- ✅ Observer pattern ensures all components stay synchronized
- ✅ Validated to prevent invalid configurations
- ✅ Accessible via CLI commands or Web API

**Example: Dynamic Configuration via Web API**
```bash
# Get current configuration
curl http://127.0.0.1:9000/api/v1/system/config

# Change project root
curl -X POST http://127.0.0.1:9000/api/v1/system/config/project-root \
  -H "Content-Type: application/json" \
  -d '{"path": "/Users/you/new-project"}'

# Switch execution mode
curl -X POST http://127.0.0.1:9000/api/v1/system/config/execution-mode \
  -H "Content-Type: application/json" \
  -d '{"path": "project"}'
```

See [Runtime Configuration API](api_reference/api_server.md#runtime-configuration-management) for full API documentation.

## Prompt Composition

Penguin composes its system prompt from independent layers rather than treating
personality, task intent, permissions, and response formatting as one “mode”:

1. **Penguin Soul** — stable identity, character, and strategic counsel.
2. **Operating contract** — permissions, truthful completion, and runtime rules.
3. **Work mode** — the current intent: build, plan, review, research, or chat.
4. **Quality overlays** — optional product, rigorous-systems, or complexity focus.
5. **Response style** — presentation only; it does not change task intent.

Runtime capabilities remain separate and enforceable. Prompt text may describe
a recommended capability profile, but it cannot grant tools or permissions.

```yaml
prompt:
  work_mode: build
  personality:
    profile: penguin
    # Optional user-owned preferences stored in local configuration.
    overlay: ""
  quality_overlays: []
```

| Work mode | Use it for | Recommended capability |
| --- | --- | --- |
| `build` | Implement and verify workspace changes. | `full` |
| `plan` | Produce an actionable plan without modifying the workspace. | `read_only` |
| `review` | Find actionable issues without applying fixes. | `read_only` |
| `research` | Gather and synthesize primary evidence. | `read_only` |
| `chat` | Explain and advise from available conversation context. | `no_tools` |

Quality overlays do not create new task modes. `product` asks for complete
user-facing states, `rigorous` strengthens systems/invariant analysis, and
`complexity_review` performs a Ponytail-inspired delete-list review.

The old `prompt.mode` names remain supported as compatibility presets. For
example, `product` maps to work mode `build` plus the product overlay, while
`terse` maps to build mode plus minimal personality and plain response style.
New configuration should use the orthogonal fields above.

Prompt settings do not create default execution limits. An unconfigured goal
still continues until completion, interruption, required input, or a real
external/runtime failure. Configured token, iteration, and time limits remain
explicit runtime contracts.

## Git Attribution Prompt

Penguin includes a commit-attribution reminder by default. It asks the agent to
add this trailer when it creates a commit:

```text
Co-authored-by: penguin-agent[bot] <penguin-agent[bot]@users.noreply.github.com>
```

This is prompt guidance only: it does not alter Git identity, rewrite existing
commits, or guarantee attribution for arbitrary shell commands. Disable the
reminder locally or per project with:

```yaml
git:
  attribution:
    prompt: false
```

For example, `/config --global set git.attribution.prompt false` persists the
setting in the user configuration. Restart Penguin or begin a new runtime for
the changed prompt to take effect.

## Configuration Methods

### 1. Environment Variables

Environment variables take precedence over YAML for the keys they cover. The
package loads `.env` files from the working directory, project root, and the
user config directory (`~/.config/penguin/.env`).

**Provider API keys** (at least one is needed to connect a model):

```bash
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
GOOGLE_API_KEY=...
OPENROUTER_API_KEY=...
DEEPSEEK_API_KEY=...
```

Additional provider keys are read as `<PROVIDER_UPPERCASE>_API_KEY`; see
`penguin/core_runtime/model_runtime.py` and `penguin/setup/wizard.py` for the
supported set.

**Model selection and behavior:**

```bash
PENGUIN_DEFAULT_MODEL=openai/gpt-5          # Default model id
PENGUIN_DEFAULT_PROVIDER=openrouter          # Default provider
PENGUIN_CLIENT_PREFERENCE=openrouter         # native | litellm | openrouter | link
PENGUIN_MODEL=openai/gpt-5                   # Legacy fallback model id
PENGUIN_PROVIDER=openrouter                  # Legacy fallback provider
PENGUIN_TEMPERATURE=0.7
PENGUIN_MAX_OUTPUT_TOKENS=4000
PENGUIN_MAX_TOKENS=4000                      # Accepted alias for max output tokens
PENGUIN_MAX_HISTORY_TOKENS=200000
PENGUIN_MAX_CONTEXT_WINDOW_TOKENS=200000
PENGUIN_CONTEXT_SAFETY_FRACTION=0.85
PENGUIN_STREAMING_ENABLED=true
PENGUIN_USE_RESPONSES_API=true
PENGUIN_INTERRUPT_ON_ACTION=true
PENGUIN_VISION_ENABLED=true
PENGUIN_REASONING_ENABLED=true
PENGUIN_REASONING_EFFORT=high
PENGUIN_REASONING_MAX_TOKENS=8000
PENGUIN_REASONING_EXCLUDE=false
PENGUIN_OPENAI_SERVICE_TIER=auto             # auto | default | flex | priority
```

**Paths and runtime roots:**

```bash
PENGUIN_CONFIG_PATH=/path/to/config.yml      # Highest-precedence config override
PENGUIN_ROOT=/path/to/data                   # Data root when installed (site-packages)
PENGUIN_CWD=...
PENGUIN_PROJECT_ROOT=/path/to/project        # Initial project root (runtime-configurable)
PENGUIN_WORKSPACE=/path/to/workspace         # Initial workspace root (runtime-configurable)
PENGUIN_WRITE_ROOT=project                   # Initial execution mode: project | workspace
PENGUIN_CACHE_DIR=/path/to/cache
PENGUIN_OPENCODE_DIR=...
PENGUIN_TUI_BIN_PATH=...
PENGUIN_TUI_CACHE_DIR=...
PENGUIN_TUI_LAUNCH_MODE=...
PENGUIN_TUI_PROFILE=...
PENGUIN_SOURCE_ROOT=...
```

**Security and behavior:**

```bash
PENGUIN_YOLO=true                            # Disable permission checks (use with caution)
PENGUIN_DEBUG=true                           # Debug logging
PENGUIN_LOG_LEVEL=INFO
PENGUIN_LOG_CONTEXT_PREVIEWS=true
PENGUIN_TELEMETRY=false
NO_COLOR=true                                # Disable ANSI color output
```

**Web server** (see below for details):

```bash
HOST=127.0.0.1
PORT=9000
PENGUIN_AUTH_ENABLED=true
PENGUIN_API_KEYS=replace-me
PENGUIN_JWT_SECRET=replace-me
PENGUIN_JWT_ALGORITHM=HS256
PENGUIN_JWT_EXPIRATION_HOURS=24
PENGUIN_PUBLIC_ENDPOINTS=/api/v1/integrations/github/webhook
PENGUIN_CORS_ORIGINS=https://penguin.example.com
PENGUIN_ALLOW_INSECURE_NO_AUTH=false
PENGUIN_MAX_UPLOAD_BYTES=10737418240
PENGUIN_MAX_CONCURRENT_TASKS=4
PENGUIN_MAX_DIFF_LINES=5000
PENGUIN_MAX_FILES_PER_REVIEW=50
PENGUIN_GITHUB_WEBHOOK_DELIVERY_TTL_SECONDS=600
GITHUB_WEBHOOK_SECRET=replace-me
```

### 2. YAML Configuration File

Create a `config.yml` for advanced configuration. The full schema below
matches what `penguin/config.py` and the package default
(`penguin/config.yml`) actually read.

```yaml
# --- Model ---
model:
  default: openai/gpt-5          # Default model id
  provider: openrouter           # openai | anthropic | openrouter | google | ...
  client_preference: openrouter  # native | litellm | openrouter | link
  temperature: 0.3
  max_output_tokens: 50000
  context_window: 170000
  streaming_enabled: true
  vision_enabled: true
  service_tier: auto             # OpenAI only: auto | default | flex | priority

# --- Per-model overrides (resolved by LLMModelConfig.for_model) ---
model_configs:
  openai/gpt-5:
    context_window: 390000
    max_output_tokens: 120000
    provider: openrouter
    temperature: 0.5
    reasoning:
      enabled: true
      effort: high

# --- Provider base URL ---
api:
  base_url: null   # Optional global API base URL

# --- Project and workspace ---
project:
  root_strategy: git-root   # 'git-root' (default) or 'cwd'
  additional_directories:   # Additional allowed directories for security
    - /path/to/extra/dir

workspace:
  path: penguin_workspace
  create_dirs:
    - conversations
    - memory_db
    - logs
    - notes
    - projects
    - context

defaults:
  write_root: project   # Default execution mode: 'project' (set to workspace to isolate)

# --- Context loading ---
context:
  additional_paths: []
  allowed_load_paths:
    - ./
  autoload_project_docs: true
  load_from_project: true
  scratchpad_dir: context

# --- Security ---
security:
  mode: workspace        # read_only | workspace | full
  enabled: true
  allowed_paths: []      # Merged additively across config layers
  denied_paths:          # Merged additively
    - .env
    - .env.*
    - '**/*.pem'
    - '**/*.key'
    - '**/*secret*'
    - '**/*credential*'
  require_approval:      # Merged additively
    - filesystem.delete
    - git.push
    - git.force

  # Optional audit logging
  audit:
    enabled: true
    log_file: ".penguin/permission_audit.log"
    categories:
      filesystem: all
      process: ask_and_deny
      network: deny_only
      git: ask_and_deny
      memory: off
    max_memory_entries: 1000
    include_context: false

# --- Per-agent personas (multi-agent mode) ---
agents:
  reviewer:
    description: Code reviewer - read-only quality and security analysis
    system_prompt: '...'
    model:
      model: anthropic/claude-haiku-4.5
      provider: openrouter
      max_output_tokens: 100000
    permissions:
      mode: read_only
    default_tools:
      - enhanced_read
      - list_files_filtered
      - search
    shared_context_window_max_tokens: 60000

# --- Output / reply style ---
output:
  prompt_style: steps_final   # steps_final | plain | json_guided | explanatory
  show_tool_results: true

# --- Diagnostics ---
diagnostics:
  enabled: true
  verbose_logging: true
  max_context_tokens: 400000
  log_to_file: false
  log_path: null

# --- Performance ---
performance:
  fast_startup: false

# --- Tools ---
tools:
  enabled: true
  allow_file_operations: true
  allow_web_access: true
  allow_code_execution: true

# --- TUI theme ---
theme:
  colors:
    assistant: '#5F87FF'
    banner: 'bold #00D7FF'
    code_border: 'dim #5F87FF'
    context: dim
    diff_add: green
    diff_remove: red
    error: red
    penguin_name: '#5F87FF'
    reasoning: dim white
    system: yellow
    tool: magenta
    user: cyan

# --- CLI display (optional; read by penguin/cli/ui.py) ---
cli:
  display:
    style: minimal            # minimal | compact | standard | detailed | streaming
    consolidate_system_messages: true
    hide_internal_markers: true
    hide_tool_results: true
    max_blank_lines: 2
    deduplicate_messages: true
    show_timestamps: true
    show_metadata: false
```

> **Note on sections not listed here:** earlier versions of this guide
> documented `logging:`, `providers:` (with `api_key`/`models` lists),
> `memory:`, `web:`, `paths:`, and `project.storage`/`project.execution`
> blocks. The current code does **not** read those YAML sections — model
> provider credentials come from environment variables, the web server is
> configured via environment variables, and memory providers are configured in
> code (see `penguin/memory/providers/factory.py`). Treat any such YAML from
> older setups as inert.

## Output Formatting

Penguin’s assistant reply style is configurable and separate from the CLI’s program output format. Use this to choose how the assistant structures its messages in the TUI and interactive sessions.

### YAML (project or user config)

```yaml
output:
  # One of: steps_final (default) | plain | json_guided | explanatory
  prompt_style: steps_final
```

Styles:
- steps_final: Keeps the “Plan / Steps” collapsible details block and a clear “Final” section.
- plain: Concise, well-structured answers without a collapsible steps block.
- json_guided: Assistant includes a concise JSON summary for structure (e.g., fields like type, answer, next_steps), and places larger code snippets in fenced code blocks.
- explanatory: Cohesive educational prose with the conclusion, reasoning, examples, and tradeoffs.

Note: This controls the assistant’s reply style. It does not change the CLI non-interactive output, which is controlled by `--output-format` (see below).

### TUI Commands

- `/output style get` — show the current style
- `/output style set steps_final|plain|json_guided|explanatory` — change the style at runtime

To persist as default:

```text
/config set output.prompt_style "plain"          # project-local
/config --global set output.prompt_style "plain" # user config
```

### CLI Non-Interactive vs. Reply Style

In non-interactive mode (`-p/--prompt`), you can select the program output format:

```bash
penguin -p "…" --output-format text|json|stream-json
```

- `--output-format` affects how the CLI prints its final response object (useful for scripting).
- `output.prompt_style` affects how the assistant structures its messages (Steps + Final, plain, JSON-guided) during interactive sessions or when rendering assistant content.

## Model Provider Configuration

Model providers are configured with the `model:` block plus per-model
overrides in `model_configs:`. Provider credentials always come from
environment variables (`<PROVIDER>_API_KEY`); the wizard (`penguin config
setup`) writes them to the user-level `.env`.

```yaml
model:
  default: openai/gpt-5
  provider: openrouter
  client_preference: openrouter

model_configs:
  anthropic/claude-sonnet-4.5:
    provider: openrouter
    context_window: 990000
    max_output_tokens: 63000
    temperature: 0.5
```

The resolved model config is produced by
`penguin.llm.model_config.ModelConfig.for_model()`, which consults the
environment variables listed above, the `model:` block, and `model_configs:`.
Use `penguin config test-routing` to debug provider/model routing.

## Project Management Configuration

```yaml
project:
  root_strategy: git-root   # or 'cwd'
  additional_directories:
    - /path/to/extra/dir
```

`project.root_strategy` controls how the project root is discovered: `git-root`
climbs to the enclosing git repository, `cwd` uses the current working
directory. `project.additional_directories` are extra directories the security
layer permits access to.

## Security Configuration

Penguin includes a comprehensive permission system that controls what operations the AI agent can perform. See [Security & Permissions](advanced/security.md) for full documentation.

### Security Modes

```yaml
security:
  # Security mode: read_only, workspace, or full
  mode: workspace

  # Enable/disable permission checks (set to false or use PENGUIN_YOLO=true to disable)
  enabled: true

  # Additional allowed paths beyond workspace/project (merged additively)
  allowed_paths:
    - /path/to/shared/resources

  # Explicitly denied paths (always blocked, merged additively)
  denied_paths:
    - ~/.ssh
    - ~/.aws
    - /etc

  # Operations requiring user approval before execution
  require_approval:
    - filesystem.delete
    - git.push
    - git.force
```

**Mode Descriptions:**
- `read_only`: Agent can only read files, no modifications allowed
- `workspace`: Operations restricted to workspace and project directories (default)
- `full`: Minimal restrictions, use with caution in trusted environments

### Multi-Agent Permissions

Per-agent permission restrictions live under `agents:` (Phase 1+
configuration surface, loaded by `Config.load_config`):

```yaml
agents:
  code-reviewer:
    description: "Code Review Expert"
    permissions:
      mode: read_only
    default_tools:
      - filesystem.read
      - memory.read
```

## Advanced Configuration

### Custom Tool Configuration

```yaml
tools:
  enabled: true
  allow_file_operations: true
  allow_web_access: true
  allow_code_execution: true
```

### Performance Tuning

```yaml
performance:
  fast_startup: false
```

## Configuration Troubleshooting

**Common Issues:**

1. **Configuration not loading**: Check YAML syntax and file permissions; run `penguin config check` and `penguin config debug` for diagnostics.
2. **API connection errors**: Verify API keys are set in the environment or user-level `.env`; run `penguin config test-routing`.
3. **Wrong model or provider being used**: Check `model.default`, `model.provider`, and any `model_configs` entry for the model id; env vars (`PENGUIN_DEFAULT_MODEL`, `PENGUIN_DEFAULT_PROVIDER`) override YAML.
4. **Project vs workspace write targets**: Check `defaults.write_root` and `PENGUIN_WRITE_ROOT`; change at runtime via `RuntimeConfig` or the Web API (`/api/v1/system/config/execution-mode`).
5. **Web interface not accessible**: Check `HOST`/`PORT` bind and auth settings (see below).

For detailed debugging, run `penguin config debug` or set `PENGUIN_DEBUG=true`.

## Web Server Configuration Notes

The web server is configured **entirely via environment variables** — there is
no `web:` YAML section. Key settings:

- `HOST` / `PORT` — bind address and port (default `127.0.0.1:9000`)
- `PENGUIN_AUTH_ENABLED` — protects HTTP and protected WebSocket endpoints
- `PENGUIN_API_KEYS` — accepted header-based API keys
- `PENGUIN_JWT_SECRET` / `PENGUIN_JWT_ALGORITHM` / `PENGUIN_JWT_EXPIRATION_HOURS` — session tokens
- `PENGUIN_PUBLIC_ENDPOINTS` — routes exposed without auth when needed
- `PENGUIN_ALLOW_INSECURE_NO_AUTH=true` — bypasses the startup block on non-local bind without auth
- `PENGUIN_CORS_ORIGINS` — explicit CORS allowlist (a small dev allowlist is used when unset, not `*`)
- `PENGUIN_MAX_UPLOAD_BYTES` — server-side upload cap
- `PENGUIN_GITHUB_WEBHOOK_DELIVERY_TTL_SECONDS` — in-memory replay-defense TTL
- `GITHUB_WEBHOOK_SECRET` — GitHub webhook signing secret

### Recommended deployment defaults

#### Local development

```bash
PENGUIN_AUTH_ENABLED=false
HOST=127.0.0.1
PORT=9000
```

#### Exposed deployment

```bash
PENGUIN_AUTH_ENABLED=true
PENGUIN_API_KEYS=replace-me
PENGUIN_CORS_ORIGINS=https://penguin.example.com
HOST=0.0.0.0
PORT=9000
```

#### GitHub webhooks with auth enabled

```bash
PENGUIN_AUTH_ENABLED=true
PENGUIN_API_KEYS=replace-me
PENGUIN_PUBLIC_ENDPOINTS=/api/v1/integrations/github/webhook
GITHUB_WEBHOOK_SECRET=replace-me
HOST=0.0.0.0
PORT=9000
```

Environment variables are the preferred credential path for provider secrets in headless/server/container usage. Legacy plaintext JSON credential persistence remains compatibility fallback only.

## Configuration Validation

Penguin validates required workspace configuration on launch (see `penguin
config check` and the startup completeness check in `penguin/cli/cli.py`). A
workspace-only configuration with no model connected is valid; you can run
`penguin config setup` to connect a model later. There is no hard startup
validation of API keys, paths, or resource limits beyond the completeness
check — runtime errors surface as warnings and in `penguin config debug`.
