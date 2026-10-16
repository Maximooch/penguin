# Loop recovery assurance

Optional development checks; no production Bend dependency. Proposed invariants
live in `LAWS.bend`: a stall gets one recovery, ordinary completion gets none,
quiet waits have no implicit deadline, and explicit deadlines remain effective.
`PROOF.bend` proves these six laws for the pure policy projection.

```sh
bend guide
bend prototypes/bend_loop_recovery/PROOF.bend
PENGUIN_TEST_BEND=1 python -m pytest -q tests/integrations/test_bend_loop_recovery.py
```

The native runner enumerates all 16 Boolean combinations using independent,
balanced parallel branches. Differential tests on one and four threads compare
these with the actual Engine recovery method and ProcessWaitGuard, including
all recognized stall statuses, four process actions, both live lifecycle states,
exact timeout boundaries, cursor progress, and second-attempt rejection. Two
mutations (unlimited recovery and an implicit deadline) must fail the laws.
Existing deterministic engine tests additionally exercise complete task/response
traces, continued stale results, explicit iteration limits, and placeholders.

These are bounded model/implementation comparisons, not a proof of Python,
provider behavior, process I/O, permissions, or Windows compatibility. Normal
Bend proofs pass locally. Independent `--verdict` verification was attempted but
could not run because Lean v4.34.0 is not installed. GPU execution is untested.
Bend is optional and is not required for the Windows Skyrim smoke test.
