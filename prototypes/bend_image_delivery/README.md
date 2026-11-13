# PR 123: Bend image-delivery assurance

Tested PR head `02f1282160816cfe118b495de0547a70afab2022` against base
`36e32f62334111824c9bb083fe7f1d6836dcd48b` using disposable `git archive`
snapshots, with the same integration test copied into each. No branch switch,
production edits, stash application/drop, or commit was needed.

`LAWS.bend` specifies four small image-gate contracts: incomplete/error results
and absent paths block delivery; successful error-free results with a path survive.
The native model evaluates independent Boolean branches in parallel. Differential
tests compare Python extraction across statuses, path shapes, and both image tools
on one and four threads. This models eligibility only, not image bytes or ordering.
Two mutations (ignoring failure status, dropping success) must fail proof checking.

The PR's existing 32 end-to-end cases separately verify actual decoded pixels,
reply adjacency, direct/ordered calls, native/Codex OAuth request encoding, output
limits, and missing/corrupt/denied images. Thus the proof does not stand in for
integration evidence.

Results:

| Snapshot | Bend tests | PR image tests | Total |
| --- | --- | --- | --- |
| Base | 3 passed, 2 failed | 32 failed | 3 passed, 34 failed |
| PR head | 5 passed | 32 passed | 37 passed |

The base's differential failures expose image artifacts from unsuccessful statuses.
Proof and mutation checks pass on both because they check the independent model.
PR head agrees with that model and passes all 32 delivery regressions. This is a
focused check, not certification of the whole PR or proof of Python correctness.
No live provider calls, GPU tests, or Lean `--verdict` validation were performed.

Run on a checkout of the PR head (the model/tests must be present):

```sh
~/.bend/bin/bend guide
~/.bend/bin/bend prototypes/bend_image_delivery/PROOF.bend
PENGUIN_TEST_BEND=1 python -m pytest -q \
  tests/integrations/test_bend_image_delivery.py tests/test_read_image_delivery.py
```

For a separate snapshot, set `BEND_IMAGE_SOURCE` to this model directory's absolute
path and copy the integration test into that snapshot. Run pytest from the
snapshot using an absolute Python executable; do not accidentally import main.
Local run transcripts: `/tmp/penguin-pr123-base-tests.txt` and
`/tmp/penguin-pr123-head-tests.txt` (ephemeral).

## Prior Bend work

Permission/runtime experiments and log-informed tests remained in the working tree.
The four loop-recovery Bend/test files were verified byte-for-byte against the
newest stash and are now present/tracked in main. No stash was popped or dropped.
