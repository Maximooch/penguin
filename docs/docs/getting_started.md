---
sidebar_position: 2
---

# Getting Started

This guide covers Penguin's current terminal-first installation and first-run flow.

## 1. Install

The recommended installation uses `uv`:

```bash
uv tool install penguin-ai
```

Plain `pip` also works:

```bash
pip install penguin-ai
```

The base package includes the main CLI, terminal UI, and web runtime. Optional extras are available for development and legacy integrations:

```bash
pip install "penguin-ai[all]"          # optional integrations
pip install "penguin-ai[legacy_tui]"   # older Textual prototype
pip install "penguin-ai[dev]"          # contributor tooling
```

Verify the installation:

```bash
penguin --version
penguin --help
penguin-cli --help
```

## 2. First Run

Run:

```bash
penguin
```

On a fresh installation, Penguin runs onboarding **before** launching the terminal UI.

### Workspace

The only required onboarding choice is the workspace location. Penguin stores conversations, memory, notes, logs, projects, and context there. Press Enter to accept the platform-appropriate default:

```text
~/penguin_workspace
```

On Windows this resolves under the current user's home directory, for example:

```text
C:\Users\Alice\penguin_workspace
```

Penguin verifies that the directory can be created and written before saving it.

### Connect an AI model — optional

After selecting a workspace, onboarding asks whether to connect an AI model. You can:

- choose a supported provider and model;
- use an existing provider credential from the environment;
- enter a credential for Penguin to store in its user-level `.env`; or
- choose **Skip for now** at the connection, provider, model, or credential step.

An OpenRouter key is **not required** to install, onboard, or launch Penguin. OpenRouter is one optional provider alongside direct providers and local Ollama models.

If you skip model setup, the TUI still launches. Penguin waits to initialize a provider until a model and any required credential are available. Before sending an AI prompt, connect one by rerunning:

```bash
penguin config setup
```

Rerunning setup preserves existing configuration and uses the current workspace as the default.

## 3. Launching Penguin

All current TUI entrypoints share the same first-run preflight:

```bash
penguin
ptui
penguin-tui
```

Use the headless CLI for scripts and one-off commands:

```bash
penguin-cli -p "Help me debug this Python function"
penguin-cli chat
```

Useful configuration commands:

```bash
penguin config setup   # change workspace or connect a model
penguin config check   # check required workspace configuration
penguin config debug   # inspect resolved configuration
penguin config edit    # open the user configuration file
```

## 4. Interrupting a Running Session

While a prompt, stream, or tool is active in the TUI, press `Esc` once to interrupt it. Penguin sends an abort request, cancels the tracked request, and returns the session to idle without waiting for slow provider or tool cleanup.

Cleanup continues on a best-effort basis in the background. Repeatedly pressing `Esc` should not be necessary.

## 5. Provider Configuration

Provider credentials may be supplied with environment variables:

```bash
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
OPENROUTER_API_KEY=...
```

Local Ollama models do not require an API key.

Model routing can also be configured explicitly:

```bash
PENGUIN_DEFAULT_MODEL=openai/gpt-5.2
PENGUIN_DEFAULT_PROVIDER=openrouter
PENGUIN_CLIENT_PREFERENCE=openrouter
```

A minimal workspace-only configuration is valid:

```yaml
workspace:
  path: ~/penguin_workspace
model: null
```

A connected model configuration looks like:

```yaml
workspace:
  path: ~/penguin_workspace
model:
  default: gpt-5.2
  provider: openai
  client_preference: native
  streaming_enabled: true
```

## 6. Project and Workspace Roots

Penguin separates the project it edits from the workspace where it stores assistant state:

- **Project root:** the current repository or working directory used by file and shell tools.
- **Workspace root:** Penguin's conversations, notes, logs, memory, projects, and context.

Select the file-operation root for a run with:

```bash
penguin --root project
penguin --root workspace
```

Or set the default with `PENGUIN_WRITE_ROOT=project|workspace`.

## 7. Web Runtime

The base install includes the web/API runtime:

```bash
penguin-web
```

By default it listens at `http://127.0.0.1:9000`; API documentation is available at `/api/docs`.

## Troubleshooting

### `OPENROUTER_API_KEY required` on first launch

Current first-run behavior should route to workspace onboarding before any provider client is initialized. If this appears on a fresh install, capture the output of:

```bash
penguin --version
penguin config debug
```

and report which entrypoint was used.

### No AI model connected

Launch is allowed without a provider. Run `penguin config setup` before sending prompts, or select a local Ollama model.

### TUI does not stop immediately after `Esc`

A single `Esc` should return the session to idle promptly. Capture the web-server log around the `/session/<id>/abort` request and report any tool that remains active.

### TUI bootstrap fails

Penguin prefers local TUI sources in a source checkout and otherwise bootstraps a cached sidecar. Advanced overrides include `PENGUIN_OPENCODE_DIR`, `PENGUIN_TUI_BIN_PATH`, and `PENGUIN_TUI_RELEASE_URL`.

### Configuration or permissions fail

Confirm the configured workspace exists and is writable. Use:

```bash
penguin config debug
penguin config edit
```

For additional options, see [Configuration](configuration.md) and the [CLI reference](usage/cli_commands.md).
