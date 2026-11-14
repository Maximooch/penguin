import Base
import ./lifecycle.bend as L

# Safety contracts for a provider request's lifecycle status (SM-32 in
# context/tasks/correct-all-implicit-state-machines.md).
# This model is not a proof of the Python code; the differential test in
# tests/integrations/test_bend_request_lifecycle.py ties the two together.
#
# DRAFT: written by Claude at Maximus's request on 2026-11-14, pending his
# review. By Bend convention this file belongs to the human.

# A completed or cancelled request is never changed.
law completed_is_final:
  for r: L.St
  {L.next(L.Completed{}, r) == L.Completed{} : L.St}

law cancelled_is_final:
  for r: L.St
  {L.next(L.Cancelled{}, r) == L.Cancelled{} : L.St}

# A failed attempt is never reopened: it stays failed unless it is retried.
law failed_is_not_reopened:
  {L.next(L.Failed{}, L.Streaming{}) == L.Failed{} : L.St}

law failed_is_not_completed:
  {L.next(L.Failed{}, L.Completed{}) == L.Failed{} : L.St}

law disconnected_is_not_completed:
  {L.next(L.Disconnected{}, L.Completed{}) == L.Disconnected{} : L.St}

law failed_can_be_retried:
  {L.next(L.Failed{}, L.Retrying{}) == L.Retrying{} : L.St}

law disconnected_can_be_retried:
  {L.next(L.Disconnected{}, L.Retrying{}) == L.Retrying{} : L.St}

# Only a failed attempt is retried.
law streaming_is_not_retried:
  {L.next(L.Streaming{}, L.Retrying{}) == L.Streaming{} : L.St}

law completed_is_not_retried:
  {L.next(L.Completed{}, L.Retrying{}) == L.Completed{} : L.St}

# A retry is cancelled or gives up; it never reports a completion itself.
law retry_does_not_complete:
  {L.next(L.Retrying{}, L.Completed{}) == L.Retrying{} : L.St}

law retry_can_be_cancelled:
  {L.next(L.Retrying{}, L.Cancelled{}) == L.Cancelled{} : L.St}
