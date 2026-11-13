# Bend experiments in Penguin

Local evaluation, October 14, 2026. Bend 2.0.37; no production runtime changes.

## Outcome

Bend is promising as an optional executable-specification/proof lane for small
pure functions, and for sufficiently large CPU-bound batches. These experiments
do **not** justify rewriting Penguin orchestration or launching a native process
for each permission check.

## Reproduce

```sh
export PATH="$HOME/.bend/bin:$PATH"
bend guide
# Repository root:
PENGUIN_TEST_BEND=1 pytest -q tests/integrations/test_bend_permissions.py tests/test_permission_engine.py
python prototypes/bend_permissions/benchmark.py
python prototypes/bend_permissions/benchmark.py --work 0
# Required manual proof gate before committing changes to this experiment:
(cd prototypes/bend_permissions && bend PROOF.bend)
```

Set `BEND_BIN` for the Python harnesses if a different compiler is desired.
Without `PENGUIN_TEST_BEND=1`, the new test module skips (no Bend installation
required). An explicitly enabled run fails if its compiler is missing. Native
builds and mutation copies use temporary directories. No hook, CI requirement,
dependency, shell configuration, or commit was installed/created.

## Files and scope

- `permissions.bend`: the existing pure ALLOW/ASK/DENY algebra and parallel tree
  reduction. It combines already-computed decisions, not live Python policies.
- `LAWS.bend`, `PROOF.bend`: fixed proposed contracts and their proofs. The new
  leaf-preservation law strengthens the specification; none were weakened.
- `runner.bend`: experimental text boundary (`a`/`q`/`d`), balanced tree building,
  and native result output. Empty chain returns ALLOW; invalid input exits 2.
  This is a bounded test harness, not a hardened public service or runtime adapter.
- `scoring.bend`: deterministic synthetic CPU work with a checksum. Independent
  subtrees fork in parallel; leaf work is sequential. The fork depth is tunable
  to compare coarse tasks with one task per leaf. No production scoring algorithm
  is implied; no GPU kernel is used.
- `benchmark.py`: dependency-free temporary builds, validated results, warmups,
  seeded randomized measurement order, and raw JSON output.
- `results.json`: retained raw measurements from both local benchmark runs.
- `../../tests/integrations/test_bend_permissions.py`: opt-in executable contracts,
  fault injection, and mutation tests.

## Correctness evidence

The focused command above passed **74 tests**: 35 new experimental cases and
39 existing permission-engine tests (13 existing deprecation warnings).

The new cases cover:

- All **364 decision chains of lengths 0 through 5**, compared with the real
  `PermissionEnforcer.check`, on both 1 and 4 CPU threads.
- **24 longer cases** per thread count: seeded 129-element chains and 257-element
  ALLOW-only, ASK-at-end, DENY-at-end, and DENY-at-start cases. Together these are
  **776 chain/result comparisons**. The exhaustive cases also check Python's
  short-circuit call sequence. External audit storage is mocked, not validated.
- Invalid input rejection without a success result.
- Separate Python characterization of disabled policies, explicit bypasses,
  priority ordering, and exceptions. These are **outside** the pure Bend model.
- Synthetic checksums against an independent Python loop for zero work, serial
  execution, coarse/full parallel execution, and 1/4-thread consistency.
- Six mutations rejected by the proof checker: broken left/right DENY handling,
  dropped ASK, broken ALLOW identity, dropped branch, and dropped leaf decision.

### A real specification gap found

With the original laws, changing every leaf into ALLOW still produced
`ALL PROOFS CHECK`. The branch equation was definitional and did not specify what
leaves meant. Reproducing this in a temporary copy confirmed the gap. The added
`leaf_identity` law now rejects that mutation. This is evidence for mutation
checks of specifications, not only confidence in a green proof output.

`bend PROOF.bend` passes. `bend PROOF.bend --verdict` remains blocked by the
missing Lean v4.34.0/prebuilt BendTT kernel. Ordinary checker success is not
independent kernel validation. The text parser/tree builder and scoring kernel
are type/termination checked and tested, but lack dedicated semantic laws.
These tests and finite comparisons do not prove all-input equivalence of Python
and Bend, audit correctness, or production permission safety.

### Existing Python boundaries matter

`PermissionEnforcer.check` skips policy exceptions. The injected exception-only
case returned ALLOW; exception followed by ASK or DENY returned the surviving
policy's result. That warrants a separate fail-open security review. It was not
changed here. YOLO/allowlist bypasses, policy evaluation side effects, first-DENY
short circuit, and audit ordering must not be replaced by parallel evaluation
just because the outcome algebra is commutative.

## Performance evidence

Local machine: macOS 15.7.3, arm64, 8 logical CPUs, 16 GiB RAM; Python 3.12.8.
Five measured samples/configuration after one warmup; shuffled order. CPU only.
All samples verified the same expected checksum. Times include process startup,
argument parsing, computation, and stdout; compile time is measured separately.

Synthetic workload: 4,096 leaves, 10,000 fixed-width recurrence steps per leaf
(40,960,000 steps). Median wall times:

| CPU threads | No forks | Fork top 4 levels | Fork all 12 levels |
| --- | ---: | ---: | ---: |
| 1 | 44.28 ms | 44.22 ms | 45.28 ms |
| 4 | 45.71 ms | 18.73 ms | 16.64 ms |
| 8 | 45.09 ms | 16.40 ms | 13.59 ms |

Best measured configuration was about **3.26x faster** than one-thread/no-fork.
Adding threads without independent forks did not help. Full-depth forking won
this particular workload; optimal granularity is workload-dependent.

The same 4,096-leaf tree with **zero work per leaf** took roughly **4.9–5.8 ms**
across configurations; differences are small relative to sample variation and
startup cost. A single three-decision permission chain took **5.39 ms** in the
compute run and **5.00 ms** in the overhead run. That is no case for per-check
subprocess integration.

Native builds took approximately 1 second each. An illustrative smaller workload
(1,024 leaves × 1,000 steps) took 64.49 ms in a single in-process Python sample
versus 7.42 ms in a single-thread Bend child in the compute run. The overhead run
measured 80.45/6.35 ms, underscoring noise. These are **not** comparisons against
optimized Python/native array libraries or an actual Penguin hotspot. No FFI,
long-lived worker, serialization-heavy workload, or GPU benchmark was tested.

## Broader regression run

Running the new suite plus permission-engine, process-permission-contract, and
permission-resume suites returned **118 passed, 2 failed**. Both failures are in
existing `test_new_policy_applies_to_each_operation` cases (`process_start`,
`process_write_stdin`): a string result is indexed as a dictionary at line 72.
Running only that existing parametrized test without Bend also returned
**1 passed, 2 failed**. No production files or those tests were modified. This
records the regression boundary rather than claiming the broader suite is green.

Ruff lint/format checks passed for the new Python files. Default opt-out behavior
was verified: 35 skipped. The complete repository suite was not run.

## Recommended next step

Keep Bend optional and use this specification-plus-differential/mutation pattern
for a small pure contract. Review/approve laws separately from implementation.
Before runtime integration, profile a real Penguin CPU hotspot and measure
end-to-end cost with realistic data transfer. Keep effectful orchestration,
approvals, process lifecycle, and auditing in their existing runtime. A proved
model is useful; it is not a proof of code that never executes that model.
