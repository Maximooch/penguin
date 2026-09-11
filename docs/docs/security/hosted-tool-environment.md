# Hosted tool environments

## Scope

`PENGUIN_TOOL_ENVIRONMENT=hosted` limits environment inheritance in the audited tool subprocess launchers.
The default, `local`, preserves existing behavior for trusted local use.
An unknown value raises an error instead of selecting local mode.

This policy is defense in depth. It is not a sandbox or a multi-tenant security guarantee.
Do not enable hosted execution credentials until the separate isolation gate passes.

## Implemented behavior

Hosted subprocesses inherit only `PATH`, `LANG`, `LC_ALL`, `LC_CTYPE`, `TZ`, `SYSTEMROOT`, and `WINDIR`.
Unknown variables do not pass through, including provider keys and Link service credentials.
The operator must keep secrets out of these permitted variables.

Trusted launch code can supply an immutable per-execution environment through `tool_environment_scope()`.
This internal context is not part of the request schema or tool arguments.
The scope restores the previous context on exit, including exceptions.
`asyncio.to_thread()` carries this context. Raw thread launchers require explicit context propagation.

Tool arguments cannot replace reserved bootstrap, identity, interpreter, loader, Git, or proxy variables.
They also cannot replace values in the trusted context.
This rule validates the tool API. Shell code can still assign variables inside its own process.

Hosted mode refuses the in-process notebook Python tool before it executes code.
The error directs the agent to the subprocess command tool.
The local notebook behavior remains unchanged.

Audited launch sites include persistent processes, notebook shells, legacy process tools, lint tools, Git helpers, search helpers, and validation commands.
The source regression requires an explicit environment at these subprocess sites.
It does not prove that third-party libraries or plugins use the same policy.

The authenticated Link capability response includes `tool_environment.version = 1` and the current mode.
It explicitly reports `execution_isolation = false` and `remote_credential_delivery = false`.
The capability must not authorize credential injection by itself.

## Deployment procedure

1. Keep hosted credentials disabled during this rollout.
2. Set `PENGUIN_TOOL_ENVIRONMENT=hosted` in the trusted service configuration.
3. Restart the service during an approved maintenance window.
4. Verify the authenticated capability response reports `mode: hosted`.
5. Run a harmless command through the actual tool path with a synthetic parent secret.
6. Verify the child cannot read that environment value.
7. Verify the notebook tool refuses in-process Python.
8. Verify explicit cancellation still stops the child process.

Local mode restores inheritance for trusted local use. It is not a safe production fallback.
This PR does not deploy the mode or modify existing runtime credentials.

## Follow-up sequence and activation gates

No configuration provides perfect security. These gates define specific threats and evidence instead of an absolute guarantee.

### 1. Isolated execution before hosted credential delivery

- [ ] Select and pin one runtime provider before Link PR 1.
- [ ] Separate agent-controlled execution from the server filesystem, processes, user identity, and network authority.
- [ ] Exclude the Docker socket, host home directories, service configuration, provider keys, and control-plane credentials from workloads.
- [ ] Use separate writable storage for concurrent execution scopes.
- [ ] Restrict private-network and metadata-service access through infrastructure policy.
- [ ] Refuse execution when isolation is unavailable. Never fall back to the server process.
- [ ] Test two hostile workloads for cross-scope file, process, credential, and network access.
- [ ] Test replacement and cancellation of workloads, including background descendants.

The existing experimental container executor is not proof of this gate.
It includes a host `/tmp` mount and a fallback when Docker is unavailable.
Do not activate that path as the hosted security boundary without a separate review.

### 2. Link bootstrap and scoped authority

- [ ] Bundle a pinned `lk` artifact and its dependencies in the workload image.
- [ ] Bind each credential to the admitted workspace, agent, execution, source, resources, and permitted operations.
- [ ] Recheck current authorization on each protected operation and renewal.
- [ ] Keep rotating credentials out of prompts, receipts, snapshots, and frozen dispatch payloads.
- [ ] Keep the durable worker as the owner of automatic final replies.
- [ ] Test wrong-workspace access, revoked membership, concurrent executions, renewal, replay, and Stop.
- [ ] Keep credential expiration separate from execution duration. Do not impose an implicit run deadline.

### 3. GitHub and service access

- [ ] Keep GitHub App private keys in trusted infrastructure.
- [ ] Mint repository-restricted installation tokens with Octokit and explicit permissions.
- [ ] Define whether workloads receive short-lived tokens or only brokered operations.
- [ ] Enforce denied operations outside agent prompts and CLI conventions.
- [ ] Evaluate OpenSandbox Credential Vault or Infisical Agent Vault before building a custom proxy.
- [ ] Enforce proxy routing outside the workload. An `HTTPS_PROXY` variable alone is bypassable.
- [ ] Test destination, method, path, redirect, and repository restrictions.
- [ ] Test outstanding credentials after revocation, not only renewal refusal.

### 4. Remaining execution and supply-chain surfaces

- [ ] Audit MCP servers, plugins, browser processes, Git hooks, package scripts, and third-party subprocess launchers.
- [ ] Keep custom runtime extensions inside the workload boundary, not the trusted service.
- [ ] Remove unused in-process execution paths from hosted tool registration.
- [ ] Scan images and dependencies, pin artifacts, and verify signatures or provenance where available.
- [ ] Prevent secrets in logs, crash dumps, snapshots, artifacts, and process arguments.
- [ ] Define patching, credential rotation, incident response, retention, and backup procedures.
- [ ] Add independent security review and recurring adversarial tests before multi-tenant launch.

## References

- [gVisor security model](https://gvisor.dev/docs/architecture_guide/security/)
- [OpenSandbox Credential Vault](https://github.com/opensandbox-group/OpenSandbox/blob/main/docs/guides/credential-vault.md)
- [Infisical Agent Vault](https://github.com/Infisical/agent-vault)
- [Octokit App authentication](https://github.com/octokit/auth-app.js)

References are design inputs, not evidence that Penguin passes the activation gates.
