import Base

# A pure projection of penguin.llm.contracts.next_request_status: the status a
# provider request moves to when a new status is asked for. Python still owns
# the request, its timestamps and its metadata.

# ProviderRequestStatus in penguin/llm/contracts.py.
type St is Data:
  Pending{}
  Running{}
  Streaming{}
  Disconnected{}
  Retrying{}
  Completed{}
  Failed{}
  Cancelled{}

# Which group of statuses a status belongs to.
type Group is Data:
  Active{}
  Ended{}
  Retry{}
  Final{}

def kind(s: St) -> Group:
  match s:
    case Pending{}:
      Active{}
    case Running{}:
      Active{}
    case Streaming{}:
      Active{}
    case Disconnected{}:
      Ended{}
    case Failed{}:
      Ended{}
    case Retrying{}:
      Retry{}
    case Completed{}:
      Final{}
    case Cancelled{}:
      Final{}

def is_retrying(s: St) -> Bool:
  match s:
    case Retrying{}:
      True{}
    case Pending{}:
      False{}
    case Running{}:
      False{}
    case Streaming{}:
      False{}
    case Disconnected{}:
      False{}
    case Completed{}:
      False{}
    case Failed{}:
      False{}
    case Cancelled{}:
      False{}

# Where a retry may end.
def ends_retry(s: St) -> Bool:
  match s:
    case Retrying{}:
      True{}
    case Cancelled{}:
      True{}
    case Failed{}:
      True{}
    case Pending{}:
      False{}
    case Running{}:
      False{}
    case Streaming{}:
      False{}
    case Disconnected{}:
      False{}
    case Completed{}:
      False{}

def pick(b: Bool, yes: St, no: St) -> St:
  match b:
    case True{}:
      yes
    case False{}:
      no

def by_group(g: Group, +cur: St, +req: St) -> St:
  match g:
    case Final{}:
      cur
    case Ended{}:
      pick(is_retrying(req), req, cur)
    case Retry{}:
      pick(ends_retry(req), req, cur)
    case Active{}:
      pick(is_retrying(req), cur, req)

def next(+cur: St, +req: St) -> St:
  by_group(kind(cur), cur, req)

def show(s: St) -> String:
  match s:
    case Pending{}:
      "p"
    case Running{}:
      "r"
    case Streaming{}:
      "s"
    case Disconnected{}:
      "d"
    case Retrying{}:
      "y"
    case Completed{}:
      "c"
    case Failed{}:
      "f"
    case Cancelled{}:
      "x"

def row(+cur: St) -> String:
  show(next(cur, Pending{})) ++ show(next(cur, Running{})) ++ show(next(cur, Streaming{})) ++ show(next(cur, Disconnected{})) ++ show(next(cur, Retrying{})) ++ show(next(cur, Completed{})) ++ show(next(cur, Failed{})) ++ show(next(cur, Cancelled{}))

def main() -> IO(Unit):
  IO.print(row(Pending{}) ++ row(Running{}) ++ row(Streaming{}) ++ row(Disconnected{}) ++ row(Retrying{}) ++ row(Completed{}) ++ row(Failed{}) ++ row(Cancelled{}))
