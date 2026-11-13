# Ordered tool batch status model

Optional assurance experiment for SM-01 in
`context/tasks/correct-all-implicit-state-machines.md`. It adds no runtime
dependency. Tests are opt-in (`PENGUIN_TEST_BEND=1`).

## Scope

`status.bend` is a pure projection of two Python functions in
`penguin/tools/runtime.py`:

- `tool_status_from_output`: raw tool output to `ToolResultStatus`.
- `halts_ordered_execution`: whether a result stops the calls after it.

Python still owns JSON parsing, tool execution and permission checks. The model
starts from the extracted `error` flag and `status` word.

The harm it guards against: a child call that is waiting for approval is
recorded as completed, and later calls in the same batch run.

## Files

- `status.bend`: the model, and a `main` that prints all 12 input cases.
- `LAWS.bend`: the contracts. Drafted by Claude on 2026-11-13 and awaiting
  human review; by Bend convention this file belongs to the human.
- `PROOF.bend`: proofs of those contracts.

## Not covered

- An unrecognised status word (for example `running`) maps to completed. That
  is current behaviour and is deliberately not stated as a law.
- `bend PROOF.bend --verdict` was not run: it needs Lean v4.34.0, which is not
  installed here.

## Run

```sh
~/.bend/bin/bend prototypes/bend_tool_status/PROOF.bend
PENGUIN_TEST_BEND=1 python -m pytest -q tests/integrations/test_bend_tool_status.py
```

## Covered code and sync point

- `penguin/tools/runtime.py`: `tool_status_from_output`,
  `halts_ordered_execution`, and the three `stop_on_error` checks in
  `execute_tool_calls_ordered`.
- `penguin/tools/tool_manager.py`: `_tool_result_from_child_output`.
- Last confirmed against the working tree on top of `548ad4ec9`, 2026-11-13.
  Move this forward only after re-checking the model against the code.
