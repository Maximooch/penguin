import Base

# A pure projection of penguin.tools.runtime.tool_status_from_output and
# halts_ordered_execution. Python still owns JSON parsing and tool execution;
# this model starts from the already-extracted `error` flag and `status` word.

# The `status` word a tool output may carry. Other{} is any unrecognised word,
# including a missing status.
type Raw is Data:
  RawCompleted{}
  RawError{}
  RawCancelled{}
  RawPendingApproval{}
  RawRequiresApproval{}
  Other{}

# ToolResultStatus in penguin/tools/runtime.py.
type Status is Data:
  Completed{}
  Error{}
  Cancelled{}
  RequiresApproval{}

def status(has_error: Bool, raw: Raw) -> Status:
  match has_error raw:
    case True{} _:
      Error{}
    case False{} RawError{}:
      Error{}
    case False{} RawCancelled{}:
      Cancelled{}
    case False{} RawPendingApproval{}:
      RequiresApproval{}
    case False{} RawRequiresApproval{}:
      RequiresApproval{}
    case False{} RawCompleted{}:
      Completed{}
    case False{} Other{}:
      Completed{}

# Whether a result stops the ordered calls that follow it.
def halts(s: Status) -> Bool:
  match s:
    case Completed{}:
      False{}
    case Error{}:
      True{}
    case Cancelled{}:
      True{}
    case RequiresApproval{}:
      True{}

def show(s: Status) -> String:
  match s:
    case Completed{}:
      "c"
    case Error{}:
      "e"
    case Cancelled{}:
      "x"
    case RequiresApproval{}:
      "r"

def flag(b: Bool) -> String:
  match b:
    case True{}:
      "1"
    case False{}:
      "0"

def cell(+has_error: Bool, +raw: Raw) -> String:
  show(status(has_error, raw)) ++ flag(halts(status(has_error, raw)))

def row(+e: Bool) -> String:
  cell(e, RawCompleted{}) ++ cell(e, RawError{}) ++ cell(e, RawCancelled{}) ++ cell(e, RawPendingApproval{}) ++ cell(e, RawRequiresApproval{}) ++ cell(e, Other{})

def main() -> IO(Unit):
  IO.print(row(False{}) ++ row(True{}))
