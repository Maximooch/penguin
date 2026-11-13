# Log-informed Penguin runtime experiments

This is an optional assurance experiment, not a production Bend integration.
It extends the permission prototype to the provider retry boundary. Native
compilation and differential tests are opt-in (`PENGUIN_TEST_BEND=1`).

## Contracts and scope

`LAWS.bend` specifies that absent/nonretryable errors, emitted assistant text,
pending tools, and useful responses block replay. A clean retryable error permits
it. `PROOF.bend` checks all six contracts. Python still owns response/error
classification, retry limits, tool effects, provider I/O, and cancellation.

`retry.bend` evaluates all 32 Boolean combinations through independent parallel
branches. Tests compare the native result on one and four threads against the
actual `should_retry_provider_failure`, across eight error categories and eight
response forms: 2,048 comparisons. This is correctness evidence, not a performance
benchmark or proof of the Python implementation. A mutation that allows replay
after emitted text must fail the proof check. No runtime dependency is added.

```sh
~/.bend/bin/bend guide
~/.bend/bin/bend prototypes/bend_runtime/PROOF.bend
PENGUIN_TEST_BEND=1 python -m pytest -q tests/integrations/test_bend_runtime.py
```

## Real-world log triage

On October 14, 2026, the local scan of `penguin_workspace/server-logs` covered
332 files and about 945 MB. The later snapshot contained 244,537 WARNING/ERROR
records, including:

| Fixed category | Matching records |
| --- | ---: |
| Checkpoint worker failures | 148,803 |
| Stream scope misses | 33,139 |
| Session view fallbacks | 27,671 |
| Provider replay sanitation | 15,895 |
| Empty response guard | 7,648 |
| Session save failures | 476 |
| Session load failures | 408 |
| Index save failures | 272 |
| Storage full | 171 |
| Process capture failure | 3 |

These are diagnostic occurrences, **not unique incidents**, and not proof that
old failures still exist. Files include historical July checkpoint errors;
current clean cross-event-loop restart passes. Running logs keep growing, so
repeat scans differ. Only fixed categories/counts are retained, not raw prompts,
responses, credentials, file paths, or conversation IDs. Synthetic fixtures
reproduce failure shapes. Quoted complete log headers may still overcount.

```sh
python scripts/server_log_inventory.py /path/to/server-logs
PENGUIN_TEST_BEND=1 python -m pytest -q \
  tests/integrations/test_bend_runtime.py \
  tests/core_runtime/test_log_inspired_scope_isolation.py \
  tests/system/test_log_inspired_checkpoint_lifecycle.py \
  tests/system/test_log_inspired_session_recovery.py \
  tests/tools/test_log_inspired_process_faults.py \
  tests/test_server_log_inventory.py
```

The above focused run: **25 passed, 3 strict xfails**. It exercises missing stream
scope isolation, interleaved streams, duplicate finalization, reasoning-only
responses, clean checkpoint restart, and real local child process recovery after
open/write/flush faults and callback exceptions. All child processes and fixture
files are local and disposable. Session tests additionally cover truncated JSON,
backup recovery, source preservation, legacy categories, failed temporary writes,
and failed atomic replacements.

### Reproduced checkpoint defect

`test_failed_checkpoint_does_not_strand_queue_join` is strict xfail: the worker
calls `task_done()` only after successful work. An injected disk-full exception
leaves unfinished work outstanding and `queue.join()` cannot complete. The test
runs to completion with a bounded wait and always shuts workers down. It does
not claim the historical event-loop storm still reproduces. No production fix
is bundled with the experiment.

### Broader suite

Use `python -m pytest tests`, not bare repository-root pytest: root discovery
also collects scripts that can call `sys.exit()` and unrelated source files.
Existing pytest defaults exclude live/e2e/slow tests. The selected core-runtime,
LLM, tools and API sweep produced **1,437 passed, 3 failed, 1 skipped, 64
deselected**. Failures were the two existing process permission policy cases
and a pasted-goal API test with an undefined `routes_module` name.

The complete `PENGUIN_TEST_BEND=1 python -m pytest -q tests
--continue-on-collection-errors` sweep returned **2,932 passed, 12 failed,
6 skipped, 113 deselected, 1 xfailed** in 165.56 seconds. The eight new session
recovery cases landed after this sweep collected; the focused final run above
includes them. Counts are separate runs, not additive coverage figures.

All 12 failed node IDs were rerun together: **11 failed, 1 passed**. The
multi-agent credential failure did not reproduce in that smaller run, suggesting
suite-order/environment coupling; its root cause remains unverified. Remaining
failures group as follows:

- API pasted-goal fixture: undefined `routes_module` (1).
- CLI regression expectations: uncaught `typer.Exit` (2).
- Model runtime fixture: missing OpenAI credentials (1).
- Engine initialization: missing `finish_reason` metadata (1).
- Length continuation/stop/iteration contracts: returned implicit completion or
  the original partial answer instead of the expected continuation state (4).
- Process policy contract: returned a string where a completed result mapping
  was expected (2).

No production code changed; these are failures in existing test nodes. They are
not all diagnosed as production defects versus test defects.

Two additional strict session xfails reproduce with `--runxfail`:
`Message.from_dict` rejects a missing legacy category and returns a recovery
session rather than the original messages; index replacement failure is swallowed
and `save_session` reports success. Together with the checkpoint case, these are
three explicit failing contracts, not successful tests.

Both Bend prototype proof files return `ALL PROOFS CHECK`; independent Lean
`--verdict` verification was not performed. All seven new Python files pass Ruff
lint and formatting checks.

Passing bounded models does not cover every production execution:
browsers, live providers, external GitHub integration, GPU execution, and load
behavior need their own explicitly enabled environments. Full-suite failures
must remain visible rather than be normalized as success.
