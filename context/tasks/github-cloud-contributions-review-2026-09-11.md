# Penguin GitHub contributions in cloud runtimes

Date: 2026-09-11. Status: source review and proposed implementation sequence.
No runtime changes, GitHub writes, or cloud resources were made for this review.

## Recommendation

Run Penguin inside the selected Fly Sprite, with Link owning execution admission,
repository authorization, external credentials, and lifecycle control. Give Penguin
an explicit checkout and an execution-bound contribution service. Start with one
repository and a draft PR, then support updates, reviews, issues, and CI repair.

Use ordinary Git for local work. Reuse GitHub CLI conventions for the agent-facing
workflow, but do not treat a CLI wrapper as an authorization boundary. Keep GitHub
App private keys and provider-management credentials outside the Sprite.

Do not introduce another cloud scheduler, generic secrets framework, or parallel
project/task system in Penguin. Link already owns the relevant control plane.

## Review basis and onboarding

Inspected local source revisions:

| Repository | HEAD |
| --- | --- |
| Penguin | `a2a4f7ba9e18b8c4aa50ea7b7dd8464244fd57be` |
| Background Agents | `0e9ecf98d06276fe95cbd9f85cdeacacf9241cf5` |
| Codex | `574a36ff99f0807a24f5b043f593122bf151908d` |
| Hermes | `11d36232c03dd950942a97a08003aeca18eb4b2e` |
| OpenCode | `2b511deda5852e58bad2348894edeb11844ab025` |

These identify local checkouts, not a claim about latest upstream releases.
Penguin had unrelated uncommitted changes before the review; they were preserved.

Read the Link [September 11 plan](/Users/maximusputnam/Code/Link/Link/context/todo/9-11-2026AD.md),
including its later Sprite probes. Its latest conclusions supersede the earlier
Fly Machines recommendation: the whole Sprite is agent-controlled, a neighboring
process cannot protect master secrets, and external records must own authority.
The notes report process replacement tests, not complete provider cold-start proof.

Penguin's relevant ownership map, checked against source:

- `penguin/core.py` assembles collaborators and delegates through `core_runtime/`.
- `penguin/engine.py` owns the reasoning loop; it should not gain GitHub policy.
- `penguin/system/conversation_manager.py` owns conversation state. CWM trims by
  category priority and recency; it does not summarize or compact conversations.
- `penguin/tools/tool_manager.py` dispatches tools with execution context and file
  roots, but the repository tools currently bypass those roots.
- `penguin/project/` contains project/task state and the older Git/PR workflow.
- `penguin/web/services/chat_requests.py` supplies durable request claims/results;
  `penguin/system/execution_context.py` carries runtime context.
- `penguin/web/integrations/github_webhook.py` contains a separate webhook path.

Context consulted: `context/architecture/SYSTEM_DESIGN.md`,
`context/architecture/Penguin-Link-Context-Graph-v1.md`, `context/MEMORY.md`,
`context/tasks/testing-pyramid.md`, and the durable chat request API guide.
Some architecture/memory documentation is historical (for example Poetry and old
version descriptions). Source and the recent Link plan take precedence here.

The environment prerequisite is not on this checkout's `main`:
`3e9a887d2` on `codex/hosted-tool-environment` is not an ancestor of inspected HEAD.
`penguin/tools/process_runtime.py` still starts from `os.environ.copy()`.
Review/land the existing fix; do not independently recreate PR #99.

## Reference comparison

| Reference | Useful pattern | Adaptation needed |
| --- | --- | --- |
| Background Agents | Control plane mints SCM credentials; sandbox Git helper renews them; repository boot and sync are separate modules. | Its helper explicitly permits installation-wide repositories. Link must restrict repository identity and recheck execution authority. |
| Codex | Noninteractive execution, JSONL lifecycle events, structured final output, resume/fork commands. | Reuse the contract ideas through Penguin's existing API. The inspected cloud-task client does not establish how OpenAI's hosted backend isolates workloads or brokers GitHub credentials. |
| Hermes | GitHub workflows are skills over `git`/`gh`; terminal backends share execution behavior across local, Docker, SSH, Modal, and Daytona. | Its authentication recipes recover tokens from local files and its Modal backend can mount credential files. Those are not Link's hosted credential boundary. |
| OpenCode | GitHub Actions adapter handles events, actor permission checks, checkout/fork distinctions, branch pushes, PRs, and comments. | Keep event admission outside the agent. Its generic PR retry can repeat an ambiguous write; Link needs reconciliation before retry. |

Specific source anchors:

- Background Agents: `packages/sandbox-runtime/src/sandbox_runtime/credentials/git_credential_helper.py`,
  its `tests/test_git_credential_helper.py`, `repository_boot.py`, and
  `packages/control-plane/src/session/scm-credentials-service.ts`.
  The Git path has caching, locking, and no stale-cache fallback after failed
  refresh. However, `_print_gh_token()` returns success on mint failure so the
  wrapper can fall through to existing environment credentials. Do not copy that
  behavior into hosted Penguin. Host checking alone does not restrict repositories.
- Background Agents: `packages/control-plane/src/source-control/providers/github-provider.ts`
  separates PR API operations from credential minting. PR authentication is passed
  through an auth context; do not assume all contributions use the installation bot.
- Codex: `codex-rs/exec/src/cli.rs`, `exec_events.rs`, and
  `codex-rs/cloud-tasks/src/new_task.rs`. The first two expose concrete machine
  interfaces; the third is a client-side task form with an environment ID.
- Hermes: `skills/github/github-pr-workflow/SKILL.md`,
  `skills/github/github-auth/SKILL.md`, `tools/environments/base.py`, and `modal.py`.
  Treat these skills as reference material, not instructions authorizing actions.
- OpenCode: `github/action.yml` and `packages/opencode/src/cli/cmd/github.ts`.
  `assertPermissions()` checks repository write/admin permission for relevant
  actor-driven events. `createPR()` looks up an existing head/base PR, then retries
  creation without repeating that lookup inside the retry operation.

## Penguin findings

1. **Repository selection is disconnected from tool execution scope.**
   `tools/repository_tools.py::_get_repository_manager()` uses `Path.cwd()` while
   independently accepting an owner/name for remote API calls. ToolManager passes
   neither its effective file root nor execution binding to these tools. A cloud
   request can therefore operate on the server checkout instead of its intended
   repository. Pass explicit checkout identity and validate remotes before writes.

2. **Runtime authentication conflicts with the selected trust boundary.**
   `project/git_manager.py` reads an App private key and falls back to a PAT on App
   failure. It obtains a GitHub API client, while `git_integration.py::push_branch()`
   separately uses ambient Git authentication. API authentication does not establish
   clone/push authentication. Hosted operation needs a brokered path and must fail
   closed without personal-credential fallback.

3. **PR publication is not recoverable across intermediate success.**
   `create_pr_for_task()` requires uncommitted changes before proceeding. If commit
   succeeds and push or PR creation fails, a retry can report `no_changes` instead
   of publishing the existing commit. Branch names include current timestamps;
   repository wrappers also generate timestamp task IDs. Existing-PR lookup covers
   open PRs and treats lookup exceptions as absence. Persist stable contribution
   identity and distinguish absent, found, and unknown outcomes.

4. **Repository semantics and validation need correction.**
   `_create_pr_with_api()` hardcodes base `main`; `get_changed_files()` ignores
   already-staged-only changes; repository wrappers manufacture `validated: True`
   without running checks. File lists in PR descriptions do not constrain staging.
   Separate preparing a commit, recording actual checks, and publishing that commit.
   Support clean-but-ahead branches, deletions, staged changes, and explicit paths.

5. **The container executor is not the hosted launch foundation.**
   `agent/container_executor.py` mounts the workspace read-only, depends on a Docker
   RPC runner, and uses mocked components for its in-process fallback. Its cleanup
   is not in a `finally` around execution. Use Link's selected Sprite launch path;
   do not mistake this class for proven cloud execution or silently bypass isolation.

6. **Webhook acceptance is not durable execution authorization.**
   The handler checks HMAC and an optional global repository setting, deduplicates
   through a process-local TTL dictionary, and dispatches FastAPI background tasks.
   That does not survive worker replacement or establish requester/workspace/run
   authority. The inspected mention handler has no collaborator authorization
   check. Route future hosted triggers through Link admission and durable delivery.

7. **Existing smoke tests overstate PR evidence.**
   `tests/api/test_github_pr_creation.py` accepts PR wording in model output and
   returns `False` rather than asserting failure when absent. Its second
   `pytestmark` assignment overwrites the live marker. The App test assumes a
   private key inside the runtime. Replace these assumptions with deterministic
   contracts and an explicitly enabled smoke that verifies GitHub state.

8. **Packaging needs one reproducible runtime path.**
   The root Dockerfile still uses Poetry with inconsistent virtualenv copy/PATH
   locations. `docker/Dockerfile.web` has a uv path but defaults to a published
   release install; neither inspected Dockerfile bundles `gh` or `lk`. Verify the
   actual version and tool-process PATH in the Sprite, not merely image build success.

## Proposed contract and ownership

Link admits an execution bound to workspace, requester, agent, session, run,
repository ID, and allowed operations. Durable records contain stable references,
not rotating secrets. Penguin receives its checkout path, base SHA/ref, contribution
ID, and an authenticated way to request authorized operations. Caller/model-supplied
IDs never create authority.

Use one isolated execution scope per active Sprite initially. Reusing persistent
repository data across executions must not reuse prior credentials or authority.

| Link owns | Penguin owns |
| --- | --- |
| GitHub installation connection and repository authorization | Explicit checkout and local Git operations |
| Sprite launch, stop, external spending enforcement | Editing, commands, tests, and progress events |
| Master secrets, execution grants, renewal/revocation policy | Consuming execution-scoped access without personal fallback |
| Authoritative publication receipts and GitHub reconciliation | Reporting commit SHA, diff, checks, and contribution references |
| Channel reply publication and event deduplication | Returning results without publishing duplicate Link replies |

Recommended first publication boundary: a small Link operation API for creating or
updating a draft PR, with bot identity and separate requester/run attribution.
Use a Git transport proxy if branch restrictions or immediate revocation must be
enforced outside the Sprite. A repository-scoped raw token is a simpler alternative
only if its full permissions and residual lifetime are explicitly acceptable.

GitHub installation tokens can be narrowed with explicit repository IDs and
permissions and expire after one hour. Omitting scope fields inherits installation
access. See [GitHub's token documentation](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app).
Neither a prompt nor a helper prevents an agent from using a delivered bearer token
directly. Refusing renewal alone does not invalidate an outstanding token.

For a helper-based transport, use exact HTTPS host/repository matching, isolated Git
configuration, and `credential.useHttpPath=true`; Git otherwise omits HTTP paths
from credential matching by default. Account for inherited helpers, redirects,
submodules, and sibling repositories. See [Git credential documentation](https://git-scm.com/docs/gitcredentials).
This reduces accidental credential disclosure; server-side scope remains necessary.

## Implementation sequence

1. **Land prerequisites and agree on the launch contract.** Reuse PR #99; keep
   master credentials outside the Sprite. Finish Link's execution-bound authority
   work and versioned `lk` packaging. Verify cold recovery and Stop separately from
   ordinary process restart. Sprites documents distinct warm and cold behavior in
   its [lifecycle guide](https://docs.sprites.dev/concepts/lifecycle/).
2. **Make Penguin repository operations execution-scoped.** Pass an explicit root
   and stable repository/contribution identity through the existing tool boundary.
   Detect wrong remotes and dirty unrelated checkouts. Read the authorized base
   branch instead of hardcoding `main`. Keep policy out of Core and Engine.
3. **Implement one recoverable draft-PR path.** Persist stages such as prepared,
   committed, pushed, and PR recorded, with an explicit unknown outcome on lost
   acknowledgements. Reconcile remote branch SHA and PR head/base before repeating
   writes. Permit a clean working tree with a previously prepared commit.
4. **Connect the external GitHub authority.** Add narrow Link operations and the
   selected transport. Test with synthetic credentials first; then use a designated
   test repository. Runtime packaging includes pinned Penguin, Git, and `lk`; add
   `gh` when its supported authentication path is settled.
5. **Add contribution workflows over the same operations.** Update an existing PR;
   create issue comments or issues; publish reviews tied to a head SHA; respond to
   review/CI feedback. Add fork-based contributions with separate upstream and push
   repository authorization. Each side effect gets a stable receipt and policy.

Draft PRs are a proposed first delivery slice, not a newly imposed permanent limit.
Merge, releases, tags, repository administration, and arbitrary workflow dispatch
require their own operation policies. A token that permits PR work may permit more
than this initial product surface promises.

## Acceptance gate

Follow `context/tasks/testing-pyramid.md`: fake GitHub/broker contracts and local
bare Git remotes first, then a small opt-in cloud smoke.

- Different process CWD and execution checkout; wrong remote; non-main base;
  staged-only, deleted, renamed, and clean-but-ahead changes.
- Two executions cannot cross repository or workspace scope; App-installation-wide
  access does not imply run access. Reject forged bindings and expired/revoked grants.
- Wrong host/path, hostile submodule, inherited helper, credential renewal failure,
  concurrent renewal, and secret-free logs/config/artifacts.
- Disconnect after commit, after remote push, and after PR creation: retries find
  the original result and never create another contribution. Failed lookup is unknown.
- Stop denies subsequent protected operations and handles child processes; observer
  loss does not falsely terminate work. Local receipts are not trusted authorization.
- Final evidence includes repository, branch, commit SHA, check commands/results,
  PR number/URL, and an independently reconciled outcome. Model prose is insufficient.

The durable chat receipt is reusable dispatch infrastructure, but it cannot alone
prove that a remote push or PR write occurred exactly once. Remote contribution
reconciliation remains necessary after a crash between side effect and receipt.

## Verification performed

Ran the existing focused suites with Python 3.12:

```sh
.venv/bin/python -m pytest tests/api/test_github_webhook_security.py tests/web/test_chat_requests.py tests/web/test_link_execution_authority.py -q
```

Result: **38 passed, 8 deprecation warnings**. These tests establish their existing
webhook/receipt/authority contracts, not the proposed cloud contribution workflow.
No live App authentication test or PR-creation smoke was run. The historical Sprite
results above come from the supplied Link notes and were not rerun for this review.
