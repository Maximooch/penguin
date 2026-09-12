# Penguin GitHub contributions follow-up

This Penguin-only change stacks on PR #99, `codex/hosted-tool-environment`, at `3e9a887d2559e076d71b14c5161e12fb087fc616`.
The follow-up branch is `codex/github-contributions`.

## Delivered

- Repository tools receive the execution checkout and validate both origin URLs.
- Local commits support staged changes, deletions, and explicit literal file paths.
- Publication uses stable contribution identities and atomic local receipts.
- Retries reconcile commits, remote branches, and PRs before further writes.
- Hosted operations require a trusted execution binding and an external adapter.
- Hosted calls cannot use the local App/PAT adapter or direct push tool.
- Draft PR results contain remote identity and commit evidence.
- The old smoke that accepted PR wording now checks GitHub state directly.
- Live GitHub tests require explicit activation.
- CI runs the offline contracts on its Python 3.10/Pydantic v1 and Python 3.12/Pydantic v2 matrix.

The [usage guide](../../docs/docs/usage/github-contributions.md) defines the contract and recovery limits.

## Verification

Local Python 3.12:

- 116 focused repository, environment, webhook, receipt, authority, and dispatch tests passed.
- Two migrated project workflow tests passed with the fake broker.
- Changed contribution modules and focused tests passed Ruff checks and formatting checks.
- The live publication and App tests skip without explicit activation.

Fly Sprite Python 3.12:

- Organization: `maximus-putnam`.
- Existing Sprite: `link-penguin-pr99-20260911`.
- Test checkout: `/home/sprite/penguin-github-contributions-test-20260912`.
- The same 116 focused tests passed in 7.01 seconds.
- The import check resolved Penguin from the named test checkout.
- Tests reused the dependency environment at `/home/sprite/penguin-source/.venv`.
- The checkout started from PR #99 and received only the changed source, tests, and documentation.

The Sprite CLI returned EOF for native exec.
Its authenticated API helper worked with HTTP/1.1 after intermittent TLS connection failures.
No Sprite-management credential was extracted or delivered to a workload.
The tests used synthetic authority and local bare Git remotes.
No new Sprite, persistent service, or keep-alive task was created.
The named test checkout remains available for inspection.

## Boundaries

No Link code changed.
No real GitHub publication or hosted credential activation was attempted.
`Maximooch/penguin-test-repo` remains the designated live test repository.

Link must supply the external adapter, execution authorization, Git transport, revocation, and authoritative records.
Python cancellation cannot terminate an already-running worker operation by itself.
Local receipts are recovery evidence, not trusted authority inside an agent-controlled Sprite.
Unknown remote outcomes without matching evidence stop for operator reconciliation.

Fork contributions, PR edits, reviews, merge, webhook modernization, and a production broker remain follow-ups.

## Final review and CI

Final review added terminal-PR recovery after source-branch deletion and rejection of a fork head in the local adapter.
The final focused suite passed 116 tests locally and in the Sprite.
Ruff 0.16.7 in CI found three unused test variables that the older local Ruff did not flag.
Those variables were corrected.

PR #99 already fails the Engine continuation and TUI typecheck jobs.
The four Engine continuation failures also reproduced directly on the base worktree.
The failing Engine and TUI source files are unchanged by this PR.
These baseline failures remain separate work.
