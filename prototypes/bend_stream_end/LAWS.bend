import Base
import ./stream_end.bend as S

# Safety contracts for how a provider stream ends (SM-12 in
# context/tasks/correct-all-implicit-state-machines.md).
# This model is not a proof of the Python code; the differential test in
# tests/integrations/test_bend_stream_end.py ties the two together.
#
# DRAFT: written by Claude at Maximus's request on 2026-11-13, pending his
# review. By Bend convention this file belongs to the human.
#
# Deliberately not a law: a clean end with no text and no tool call is Empty{}.
# Whether that is an error is each adapter's choice today.

# A cancelled request is cancelled, whatever else arrived.
law cancelled_wins:
  for e: Bool
  for t: Bool
  for x: S.Early
  for o: Bool
  for s: Bool
  {S.end(True{}, e, t, x, o, s) == S.Cancelled{} : S.End}

# A provider error is the outcome even when a tool call or text is waiting.
law provider_error_wins:
  for t: Bool
  for x: S.Early
  for o: Bool
  for s: Bool
  {S.end(False{}, True{}, t, x, o, s) == S.ProviderError{} : S.End}

# A stream that never reached the provider's end marker is incomplete.
law no_end_marker_is_incomplete:
  for x: S.Early
  for o: Bool
  for s: Bool
  {S.end(False{}, False{}, False{}, x, o, s) == S.Incomplete{} : S.End}

# Tool calls from a cancelled, failed or incomplete stream are never run.
law cancelled_drops_tool_calls:
  for e: Bool
  for t: Bool
  for x: S.Early
  for o: Bool
  for s: Bool
  {S.keeps(S.end(True{}, e, t, x, o, s)) == False{} : Bool}

law provider_error_drops_tool_calls:
  for c: Bool
  for t: Bool
  for x: S.Early
  for o: Bool
  for s: Bool
  {S.keeps(S.end(c, True{}, t, x, o, s)) == False{} : Bool}

law incomplete_drops_tool_calls:
  for c: Bool
  for e: Bool
  for x: S.Early
  for o: Bool
  for s: Bool
  {S.keeps(S.end(c, e, False{}, x, o, s)) == False{} : Bool}

# Tool calls from output the provider cut short are never run.
law length_cut_drops_tool_calls:
  for c: Bool
  for e: Bool
  for t: Bool
  for o: Bool
  for s: Bool
  {S.keeps(S.end(c, e, t, S.Length{}, o, s)) == False{} : Bool}

law filter_cut_drops_tool_calls:
  for c: Bool
  for e: Bool
  for t: Bool
  for o: Bool
  for s: Bool
  {S.keeps(S.end(c, e, t, S.Filter{}, o, s)) == False{} : Bool}

# A clean end with a waiting tool call runs it, with or without text.
law clean_tool_call_is_kept:
  for s: Bool
  {S.keeps(S.end(False{}, False{}, True{}, S.NoEarly{}, True{}, s)) == True{} : Bool}

# A clean end with text and no tool call is a plain answer.
law clean_text_is_text:
  {S.end(False{}, False{}, True{}, S.NoEarly{}, False{}, True{}) == S.Answer{} : S.End}
