import Base
import ./LAWS.bend as Laws

def Laws.no_recovery_without_stall(attempted):
  {==}

def Laws.recovery_at_most_once(stalled):
  match stalled:
    case False{}:
      {==}
    case True{}:
      {==}

def Laws.first_stall_recovers():
  {==}

def Laws.no_implicit_wait_deadline(elapsed):
  {==}

def Laws.explicit_elapsed_deadline_stops():
  {==}

def Laws.explicit_unelapsed_deadline_waits():
  {==}
