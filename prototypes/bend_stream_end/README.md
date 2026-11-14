# Stream-end outcome model

Optional assurance experiment for SM-12 in
`context/tasks/correct-all-implicit-state-machines.md`. It adds no runtime
dependency. Tests are opt-in (`PENGUIN_TEST_BEND=1`).

## Scope

`stream_end.bend` is a pure projection of two Python functions in
`penguin/llm/stream_end.py`:

- `classify_stream_end`: the facts an adapter holds when its stream ends, to
  one `StreamEnd` outcome.
- `keeps_tool_calls`: whether tool calls gathered during the stream may run.

Python still owns the provider request, event parsing and tool-call
accumulation. The model starts from six extracted facts: cancelled, provider
error, end marker seen, output cut short (and why), tool call waiting, text
received.

The harm it guards against: a tool call whose arguments were cut off by a
provider error, a dropped connection or an output limit is executed.

## Files

- `stream_end.bend`: the model, and a `main` that prints all 96 input cases.
- `LAWS.bend`: the contracts. Drafted by Claude on 2026-11-13 and awaiting
  human review; by Bend convention this file belongs to the human.
- `PROOF.bend`: proofs of those contracts.

## Not covered

- A clean end with no text and no tool call is `Empty{}`. Whether that is an
  error is each adapter's own choice today and is deliberately not a law.
- Whether each adapter extracts the six facts correctly from its provider's
  events. The deterministic tests in
  `tests/llm/test_stream_end_classification.py` cover that for the paths they
  exercise.
- `bend PROOF.bend --verdict` was not run: it needs Lean, which is not
  installed here.

## Run

```sh
~/.bend/bin/bend prototypes/bend_stream_end/PROOF.bend
PENGUIN_TEST_BEND=1 python -m pytest -q tests/integrations/test_bend_stream_end.py
```

## Covered code and sync point

- `penguin/llm/stream_end.py`: `classify_stream_end`, `keeps_tool_calls`.
- Callers: `penguin/llm/adapters/openai.py` (`_settle_responses_stream_end` and
  the Codex stream end), `penguin/llm/adapters/openrouter.py`
  (`_settle_stream_end`), `penguin/llm/adapters/anthropic.py`
  (`_handle_streaming`).
- Last confirmed against the working tree on top of `6e8539496`, 2026-11-13.
  Move this forward only after re-checking the model against the code.
