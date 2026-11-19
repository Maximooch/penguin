# Turn-loop termination model

Optional assurance experiment for SM-15 in
`context/tasks/correct-all-implicit-state-machines.md`. It adds no runtime
dependency. Tests are opt-in (`PENGUIN_TEST_BEND=1`).

## Scope

`recovery.bend` is a pure projection of the recovery-turn caps in
`Engine._iteration_loop` (`penguin/engine.py`), which both `run_response` and
`run_task` run. Two kinds of turn make the loop continue without progress:

- an output-limit turn (`finish_reason == LENGTH`), which queues a
  continuation note, capped by `MAX_CONSECUTIVE_OUTPUT_CONTINUATIONS` (8);
- a malformed-syntax turn, which queues a repair note, capped by
  `MAX_MALFORMED_ACTION_REPAIRS` (3).

Both counters reset only after an ordinary turn, so alternating between the two
kinds cannot keep a run alive.

The harm it guards against: a run with no iteration cap that never ends because
the model keeps producing output Penguin has to recover from. Before SM-15 the
repair turn had no counter at all, and a repair turn reset the output-limit
counter.

## Files

- `recovery.bend`: the model, and a `main` that prints the stop turn of all
  4096 twelve-turn recovery sequences and all 729 six-turn sequences that also
  contain ordinary turns.
- `LAWS.bend`: the contracts. Drafted by Claude on 2026-11-14 and awaiting
  human review; by Bend convention this file belongs to the human.
- `PROOF.bend`: proofs of those contracts.

## Not covered

- The other ways the loop ends (finish tool, completion phrase, stall guard,
  budget, stop request, errors) are Python's, covered by
  `tests/test_engine_loop_termination.py` and
  `tests/test_engine_task_finish_contract.py`.
- Ordinary turns are unbounded by design: a model doing real work runs until
  it finishes, a guard fires, or a configured limit is reached.
- `bend PROOF.bend --verdict` was not run: it needs Lean, which is not
  installed here.

## Run

```sh
~/.bend/bin/bend prototypes/bend_loop_termination/PROOF.bend
PENGUIN_TEST_BEND=1 python -m pytest -q tests/integrations/test_bend_loop_termination.py
```

## Covered code and sync point

- `penguin/engine.py`: the output-limit and malformed-syntax branches of
  `Engine._iteration_loop`, `LoopState.output_continuation_count`,
  `LoopState.malformed_repair_count`.
- Last confirmed against the working tree on top of `0207e1f63`, 2026-11-14.
  Move this forward only after re-checking the model against the code.
