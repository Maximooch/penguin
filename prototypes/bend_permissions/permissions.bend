import Base

# Pure decision aggregation only: never run effectful policies in parallel.
type Decision is Data:
  Allow{}
  Ask{}
  Deny{}

def combine(a: Decision, b: Decision) -> Decision:
  match a b:
    case Deny{} _:
      Deny{}
    case _ Deny{}:
      Deny{}
    case Ask{} _:
      Ask{}
    case _ Ask{}:
      Ask{}
    case Allow{} Allow{}:
      Allow{}

type Decisions is Data:
  Leaf{decision: Decision}
  Branch{left: Decisions, right: Decisions}

def aggregate(tree: Decisions) -> Decision:
  match tree:
    case Leaf{decision}:
      decision
    case Branch{left, right}:
      a b = aggregate(left) aggregate(right)
      combine(a, b)

def main() -> Decision:
  aggregate(Branch{Leaf{Allow{}}, Branch{Leaf{Ask{}}, Leaf{Deny{}}}})
