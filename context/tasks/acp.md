# Penguin ACP implementation and conformance audit

Updated October 28, 2026. This file supersedes the original phase checklist with the implemented state and remaining gates. The stack is draft and unmerged. It is not a claim of complete ACP parity.

## Contract and evidence

Penguin acts as an ACP agent over `penguin acp` stdio. The implementation targets protocol v1 using `agent-client-protocol>=0.12.1,<0.13`, Pydantic 2 and MCP 1.x. It is independent of the A2A HTTP server and MCP tools. The SDK includes resource links; earlier notes claiming it did not were incorrect. Published session deletion and exact prompt-request cancellation need explicit schema-validated transport handlers because the pinned SDK does not route them. Most RPCs and all client RPCs still use the official SDK.

Primary references:
- https://github.com/agentclientprotocol/agent-client-protocol/blob/main/docs/protocol/v1/overview.mdx
- https://github.com/agentclientprotocol/agent-client-protocol/blob/main/schema/v1/schema.json
- https://github.com/agentclientprotocol/python-sdk

The current subagent RFD and form elicitation are optional negotiated/experimental behavior. They are not counted as mandatory v1 features, ACP v2 support, or old AIR extensions.

## Implemented and tested

| Area | Behavior and evidence |
| --- | --- |
| Transport and baseline | Real shipped CLI over subprocess stdio, clean stdout, Unicode, malformed frames, supported version negotiation, provider errors and explicit stop reasons. Tests use a deterministic provider core, not a live model. |
| Input | Text and resource references; local URIs confined to authorized cwd after decoding and resolution, remote references never automatically fetched. PNG/JPEG/WebP only on a vision-enabled selected model; bounded embedded text/binary storage. Audio is rejected and not advertised. |
| Ownership | One ACP root session maps to one native conversation and immutable cwd. Indexed ACP metadata is required on reload; legacy or foreign-root sessions are rejected. File reads/writes continue through normal tool permissions. |
| Additional roots | Absolute existing roots inside launch-authorized directories, fixed during a turn. Load/resume activates the complete requested list, with cwd unchanged; list reports it. File permissions, URI references, native diffs, child execution and persisted goals retain the scope. Per-session attachment copies are included internally. |
| Lifecycle | New, load with ordered replay, resume without replay, list/filter/page, close, delete. Delete checks ownership, rejects active work/unresolved processes, and removes native history, journal and attachments. Close retains history. |
| Long sessions | Append-only replay journal; native model state saved at turn boundaries. Incomplete final append recovery, malformed complete-record rejection, 2,000-chunk linear-write regression. Reload does not inject a whole transcript into model context. |
| Tools | Scoped stable start/result IDs, bounded content, todo plans, terminal failed updates on interruption. Canonical authorized EditService transactions provide native complete before/after snapshots up to limits; other tools retain textual results. |
| Processes | Actual runtime events update independent execution cards after the initiating turn, without polling or consuming model cursors. Retained output, capture failure and exit status shown. Missing root-process handle after reconnect is explicitly unknown. |
| Permissions | Existing policy enforced; ACP offers allow-once/deny and exact file read/write retention, explicitly until close or remembered for this saved session. /permissions reset revokes retained grants. Timeouts, cancel, close and child completion deny pending requests; no late grants. Multiple pending child approvals preserve requires_action until all resolve. |
| Questions | Actual ActionExecutor question tool, negotiated form answers validated before resolution. Unsupported clients receive a text question for their next message; the tool request is rejected immediately so it cannot wait on an absent web UI. Cancel/close rejects forms. |
| Controls | Per-session configured-model selection and Build/Plan modes, busy changes rejected. Plan appears only with permission enforcement and cannot become writable after enforcement is disabled. Settings persist; provider choices must be configured locally. `/status` and `/mcp` are local read-only commands. |
| Usage | Session-scoped current context/window telemetry; unknown/global/malformed values omitted. Cost is not fabricated. |
| MCP | Per-session stdio/HTTP/SSE providers, literal client env values, independent context and permissions; server descriptions resent on reconnect, provider closed on session close. Actual isolated local MCP server contracts. |
| Cancel | Whole-turn session/cancel and exact prompt RPC cancellation through $/cancel_request. Running and queued prompt isolation, stale request IDs and continued use are tested over real stdio. |
| Child agents | Current draft negotiation only. Actual runtime lifecycle/public output, directed messages, child tools, nested parentage and replay. Legacy clients get ordinary parent cards. Independently scheduled background children can be cancelled; foreground children sharing a task cannot claim independent cancel. |

## Deliberate limits and exact remaining work

| Gap | Current decision | Requirement to close it |
| --- | --- | --- |
| Client filesystem/terminal RPC | Opt-in client text reads/writes and separately selected foreground client terminals, with no local fallback. Other unsupported file/process tools are hidden/rejected. | Client background handles still need a retained remote-process manager; standard terminal RPC has no stdin operation. Fully remote directories need a virtual-path authority model; richer edits need client transaction/backup semantics. |
| True parallel top-level sessions | A process gate serializes model turns and stateful lifecycle operations because the core conversation manager is shared. Independent runtime background tasks may outlive a turn. | Separate mutable conversation/model/tool state per root session and prove overlapping prompts, models, permissions, reload/close, and cancellation do not contaminate each other. |
| Persisted approvals | Exact-resource read/write grants are now available by explicit choice, until close or remembered for this saved session. Key includes tool, agent, policy, mode, roots and backend; /permissions reset revokes them. | Broader operation-wide, wildcard, process/network/delete and cross-session grants remain intentionally unsupported. Native session storage is the trust boundary; these are not a sandbox against local filesystem tampering. |
| Interactive ACP auth/logout | No interactive auth advertised; use normal local Penguin provider setup. | A provider-specific flow with token storage/refresh/revocation and client negotiation. Editor identity must never become tool authority. |
| Extra model configuration | Configured models and modes only; no arbitrary provider/model IDs, effort or sampling knobs. | Add only knobs the selected backend can validate and apply through request-scoped runtime APIs. |
| Other request cancellation | Exact cancellation is for prompts. Atomic/short control operations and session setup do not implement request cancellation. | Explicit lifecycle rollback/resource cleanup for cancellable MCP discovery and session setup; do not partially cancel permanent deletion. |
| Reconnect and recovery | Native conversation and replay persist; live child execution is not resumed after adapter-process death. Historical child association has no cancel authority. Root process cards check only live owned handles; historical child-process cards cannot reconstruct live work. | Durable supervisor identity/ownership and explicit recovery protocol; reconnect must distinguish known live work from unknown outcomes. |
| Advanced UI extensions | No client-specific goal/task panel, arbitrary native tool renderer, hidden reasoning feed, ACP v2 or older AIR shape. Process output uses standard cards. | Negotiate an actual released/compatible client contract and test that client; do not infer parity from extension count. |
| Diff breadth | Complete snapshots only from the canonical authorized async edit path; deleted/oversized files remain textual. | Additional tool producers must expose trustworthy bounded transaction snapshots, not extra unauthorized reads. |
| Real editor/provider acceptance | Zed 0.208.4 tested with an isolated profile and the actual CLI/adapter plus deterministic provider: handshake, Unicode output, visible tool card and /status discovery. This exposed and fixed command announcements arriving before the new-session response. A live provider and full interactive matrix remain unverified. | Launch a supported editor against this branch with a configured provider; exercise multi-turn tools, approve/deny, image, MCP, cancel, close/reopen and persisted replay. Repeat child tests with a client supporting the current draft. |

Windows process termination uses taskkill tree cleanup, not Windows Job Objects or guaranteed ownership of detached descendants. Tests preserve this distinction.

## Draft PR dependency graph

Baseline sequence: #134 baseline -> #135 tool events -> #136 sessions -> #137 rich input -> #138 replay journal -> #139 contract CI -> #140 session MCP -> #141 controls.

`stack/acp-runtime-base` combines that sequence with separate reliability #133. Then #142 child sessions, with sibling #143 native diffs and #144 child approval cleanup. `stack/acp-progress-base` combines those siblings, followed by #145 process UI -> #147 deletion -> #148 questions. `stack/acp-windows-base` combines that stack with Windows runtime #146 (including environment correction), then #149 cross-platform producer tests -> #150 scoped usage -> #151 exact prompt request cancellation. Then #152 records the audit, #153 additional roots, #154 opt-in client files, #155 foreground client terminals, #156 real permission-request serialization and #157 exact retained approvals. `stack/acp-storage-base` combines #157 with native storage #158 (3d2eb201, including sharing-probe follow-up), preserving both storage and process CI jobs. The editor-ordering follow-up builds on that integration. These are Git branch integrations for review, not merged pull requests.

## Validation gates

- [x] Deterministic real stdio CLI/SDK contracts and negative inputs.
- [x] Actual runtime producers: child lifecycle, authorized edit transactions, process output, question tool, persisted usage.
- [x] Dedicated CI on Windows/Linux and Python 3.11/3.12 with ACP dependencies, no provider secrets.
- [x] Windows native process capture and environment assertions; no skipped Windows ACP producer.
- [x] Locked dependency check and scoped Ruff checks.
- [x] Latest storage/editor integration aggregate: 119 ACP/edit-contract tests passed on Windows Python 3.11.14, no skips; pinned uv 0.11.2 lock check passed. A separate earlier storage run passed 29 tests. The later expanded storage test exposed an assertion that counts retry attempts as new temporary files; tracked independently.
- [x] #151 code-head CI passed, including all four ACP OS/Python jobs and broader repository contracts. Later increments require their own CI.
- [x] Installed Zed deterministic-provider smoke: text, tool card and command discovery.
- [ ] Live-provider and full interactive acceptance as specified above.
- [ ] All optional decisions above revisited before claiming parity for a particular remote/advanced client.

Code aggregate after #151: 111 ACP, native Windows process and environment-policy checks passed, with no skips, on Windows Python 3.11.14. Scoped Ruff and the pinned uv 0.11.2 lock check passed. #149 and #151 full CI passed, including four ACP matrix jobs. Additional-root iteration has its own producer, persisted-goal and protocol tests. Older full-repository failures must be reported separately, not hidden by focused results.

## Editor smoke setup and limit

The isolated fixture lives outside the repository under `Documents/Codex/acp-editor-smoke`. It uses `tests/integrations/test_acp_wire.py`'s deterministic core with the shipped CLI entrypoint. It does not execute a real shell command or call a paid model: the displayed tool event is deterministic. On Windows, launch the Zed CLI with `--user-data-dir <profile> --foreground <workspace>` after the prior test process exits; otherwise an existing process can route the workspace to its own profile. Custom agent configuration follows Zed's documented `agent_servers` command/args/env format. The actual test confirmed `/status` is offered and returns `Mode: build; model: default` after the fix; previously Zed reported that command unsupported.

Command discovery is emitted after the transport writes/drains the matching successful `session/new` response, with a raw stdio order assertion. There is no timing sleep. Direct SDK/in-process use retains its existing callback behavior; the shipped transport handles editor ordering.
