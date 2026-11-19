import Base
import ./lifecycle.bend as L

# A pure projection of penguin.llm.contracts.classify_call_outcome: one
# provider attempt's outcome from its lifecycle status and recorded error.

# The recorded error, if any.
type Err is Data:
  NoErr{}
  Retryable{}
  Fatal{}

# LLMCallStatus in penguin/llm/contracts.py.
type Out is Data:
  Succeeded{}
  RetryableError{}
  FatalError{}
  CancelledOut{}

def failed_status(s: L.St) -> Bool:
  match s:
    case L.Disconnected{}:
      True{}
    case L.Failed{}:
      True{}
    case L.Retrying{}:
      True{}
    case L.Pending{}:
      False{}
    case L.Running{}:
      False{}
    case L.Streaming{}:
      False{}
    case L.Completed{}:
      False{}
    case L.Cancelled{}:
      False{}

def without_error(b: Bool) -> Out:
  match b:
    case True{}:
      FatalError{}
    case False{}:
      Succeeded{}

def by_error(+s: L.St, e: Err) -> Out:
  match e:
    case Retryable{}:
      RetryableError{}
    case Fatal{}:
      FatalError{}
    case NoErr{}:
      without_error(failed_status(s))

def outcome(+s: L.St, e: Err) -> Out:
  match s:
    case L.Cancelled{}:
      CancelledOut{}
    case L.Pending{}:
      by_error(L.Pending{}, e)
    case L.Running{}:
      by_error(L.Running{}, e)
    case L.Streaming{}:
      by_error(L.Streaming{}, e)
    case L.Disconnected{}:
      by_error(L.Disconnected{}, e)
    case L.Retrying{}:
      by_error(L.Retrying{}, e)
    case L.Completed{}:
      by_error(L.Completed{}, e)
    case L.Failed{}:
      by_error(L.Failed{}, e)

def show(o: Out) -> String:
  match o:
    case Succeeded{}:
      "c"
    case RetryableError{}:
      "r"
    case FatalError{}:
      "f"
    case CancelledOut{}:
      "x"

def row(+s: L.St) -> String:
  show(outcome(s, NoErr{})) ++ show(outcome(s, Retryable{})) ++ show(outcome(s, Fatal{}))

def main() -> IO(Unit):
  IO.print(row(L.Pending{}) ++ row(L.Running{}) ++ row(L.Streaming{}) ++ row(L.Disconnected{}) ++ row(L.Retrying{}) ++ row(L.Completed{}) ++ row(L.Failed{}) ++ row(L.Cancelled{}))
