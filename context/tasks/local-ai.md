# Local AI And Ollama Integration

## Status

Deferred follow-up. Do not expand the Windows first-run/onboarding branch to include this work.

## Goal

Make locally hosted AI a first-class Penguin connection path, beginning with credentialless Ollama discovery and model selection.

The primary use case is a model server running on the user's machine or local network. Cloud-hosted Ollama and authenticated remote endpoints are secondary cases and must not force cloud-oriented credential UX onto local users.

## Problem Statement

Penguin currently exposes Ollama in the provider connection dialog but falls back to the generic non-OpenAI auth method:

```json
{"type": "api", "label": "API key"}
```

That is incorrect for the dominant Ollama workflow. A normal local Ollama installation:

- listens on a local endpoint, commonly `http://localhost:11434`;
- does not require an API key;
- exposes installed models through its local API;
- should be considered usable based on endpoint reachability, not credential presence.

Current provider state also risks conflating several independent facts:

- an `OLLAMA_HOST` environment variable exists;
- an Ollama server is reachable;
- authentication is configured;
- at least one model is installed;
- the selected model is compatible with Penguin's tool and context requirements.

These need explicit semantics.

## Product Decisions

### Locked Direction

- Local Ollama must not request an API key.
- `http://localhost:11434` should be the default discovery endpoint.
- Users may specify a different local or remote server URL.
- Authentication for custom remote endpoints is optional unless the endpoint requires it.
- Ollama Cloud should be represented as a distinct credentialed connection mode rather than silently changing the meaning of local Ollama.
- Provider discovery and model discovery are separate states.
- A reachable server with no installed models should produce an actionable empty state, not appear broken.

### Open Questions

- Should **Ollama Cloud** be a separate provider entry, or an advanced connection mode beneath Ollama?
- Should Penguin support arbitrary OpenAI-compatible local servers in this task, or keep v1 Ollama-specific?
- Which local engines should follow after Ollama: LM Studio, llama.cpp server, MLX, vLLM, LocalAI, or another OpenAI-compatible endpoint?
- Should LAN endpoints require an explicit security warning before sending prompts or workspace-derived context?
- How should Penguin represent model capabilities when the local server reports incomplete metadata?

## Proposed User Experience

### Connect Provider Dialog

Selecting Ollama should open a connection flow such as:

```text
Connect Ollama

> Use local Ollama
  Enter server URL
  Connect Ollama Cloud
```

`Connect Ollama Cloud` may be omitted until cloud support is deliberately implemented.

### Local Discovery

For **Use local Ollama**:

1. Probe `http://localhost:11434` with a short timeout.
2. If reachable, fetch installed models.
3. Show the detected server version when available.
4. Allow the user to select an installed model.
5. Persist the endpoint and selected model without writing a fake API credential.

Example success state:

```text
Local Ollama detected
http://localhost:11434

Installed models:
> qwen3:8b
  llama3.2:3b
  deepseek-r1:14b
```

### Custom Server URL

For **Enter server URL**:

1. Ask for an HTTP or HTTPS endpoint.
2. Normalize and validate the URL.
3. Probe the server.
4. Fetch installed models.
5. If the server returns an authentication error, offer an optional token/header configuration step.
6. Persist endpoint and authentication independently.

Do not label the first field “API key.” The required value is an endpoint; credentials may not exist.

### Offline Or Unreachable State

```text
Could not reach Ollama at http://localhost:11434.

- Start Ollama and try again
- Enter another server URL
- Cancel
```

The error should distinguish:

- connection refused;
- timeout;
- invalid response/non-Ollama service;
- TLS/certificate failure;
- authentication required;
- reachable server with no models installed.

## Provider State Model

Avoid reducing local provider state to one `connected` boolean internally. Track enough detail to explain what is wrong.

Suggested state:

```text
configured   endpoint exists in Penguin configuration
detected     endpoint responded as a compatible server
authorized   no auth required or supplied auth succeeded
ready        at least one usable model is available
selected     a valid model is selected
```

The OpenCode-compatible API may still expose a summarized `connected` value, but Penguin-specific metadata should preserve the richer state.

Suggested rule:

```text
connected = detected && authorized
```

Model readiness should remain separate:

```text
ready = connected && usable_model_count > 0
```

Do not infer reachability merely from `OLLAMA_HOST` being set.

## Discovery And API Behavior

### Default Endpoint

Use this precedence unless existing configuration conventions require otherwise:

1. explicitly saved Penguin Ollama endpoint;
2. `OLLAMA_HOST`;
3. `http://localhost:11434`.

Normalize trailing slashes and reject unsupported URL schemes.

### Health And Identity Probe

Use an Ollama-native lightweight endpoint where available. Validate that the response is plausibly Ollama rather than treating any HTTP 200 as success.

Requirements:

- bounded connect and response timeout;
- cancellation support;
- no retries on the interactive request path beyond one deliberate retry action;
- no server stack trace shown to the user;
- no long blocking request during TUI startup.

### Model Discovery

Fetch locally installed models from the Ollama API and map them into Penguin/OpenCode provider payloads.

Preserve:

- exact model/tag identifier;
- display name;
- size when available;
- modification timestamp when available;
- family/parameter/quantization metadata when available;
- context length and capabilities only when known or safely inferred.

Do not claim tool calling, vision, reasoning, or context-window support solely from the model name unless the inference is explicit and conservative.

### Refresh

- Refresh when the user opens Ollama's model picker.
- Provide an explicit refresh action.
- Cache successful discovery briefly.
- Do not poll continuously.
- If the server becomes unavailable, retain the saved endpoint but update detected/ready state.

## Authentication Model

### Local Ollama

- No credential prompt.
- No placeholder API key.
- Do not write an auth record merely to mark the provider connected.
- Persist endpoint configuration separately from provider credential storage.

### Authenticated Remote Ollama

If support is added, allow an optional bearer token or configurable header without assuming one universal Ollama auth protocol.

Security requirements:

- store secrets through Penguin's provider credential mechanism;
- redact tokens from logs, errors, screenshots, and endpoint payloads;
- never append credentials to URLs;
- support removing the credential without deleting the endpoint;
- validate authentication with a bounded server request.

### Ollama Cloud

Treat cloud authentication as an explicit mode with its own labels, instructions, endpoint semantics, and tests. Do not make local users pass through a cloud API-key screen.

## Configuration Shape

Exact schema should follow Penguin's current configuration architecture, but conceptually separate endpoint and auth:

```yaml
providers:
  ollama:
    endpoint: http://localhost:11434
    mode: local

model:
  provider: ollama
  id: qwen3:8b
  client_preference: native
```

If the current schema stores model records rather than provider records, introduce the smallest compatible representation. Do not add a broad new provider abstraction solely for this task unless existing structures cannot safely represent an endpoint without a credential.

## Runtime Requirements

- Ollama client construction must not require an API key.
- Startup must remain lazy when Ollama is configured but unavailable.
- Prompt submission should produce an actionable endpoint/model error.
- Switching from a remote provider to Ollama should rebuild the runtime client cleanly.
- Switching Ollama endpoints should invalidate cached models and clients.
- Cancellation must propagate to local streaming requests promptly.
- Tool schemas must only be sent when the selected local model/server combination supports them.
- A local request must not silently fall back to OpenRouter or another cloud provider.

## Security And Privacy

Local AI is often chosen specifically for privacy. Penguin must not undermine that expectation.

- Never fetch a cloud catalog merely because Ollama was selected.
- Never route a local model request through OpenRouter as a fallback.
- Clearly identify the destination endpoint before first use.
- Warn when the endpoint is non-local or uses plaintext HTTP over a non-loopback address.
- Do not expose workspace content during health or model discovery requests.
- Keep telemetry and diagnostics free of prompts and credentials.
- Document that remote/LAN endpoints receive the content sent to the selected model.

## Testing Plan

### Deterministic Fake Ollama Server

Create a local test server implementing the minimum relevant endpoints and modes:

- healthy server with several models;
- healthy server with no models;
- connection refused;
- delayed response/timeout;
- invalid JSON;
- non-Ollama HTTP service;
- authentication required;
- authenticated success;
- streaming generation;
- hanging stream cancelled by Penguin;
- server disconnect during streaming.

### Unit Tests

- [ ] Endpoint precedence and normalization.
- [ ] Loopback versus LAN/remote classification.
- [ ] Credentialless auth-method mapping.
- [ ] Provider state derivation.
- [ ] Model payload normalization.
- [ ] Conservative capability mapping.
- [ ] Secret redaction.

### API/Integration Tests

- [ ] `/provider` exposes Ollama even when no credential exists.
- [ ] `/provider/auth` does not advertise a required API key for local Ollama.
- [ ] Local detection updates provider state without creating an auth record.
- [ ] Installed models populate `/config/providers` and `/provider`.
- [ ] No-model state is distinguishable from unreachable state.
- [ ] Custom endpoint persists independently from credentials.
- [ ] Changing endpoint invalidates the cached catalog.
- [ ] Prompting through fake Ollama works without an API key.
- [ ] Abort returns the session to idle promptly during a hanging local stream.
- [ ] No cloud fallback occurs on local failure.

### Interactive Tests

- [ ] Start Ollama with at least one installed model.
- [ ] Open **Connect a provider** and select Ollama.
- [ ] Confirm local detection without credential entry.
- [ ] Select a model and complete a prompt.
- [ ] Interrupt generation with one `Esc`.
- [ ] Stop Ollama and confirm the TUI shows an actionable disconnected state.
- [ ] Restart Ollama and refresh without restarting Penguin.
- [ ] Test a workspace path containing spaces on Windows.
- [ ] Test Docker/Codespaces where `localhost` may refer to the container rather than the host.

## Codespaces, Containers, And Remote Development

Localhost semantics need explicit treatment:

- In Codespaces, `localhost:11434` refers to the Codespace container/VM, not the user's laptop.
- In Docker, host Ollama may require `host.docker.internal` or an explicit network address.
- In WSL, Windows-hosted Ollama reachability depends on networking mode and firewall settings.
- Remote SSH development has the same host-boundary issue.

The connection UI should not claim “Local Ollama not installed” when the real issue is that Penguin and Ollama run on different machines. Errors and documentation should explain the endpoint boundary.

## Broader Local AI Follow-Ups

After Ollama is solid, evaluate a generic OpenAI-compatible local provider path for:

- LM Studio;
- llama.cpp server;
- vLLM;
- LocalAI;
- MLX-backed servers;
- other self-hosted OpenAI-compatible endpoints.

Reuse common endpoint, optional-auth, discovery, security-warning, and cancellation primitives. Avoid adding one nearly identical provider implementation per local engine when a tested compatible transport is sufficient.

Keep engine-native integrations where they provide material value, such as richer model discovery or lifecycle management.

## Implementation Phases

### Phase 1: Correct Connection Semantics

- [ ] Remove required API-key UX for local Ollama.
- [ ] Add endpoint configuration with the default local URL.
- [ ] Represent endpoint configuration separately from credentials.
- [ ] Add reachable/authorized/ready state semantics.
- [ ] Add deterministic route and provider-state tests.

### Phase 2: Discovery And Model Selection

- [ ] Probe the configured Ollama endpoint.
- [ ] Fetch and normalize installed models.
- [ ] Populate provider/model dialogs.
- [ ] Add refresh and actionable empty/error states.
- [ ] Add fake-server integration tests.

### Phase 3: Runtime And Cancellation

- [ ] Construct the Ollama client without credentials.
- [ ] Validate non-streaming and streaming prompts.
- [ ] Validate tool support conservatively.
- [ ] Verify abort-to-idle behavior.
- [ ] Prevent implicit cloud fallback.

### Phase 4: Remote And Cloud Modes

- [ ] Add optional authentication for custom remote servers if justified.
- [ ] Add LAN/plaintext security warnings.
- [ ] Decide and implement Ollama Cloud as an explicit mode.
- [ ] Document Codespaces, Docker, WSL, and remote-SSH endpoint behavior.

### Phase 5: Generic Local Provider Support

- [ ] Extract reusable local endpoint primitives.
- [ ] Evaluate OpenAI-compatible local engines.
- [ ] Add only the provider surfaces supported by real user demand and test coverage.

## Exit Criteria

- [ ] A default local Ollama installation can be connected without any API key.
- [ ] Penguin detects reachability rather than inferring it from `OLLAMA_HOST`.
- [ ] Installed Ollama models appear in the TUI model picker.
- [ ] Empty, unreachable, unauthorized, and ready states are distinguishable.
- [ ] Local prompt streaming and cancellation work reliably.
- [ ] Local failures never silently route prompts to a cloud provider.
- [ ] Remote endpoint credentials, if supported, are optional and stored securely.
- [ ] Codespaces/container localhost limitations are documented.
- [ ] Deterministic fake-server coverage exists for discovery, errors, streaming, and cancellation.

## Related Tasks

- `context/tasks/gui-testing.md` — synthetic user flows for real desktop/terminal environments.
- `context/tasks/cross-platform-interactive-vms.md` — infrastructure for interactive OS testing.
- `context/tasks/tui-testing.md` — TUI startup, model selection, interrupt, and exit validation.
- `context/tasks/llm-provider-contract.md` — provider/runtime boundary and normalization work.
- `context/tasks/llm-testing-suite-overhaul.md` — deterministic provider testing strategy.
