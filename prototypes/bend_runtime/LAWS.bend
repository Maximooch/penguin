import Base
import ./retry.bend as R

# Proposed safety contracts: this model is not a proof of Python or provider I/O.
law missing_error:
  for r: Bool
  for s: Bool
  for t: Bool
  for b: Bool
  {R.retry(False{}, r, s, t, b) == False{} : Bool}

law emitted_text_blocks:
  for e: Bool
  for r: Bool
  for t: Bool
  for b: Bool
  {R.retry(e, r, True{}, t, b) == False{} : Bool}

law pending_tool_blocks:
  for e: Bool
  for r: Bool
  for s: Bool
  for b: Bool
  {R.retry(e, r, s, True{}, b) == False{} : Bool}

law clean_retryable_failure:
  {R.retry(True{}, True{}, False{}, False{}, False{}) == True{} : Bool}


law non_retryable_blocks:
  for e: Bool
  for s: Bool
  for t: Bool
  for b: Bool
  {R.retry(e, False{}, s, t, b) == False{} : Bool}

law useful_response_blocks:
  for e: Bool
  for r: Bool
  for s: Bool
  for t: Bool
  {R.retry(e, r, s, t, True{}) == False{} : Bool}
