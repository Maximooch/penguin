# GitHub contributions

Penguin can prepare a commit, push it, and open a draft PR through one recoverable workflow.
Repository tools use the execution checkout instead of the server working directory.

This implementation supports one GitHub repository per contribution.
Forks, PR edits, merge, reviews, and webhook admission remain separate work.

## Local use

1. Clone the target repository.
2. Set its credential-free `origin` URL.
3. Configure Git authentication and commit identity.
4. Fetch the repository's base branch.
5. Select the checkout root as Penguin's execution directory.
6. Use `create_improvement_pr`, `create_feature_pr`, or `create_bugfix_pr`.

The existing tools now return JSON with repository, branch, commit SHA, PR number, URL, and state.
A successful PR response includes an independent remote lookup.
The workflow uses the repository's default branch unless a caller supplies a base branch.
Local Git transport authentication remains separate from the GitHub API client.

Local API authentication accepts an App configuration or `GITHUB_TOKEN`.
An incomplete or failed App configuration does not fall back to a personal token.
Status and local branch operations do not load credentials.

The optional `contribution_id` identifies one change.
On retries, reuse the ID, title, description, file selection, and base commit.
Without an ID, local repository tools derive one from the title and description.
For another change with the same text, supply a new ID.
Hosted execution uses the trusted binding's ID instead of the model's ID.

The workflow does not report invented test results.
Repository tools state that validation was not supplied.
The project task facade preserves validation supplied by its task runner.

## File selection

An omitted file list stages all changes, including deletions.
An explicit list stages only those literal paths.
Directories and paths outside the checkout are invalid.
If unrelated changes are already staged, the tool refuses the commit and preserves the index.

The workflow can publish an existing commit from a clean checkout.
File selection controls the new commit, not earlier commits already ahead of the base.
The caller must select a suitable starting branch.

## Recovery

Penguin stores local receipts under the checkout's Git directory in `penguin-contributions/`.
Receipts contain stable references and publication progress.
They do not contain credentials or grant authority.

| Observed state | Behavior |
| --- | --- |
| Commit succeeded before receipt write | Recover the commit through its marker and parent SHA. |
| Push succeeded before acknowledgement | Read the remote branch and compare its SHA. |
| PR creation succeeded before acknowledgement | Find the PR by its head and base branches. |
| Remote lookup failed | Stop without treating the failure as absence. |
| An uncertain write has no remote evidence | Return `CONTRIBUTION_UNKNOWN` and require reconciliation. |
| A matching PR is closed or merged | Return its state without opening another PR. |
| Inputs changed under the same identity | Return `CONTRIBUTION_CONFLICT`. |

Retries do not repeat uncertain writes without evidence.
Some cases therefore require operator reconciliation.
Deleting a receipt removes duplicate-prevention evidence and is not a safe retry procedure.
Receipt repair and remote reconciliation tooling remain future work.

A checkout lock serializes calls through this workflow on Linux and macOS.
The lock does not stop an arbitrary shell process from changing the checkout.
Use one isolated execution scope per writable checkout.

## Hosted integration contract

Set `PENGUIN_TOOL_ENVIRONMENT=hosted` through trusted launch configuration.
The environment controls from PR #99 remain required.
Hosted publication fails before commit creation when no execution binding exists.
The direct `commit_and_push_changes` tool refuses hosted calls.
Hosted pushes use the bound PR workflow.

Trusted launch code installs a `ContributionBinding` through `contribution_scope()`.
The binding contains execution ID, contribution ID, repository, checkout, base branch, base SHA, and an operation adapter.
The scope uses a ContextVar and propagates through `asyncio.to_thread()`.
It is not a request field or model tool argument.

The adapter implements `ContributionOperations`:

| Operation | Required behavior |
| --- | --- |
| `branch_sha(binding, branch)` | Recheck authority and return the exact remote SHA or authoritative absence. |
| `push(binding, branch, sha)` | Publish that immutable commit through the authorized transport. |
| `find_pr(binding, branch)` | Find the exact head/base pair, including closed and merged PRs. |
| `create_pr(binding, branch, title, body)` | Create one draft PR without hidden write retries. |

Each operation must enforce current execution and repository authority outside the Sprite.
A broker lookup failure must raise `RepositoryError`, not return `None`.
An adapter must not put credentials in errors or results.
The fake adapter in `tests/project/fake_broker.py` demonstrates the interface with a local bare repository.
It is not a production adapter.

Link still owns the following integration work:

- Authenticate and admit each execution.
- Connect the GitHub installation and restrict repository access.
- Supply an adapter with an authorized Git transport.
- Configure bot commit identity through `tool_environment_scope()`.
- Keep master keys and authoritative records outside the Sprite.
- Recheck authority on operations and credential renewal.
- Revoke authority on Stop and control background processes.
- Record authoritative publication results outside the Sprite.

Python cancellation cannot stop a Git process or broker call already running in a worker thread.
The adapter and external controller must enforce cancellation and revocation.
Local receipts do not prove that a remote operation stopped.
No Link endpoint, token-delivery mechanism, or production hosted adapter ships in this change.

The entire Sprite remains agent-controlled.
Python objects, local files, and the ContextVar are not security boundaries against agent code.
Master credentials must remain outside that boundary.
See [hosted tool environments](../security/hosted-tool-environment.md) for the other activation requirements.

## Verification

Run the deterministic suite first:

```sh
uv run pytest tests/project tests/system/test_tool_environment.py tests/api/test_github_webhook_security.py tests/web/test_chat_requests.py tests/web/test_link_execution_authority.py tests/tools/test_async_tool_dispatch.py -q
```

The suite uses synthetic authority and a local bare Git remote.
It covers checkout selection, commit recovery, lost acknowledgements, changed inputs, remote evidence, scope isolation, and revocation.
The tests do not create GitHub resources.

The designated live repository is `Maximooch/penguin-test-repo`.
The optional API smoke in `tests/api/test_github_pr_creation.py` requires explicit activation and a prepared disposable checkout.
That smoke performs real writes and checks GitHub state directly.
It is separate from hosted activation and does not replace the deterministic suite.
