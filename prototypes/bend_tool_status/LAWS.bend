import Base
import ./status.bend as S

# Safety contracts for ordered tool batches (SM-01 in
# context/tasks/correct-all-implicit-state-machines.md).
# This model is not a proof of the Python code; the differential test in
# tests/integrations/test_bend_tool_status.py ties the two together.
#
# DRAFT: written by Claude at Maximus's request on 2026-11-13, pending his
# review. By Bend convention this file belongs to the human.
#
# Deliberately not a law: an unrecognised status word maps to Completed{}.
# That is how the code behaves today, not a promise.

# A reported error is an error whatever the status word says.
law error_flag_wins:
  for r: S.Raw
  {S.status(True{}, r) == S.Error{} : S.Status}

# A call waiting for approval is never recorded as completed.
law pending_approval_requires_approval:
  {S.status(False{}, S.RawPendingApproval{}) == S.RequiresApproval{} : S.Status}

law requires_approval_requires_approval:
  {S.status(False{}, S.RawRequiresApproval{}) == S.RequiresApproval{} : S.Status}

# The calls after one that is waiting for approval do not run.
law pending_approval_halts:
  for e: Bool
  {S.halts(S.status(e, S.RawPendingApproval{})) == True{} : Bool}

law requires_approval_halts:
  for e: Bool
  {S.halts(S.status(e, S.RawRequiresApproval{})) == True{} : Bool}

# The calls after a failed or cancelled one do not run.
law error_halts:
  for e: Bool
  {S.halts(S.status(e, S.RawError{})) == True{} : Bool}

law cancelled_halts:
  for e: Bool
  {S.halts(S.status(e, S.RawCancelled{})) == True{} : Bool}

law reported_error_halts:
  for r: S.Raw
  {S.halts(S.status(True{}, r)) == True{} : Bool}

# A clean success lets the batch continue.
law clean_completion_continues:
  {S.halts(S.status(False{}, S.RawCompleted{})) == False{} : Bool}
