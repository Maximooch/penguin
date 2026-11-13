import Base

# Only successful, error-free results with a usable path may expose images.
def deliver(done: Bool, error: Bool, path: Bool) -> Bool:
  match done error path:
    case True{} False{} True{}:
      True{}
    case _ _ _:
      False{}

def show(value: Bool) -> String:
  match value:
    case True{}:
      "1"
    case False{}:
      "0"

def paths(+d: Bool, +e: Bool) -> String:
  a b = deliver(d, e, False{}) deliver(d, e, True{})
  show(a) ++ show(b)

def errors(+d: Bool) -> String:
  a b = paths(d, False{}) paths(d, True{})
  a ++ b

def main() -> IO(Unit):
  a b = errors(False{}) errors(True{})
  IO.print(a ++ b)
