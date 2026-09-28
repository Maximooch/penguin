# Docs Audit, Config-System Findings & Agent-Interop Standards Review

Date: 2026-08-17
Status: For review (no commits made)
Scope: Configuration docs accuracy pass + agent-interop standards research

## 1. What Changed (Docs)

Docs updated to match the actual code surface (verified by grepping the
implementation, not by trusting the docs):

| File | Change |
| --- | --- |
| `docs/docs/configuration.md` | Full rewrite of the config guide. Removed invented env vars (`DEFAULT_MODEL`, `DEFAULT_PROVIDER`, `TEMPERATURE`, `PROJECT_AUTO_CHECKPOINT`, `MEMORY_PROVIDER`, `EMBEDDING_MODEL`, `TASK_COMPLETION_PHRASE`, …) and invented YAML sections (`logging:`, `providers:` with `api_key`/`models`, `web:`, `paths:`, `project.storage`/`project.execution`). Documented the actual `penguin/config.yml` schema, the real precedence chain (incl. `PENGUIN_CONFIG_PATH` and `.penguin/settings.local.yml`), real env vars (`PENGUIN_DEFAULT_MODEL`, `PENGUIN_CLIENT_PREFERENCE`, `PENGUIN_TEMPERATURE`, `PENGUIN_STREAMING_ENABLED`, web-server vars, …), `/config` slash-command semantics, and corrected the `penguin --config config.prod.yml` claim (no such flag; `PENGUIN_CONFIG_PATH` is the mechanism). |
| `docs/docs/advanced/security.md` | Removed `PENGUIN_SECURITY_MODE` (does not exist in code — security mode comes from YAML or `RuntimeConfig`/API). Fixed `/config runtime set security_mode read_only` (no `/config runtime` subcommand exists) → replaced with the real `PATCH /api/v1/security/config` and `POST /api/v1/security/yolo` endpoints. |
| `docs/docs/api_reference/model_config.md` | Removed `PENGUIN_USE_ASSISTANTS_API` / `PENGUIN_USE_NATIVE_ADAPTER` env vars (not read anywhere). Added the real env vars (`PENGUIN_CLIENT_PREFERENCE`, `PENGUIN_USE_RESPONSES_API`, `PENGUIN_INTERRUPT_ON_ACTION`, reasoning vars, `PENGUIN_OPENAI_SERVICE_TIER`) and the real dataclass fields. |

Kept accurate as-is: `runtime_config.md` (all `set_*` methods exist, observer
signature matches), `api_server.md` runtime-config section, `web_interface.md`
env vars, `getting_started.md`, `run-mode.md`, `orchestration.md`,
`runtime-events.md`.

## 2. Bugs / Issues Found (in code and docs)

### 2.1 Doc bugs fixed above
1. `configuration.md` claimed a `--config` CLI flag and env-var/YAML surface that never existed.
2. `security.md` documented `PENGUIN_SECURITY_MODE` — code has no reader for it.
3. `security.md` documented `/config runtime set security_mode read_only` — the `/config` handler only implements `list|get|set|add|remove`.

### 2.2 Code issues worth a look (not fixed — out of scope)
1. **`penguin/config.py` has a silent default mismatch for
   `diagnostics.max_context_tokens`:**
   ```python
   max_context_tokens=config_data.get("diagnostics", {}).get(
       "max_context_tokens", 400000 # TODO: Possible culprit. Make this a default value in the config.yml
   ```
   The `DiagnosticsConfig` dataclass default is `200000`, the hardcoded
   fallback in `Config.load_config()` is `400000`, and the package
   `penguin/config.yml` does not set `diagnostics.max_context_tokens` at all.
   So the *effective* default (400000) silently disagrees with the dataclass
   contract (200000), and the literal `TODO: Possible culprit` comment is still
   shipped. Either set the value in `config.yml` (and make the dataclass read
   it), or align the two fallbacks.
2. **`config.yml` at repo root has the comment `# I think this is redundant`** — the file is a dev-repo default that largely duplicates `penguin/config.yml`. Either delete it (and confirm the loader doesn't depend on it) or document it as intended.
3. **`CLIRenderer._load_cli_display_config`** reads `config.get('cli', {})` with `isinstance(config, dict)` — works because the startup config is a dict, but the pattern of some components using `config.get()` (dict API) and others `config.some_attr` (object API) is fragile. `Config` dataclass (`penguin/config.py:1338+`) and the raw dict coexist; there is no single typed accessor.
4. **`PENGUIN_WRITE_ROOT`** is read by `RuntimeConfig.__init__` and by `path_utils.get_default_write_root()`; but `set_config_value` writes to `.penguin/settings.local.yml` — env vars are **not** persisted by `/config set`. Docs now say this clearly; the code has no warning when an env var shadows a `/config set` value.
5. **Model env var duplication:** `PENGUIN_MAX_OUTPUT_TOKENS` vs `PENGUIN_MAX_TOKENS`, `PENGUIN_MAX_CONTEXT_WINDOW_TOKENS` vs `PENGUIN_CONTEXT_WINDOW`, `PENGUIN_OPENAI_SERVICE_TIER` vs `OPENAI_SERVICE_TIER` — the code has literal `# TODO: renaming Penguin env vars` comments. Worth a deprecation pass.
6. **`web/server.py` restart message** references `PENGUIN_AUTH_ENABLED=false` as the way to run local-only without auth — fine, but `PENGUIN_ALLOW_INSECURE_NO_AUTH` + `PENGUIN_AUTH_ENABLED` interplay is subtle and now documented in two places (configuration.md and web_interface.md); consider a single source of truth.

## 3. Suggestions

1. **Single source of truth for env vars.** There is no central registry of
   "env var → config key → YAML key". `ModelConfig.from_env()` hardcodes
   `os.getenv(...)` calls; `config.py` reads another set; web server reads
   another. A table in `docs/docs/configuration.md` exists now, but a code-side
   `ENV_VAR_REGISTRY` (or even a test that asserts docs env vars ⊆ code env
   vars) would prevent drift. A cheap first step: a pytest that greps the docs
   for `PENGUIN_*` and asserts each appears in `penguin/` source.
2. **Finish the `Config` dataclass migration.** `load_config()` returns a dict;
   `Config.load_config()` builds a typed dataclass with `SecurityConfig`,
   `AuditConfig`, `OutputConfig`, `DiagnosticsConfig`, `AgentPersonaConfig`,
   `AgentModelSettings`. Callers mix `config.get('tools', {})` (dict) and
   `config.security_mode` (object). Pick one access path and enforce it with
   typing.
3. **`settings.local.yml` discoverability.** `.penguin/` is git-ignored by
   convention (`.penguin/.gitignore`), which is right — but there is no
   `penguin config path` command to print which file would be written.
   `get_project_config_paths()` exists; expose it as a CLI command.
4. **Deprecate the env-var aliases** (`PENGUIN_MAX_TOKENS`, `PENGUIN_CONTEXT_WINDOW`, `OPENAI_SERVICE_TIER`) with a warning log, then remove in a major bump.
5. **`penguin config check` should validate `diagnostics.max_context_tokens` default divergence** (see 2.2.1) — fail loudly rather than silently using 400000.

## 4. Strong Questions / Clarifications

1. **Is `config.yml` at the repo root intentional?** The loader treats
   `<repo_root>/config.yml` as "dev repo default" (layer 2), and this repo's
   copy is labeled "I think this is redundant". If it's vestigial, delete it
   and add a test that the loader works without it. If it's a deliberate dev
   override, document what it overrides and why it exists separately from
   `penguin/config.yml`.
2. **Should `docs/docs/configuration.md` be split?** It is now ~630 lines.
   Candidates: Web-server config (env vars) → `web_interface.md` or its own
   page; Prompt composition → `prompting.md`; Security → already split
   (`advanced/security.md`). Or keep one page as the operator's index and link
   out. Which does the docs maintainer prefer?
3. **Who owns `docs/` freshness?** The drift was large (invented YAML
   sections, invented env vars). Is there appetite for a docs-vs-code CI check
   (suggestion 1) or is this a one-time pass?
4. **`diagnostics.max_context_tokens` — which is the truth?** YAML default
   (300000?) or the hardcoded 400000? The answer changes what `config check`
   should report and what the docs should say. (This is a real correctness
   question — see 2.2.1.)
5. **Does Penguin want an `agent.json`-style self-description?** If ACP/Zed
   interop is a goal (see §5), Penguin needs a machine-readable agent card.
   Where should it live — package data, a CLI `penguin acp` command, or a web
   endpoint?

## 5. Agent-Interop Standards Research (OpenCode, Codex, Hermes, ACP, A2A)

### 5.1 Terminology — two different "ACPs"

- **Agent Client Protocol (ACP)** — originally by Zed; **client↔agent** editor
  integration (agent runs as a server inside an editor like Zed). JSON-RPC /
  nd-JSON over stdio. Has a **registry** (`agent.json` cards) at
  `cdn.agentclientprotocol.com`. This is what OpenCode's `opencode acp` and
  Hermes's `acp_adapter` implement.
- **Agent Communication Protocol (ACP, IBM)** — agent↔agent protocol; per
  current guidance it has **merged into Google's A2A under the Linux
  Foundation** (June 2025). IBM's docs now point users at A2A migration paths.
  Do not build new work on the standalone IBM ACP.

The user's "ACP" reference is ambiguous; the actionable reading is **Zed's ACP
(Agent Client Protocol)** for editor/tool integration, and **A2A** for
agent-to-agent orchestration (which is exactly what Link plans).

### 5.2 What the referenced projects actually do (evidence in-repo)

- **Hermes** (`reference/hermes-agent/`): ships a real ACP adapter
  (`acp_adapter/` with `server.py`, `auth.py`, `edit_approval.py`,
  `permissions.py`, `provenance.py`, `session.py`, `tools.py`, `events.py`)
  using the `agent-client-protocol==0.9.0` PyPI package, plus an ACP registry
  entry (`acp_registry/agent.json`) advertising `hermes-agent[acp]` via uvx.
  It implements auth handshake, session management, edit approval, MCP server
  advertising (`McpServerHttp/Sse/Stdio`), and protocol-version negotiation
  against `acp.PROTOCOL_VERSION`.
- **OpenCode** (`context/docs_cache/opencode_cli.md`): `opencode acp` starts
  an ACP server over stdio nd-JSON. So OpenCode is ACP-capable as an agent
  server.
- **Codex** (`reference/codex/`): no ACP/A2A surface found in the reference
  checkout; OpenAI's interop story is MCP client support and the Agents SDK.
  (A2A announced OpenAI support in principle; nothing shipped in this
  checkout.)

### 5.3 Current standards landscape (as of research date)

- **A2A (Agent2Agent)** — Google → Linux Foundation, open protocol, v0.3:
  JSON-RPC 2.0 over HTTP(S), Agent Card discovery (`/.well-known/agent-card.json`),
  stateful Task lifecycle (submitted/working/input-required/completed/failed),
  SSE streaming, optional gRPC binding. Purpose: **agent-to-agent task
  orchestration**. Broad vendor adoption (LangChain, CrewAI, AutoGen,
  Salesforce, ServiceNow …).
- **MCP (Model Context Protocol)** — tool/resource access standard. Penguin
  already ships an MCP client (`penguin/integrations/mcp/`, `MCPToolProvider`)
  and documents it (`docs/docs/system/mcp.md`, `api_reference/mcp-tools.md`).
- **ACP (Zed)** — client↔agent editor protocol; registry + agent.json cards.
- **MessageBus** — Penguin already has an internal
  `penguin/system/message_bus.py` (`ProtocolMessage`, singleton bus) described
  as "Lightweight MessageBus for agent/human routing (Phase 3)". This is the
  natural seam for a future A2A adapter, but it is **internal-only today**.

### 5.4 Recommendation for Penguin

- **Tool level:** keep MCP as the tool-interop standard; it is already
  implemented and documented.
- **Editor/client level (optional):** if Zed/editor integration is desired,
  adopt **Zed ACP** by mirroring Hermes's approach — `agent-client-protocol`
  dependency, an `acp_adapter` package, a `penguin acp` entry point, and an
  `agent.json` registry card. This is small, proven, and orthogonal to Link.
- **Orchestration level (Link):** plan for **A2A** as the wire protocol
  between Link and Penguin instances, per the existing `context/link/`
  design (which already names A2A + SSE). Key gaps to close before adoption:
  1. Penguin needs an **Agent Card** (endpoint, auth, capabilities, skills) —
     see §4.5.
  2. Penguin's internal `MessageBus`/`ProtocolMessage` should map onto A2A's
     Task lifecycle (submitted → working → input-required → completed/failed)
     rather than inventing a parallel state model.
  3. Decide **auth**: A2A handshake must advertise at least one auth method
     (Hermes's `auth.py` shows the pattern — terminal-setup fallback plus
     provider credentials).
  4. Decide transport: HTTP JSON-RPC (+ SSE) is the A2A v0.3 default; gRPC is
     optional. Start with HTTP/SSE.
- **Do NOT** build on IBM's standalone ACP — it has merged into A2A.

### 5.5 Open questions for the Link/ACP decision

1. Is the "ACP" the user means **Zed's Agent Client Protocol** (editor
   integration) or **agent communication** generally? The recommendation
   above covers both readings, but the priority order differs: Zed-ACP is a
   small optional feature; A2A is a Link-blocking architectural decision.
2. Should Penguin expose its own **Agent Card** even before Link exists, so
   third parties (Zed, A2A clients) can discover it?
3. Should the A2A adapter be **inside Penguin** (plugin/dependency) or in
   **Link** (which already owns the A2A server per `context/link/`)? The
   existing design has Link as the orchestrator speaking A2A to Penguin
   instances; Penguin-side work may be limited to an A2A client + Agent Card.
4. Does Penguin's existing `MessageBus`/EventBus need to become the
   transport-neutral bus that both internal components and A2A map onto, or
   is an adapter at the web layer sufficient?

## 6. Files Touched

- `docs/docs/configuration.md` (rewrite)
- `docs/docs/advanced/security.md` (2 fixes)
- `docs/docs/api_reference/model_config.md` (env table, class diagram, examples)
- `context/design/docs-audit-and-agent-interop.md` (this file)

No commits were made. Everything is staged for manual review.
