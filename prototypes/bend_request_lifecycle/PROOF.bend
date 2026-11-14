import Base
import ./LAWS.bend as Laws

def Laws.completed_is_final(r):
  {==}

def Laws.cancelled_is_final(r):
  {==}

def Laws.failed_is_not_reopened():
  {==}

def Laws.failed_is_not_completed():
  {==}

def Laws.disconnected_is_not_completed():
  {==}

def Laws.failed_can_be_retried():
  {==}

def Laws.disconnected_can_be_retried():
  {==}

def Laws.streaming_is_not_retried():
  {==}

def Laws.completed_is_not_retried():
  {==}

def Laws.retry_does_not_complete():
  {==}

def Laws.retry_can_be_cancelled():
  {==}

def Laws.cancelled_outcome_wins(e):
  {==}

def Laws.failed_request_is_not_done():
  {==}

def Laws.disconnected_request_is_not_done():
  {==}

def Laws.completed_with_retryable_error_is_retryable():
  {==}

def Laws.completed_with_fatal_error_is_fatal():
  {==}

def Laws.clean_completion_is_done():
  {==}
