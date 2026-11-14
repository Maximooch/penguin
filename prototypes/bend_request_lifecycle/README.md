# Provider request lifecycle model

Optional assurance experiment for SM-32 in
`context/tasks/correct-all-implicit-state-machines.md`. It adds no runtime
dependency. Tests are opt-in (`PENGUIN_TEST_BEND=1`).

## Scope

`lifecycle.bend` is a pure projection of `next_request_status` in
`penguin/llm/contracts.py`: the status a provider request moves to when a new
status is asked for. `LLMRequestLifecycle.advance` applies it; every adapter
and the Link provider record status only through `advance` and `finish`.

The harm it guards against: a late event reopens or relabels a request that
has already ended, so a failed request reads as completed or still running.

## Files

- `lifecycle.bend`: the model, and a `main` that prints all 64 transitions.
- `LAWS.bend`: the contracts. Drafted by Claude on 2026-11-14 and awaiting
  human review; by Bend convention this file belongs to the human.
- `PROOF.bend`: proofs of those contracts.

## Not covered

- Timestamps and metadata (`ended_at`, `finish_reason`, `error`) are Python's.
  `tests/llm/test_request_lifecycle_transitions.py` covers that a refused
  transition changes none of them.
- `bend PROOF.bend --verdict` was not run: it needs Lean, which is not
  installed here.

## Run

```sh
~/.bend/bin/bend prototypes/bend_request_lifecycle/PROOF.bend
PENGUIN_TEST_BEND=1 python -m pytest -q tests/integrations/test_bend_request_lifecycle.py
```

## Covered code and sync point

- `penguin/llm/contracts.py`: `next_request_status`,
  `LLMRequestLifecycle.advance`, `LLMRequestLifecycle.finish`.
- Last confirmed against the working tree on top of `907c483bd`, 2026-11-14.
  Move this forward only after re-checking the model against the code.
