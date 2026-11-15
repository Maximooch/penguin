# Context-window trimming model

Optional assurance experiment for SM-55 in
`context/tasks/correct-all-implicit-state-machines.md`. It adds no runtime
dependency. Tests are opt-in (`PENGUIN_TEST_BEND=1`).

## Scope

`trim.bend` is a pure projection of `ContextWindowManager.trim_session`
(`penguin/system/context_window.py`). Penguin trims message categories by
priority and recency. It does not summarise or compact anything.

- Categories are trimmed lowest priority first. SYSTEM is never trimmed.
- Inside a category, whole messages are removed, oldest first.
- A category over its own budget is trimmed back to that budget.
- While the session is over the window, a category is also trimmed by what is
  still over, down to its minimum, even when it is within its own budget.

The model has SYSTEM and two trimmable categories, DIALOG and SYSTEM_OUTPUT
(trimmed first). The window is 6 tokens; SYSTEM_OUTPUT's budget is 1 to 3
and DIALOG's is 2 to 4. The budgets add up to more than the window, as
Penguin's defaults do. That case is the one SM-55 fixed: before, a session
over the window with every category within its budget was not trimmed.

## Files

- `trim.bend`: the model, the four checked properties, and a `main` that
  prints how many messages each trimmable category keeps, for all 338
  sessions of the model's space.
- `LAWS.bend`: the contracts. Drafted by Claude on 2026-11-15 and awaiting
  human review; by Bend convention this file belongs to the human.
- `PROOF.bend`: proofs of those contracts, by evaluation over the whole space.

The differential test runs the real `trim_session` on the same 338 sessions
and compares its table with the model's. It fails on the code from before
SM-55. A model with the pre-SM-55 rule fails
`trimmed_session_fits_unless_at_minimums`.

## Not covered

- Token counting, image trimming, and categories other than the three
  modelled. CONTEXT, ERROR, INTERNAL and UNKNOWN follow the same per-category
  rule; the Python tests cover them.
- A category's minimum is where trimming aims to stop, not a floor: because
  whole messages are removed, a category can end below its minimum by part
  of one message (`minimum_is_a_target_not_a_floor`).
- `bend PROOF.bend --verdict` was not run: it needs Lean, which is not
  installed here.

## Run

```sh
~/.bend/bin/bend prototypes/bend_context_trim/PROOF.bend
PENGUIN_TEST_BEND=1 python -m pytest -q tests/integrations/test_bend_context_trim.py
```
