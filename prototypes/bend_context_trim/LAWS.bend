import Base
import ./trim.bend as R

# Trimming contracts for the context window (SM-55 in
# context/tasks/correct-all-implicit-state-machines.md). Penguin trims message
# categories by priority and recency; it never summarises or compacts.
# This model is not a proof of the Python code; the differential test in
# tests/integrations/test_bend_context_trim.py runs the real trim_session on
# every enumerated session and compares what each kept.
#
# DRAFT: written by Claude at Maximus's request on 2026-11-15, pending his
# review. By Bend convention this file belongs to the human.
#
# The four "for every session" laws are checked over all 338 sessions of the
# model's space: SYSTEM 0 or 2 tokens, and SYSTEM_OUTPUT and DIALOG each empty
# or holding one or two messages of 1 to 3 tokens, in a 6-token window.

# After trimming, the session fits the window, or SYSTEM_OUTPUT and DIALOG are
# both at or below their minimums: only SYSTEM and the minimums may keep a
# session over the window.
law trimmed_session_fits_unless_at_minimums:
  {R.all(R.Fits{}) == True{} : Bool}

# A session within the window, with every category within its budget, keeps
# every message.
law session_in_budget_is_untouched:
  {R.all(R.Untouched{}) == True{} : Bool}

# DIALOG loses a message only when it is over its own budget, or when
# SYSTEM_OUTPUT (lower priority) has already been trimmed to its minimum.
law lower_priority_is_trimmed_first:
  {R.all(R.OutputFirst{}) == True{} : Bool}

# A category at or below its minimum and within its budget loses nothing.
law category_at_its_minimum_is_kept:
  {R.all(R.Floor{}) == True{} : Bool}

# Every category is within its budget here, but the session is three tokens
# over the window, so trimming happens (before SM-55 nothing was trimmed).
# Whole messages are removed, so SYSTEM_OUTPUT ends below its 1-token minimum:
# the minimum is where trimming aims to stop, not a guaranteed floor.
law minimum_is_a_target_not_a_floor:
  {R.trim(2n, R.One{3n}, R.Two{2n, 2n}) == R.Trim{R.Empty{}, R.Two{2n, 2n}} : R.Trim}
