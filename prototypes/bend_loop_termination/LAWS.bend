import Base
import ./recovery.bend as R

# Termination contracts for the turn loop's recovery turns (SM-15 in
# context/tasks/correct-all-implicit-state-machines.md). A run with no
# iteration cap must still end when the model keeps answering with output
# Penguin has to recover from.
# This model is not a proof of the Python code; the differential test in
# tests/integrations/test_bend_loop_termination.py ties the two together.
#
# DRAFT: written by Claude at Maximus's request on 2026-11-14, pending his
# review. By Bend convention this file belongs to the human.

# Any mix of output-limit and malformed-syntax turns ends the run within
# twelve turns: eight continuations, three repairs, and the turn that exceeds
# a cap.
law recovery_turns_end_within_twelve:
  {R.stops_within(12n, R.Going{0n, 0n}) == True{} : Bool}

# Twelve is the exact bound: some sequence of eleven recovery turns is still
# going, so the caps are not tighter than the constants say.
law eleven_recovery_turns_can_continue:
  {R.stops_within(11n, R.Going{0n, 0n}) == False{} : Bool}

# Only an ordinary turn restores the recovery budget.
law ordinary_turn_restores_budget:
  for oc: Nat
  for rc: Nat
  {R.step(R.Ordinary{}, oc, rc, 0) == R.Going{0n, 0n} : R.Run}

# A stopped run stays stopped.
law stopped_run_stays_stopped:
  for t: R.Turn
  {R.advance(R.Stopped{7}, t, 9) == R.Stopped{7} : R.Run}
