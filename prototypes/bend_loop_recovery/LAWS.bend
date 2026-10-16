import Base
import ./policy.bend as P

# Proposed contracts for this PR, not a proof of Python or provider I/O.
law no_recovery_without_stall:
  for attempted: Bool
  {P.recover(False{}, attempted) == False{} : Bool}

law recovery_at_most_once:
  for stalled: Bool
  {P.recover(stalled, True{}) == False{} : Bool}

law first_stall_recovers:
  {P.recover(True{}, False{}) == True{} : Bool}

law no_implicit_wait_deadline:
  for elapsed: Bool
  {P.wait_timeout(False{}, elapsed) == False{} : Bool}

law explicit_elapsed_deadline_stops:
  {P.wait_timeout(True{}, True{}) == True{} : Bool}

law explicit_unelapsed_deadline_waits:
  {P.wait_timeout(True{}, False{}) == False{} : Bool}
