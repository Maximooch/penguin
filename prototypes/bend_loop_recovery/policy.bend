import Base

# Pure projections only: no provider/tool execution or clock reads.
def recover(stalled: Bool, attempted: Bool) -> Bool:
  match stalled attempted:
    case True{} False{}:
      True{}
    case _ _:
      False{}

def wait_timeout(explicit: Bool, elapsed: Bool) -> Bool:
  match explicit elapsed:
    case True{} True{}:
      True{}
    case _ _:
      False{}

def show(value: Bool) -> String:
  match value:
    case True{}:
      "1"
    case False{}:
      "0"

# Independent balanced branches enumerate all 16 input combinations.
def sample(+stalled: Bool, +attempted: Bool, explicit: Bool, elapsed: Bool) -> String:
  a b = recover(stalled, attempted) wait_timeout(explicit, elapsed)
  show(a) ++ show(b)

def times(+stalled: Bool, +attempted: Bool, +explicit: Bool) -> String:
  a b = sample(stalled, attempted, explicit, False{}) sample(stalled, attempted, explicit, True{})
  a ++ b

def budgets(+stalled: Bool, +attempted: Bool) -> String:
  a b = times(stalled, attempted, False{}) times(stalled, attempted, True{})
  a ++ b

def attempts(+stalled: Bool) -> String:
  a b = budgets(stalled, False{}) budgets(stalled, True{})
  a ++ b

def main() -> IO(Unit):
  a b = attempts(False{}) attempts(True{})
  IO.print(a ++ b)
