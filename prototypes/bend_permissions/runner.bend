import Base
import ./permissions.bend as P

def prepend(value: P.Decision, tail: Result<String, List<&2, P.Decision>>) -> Result<String, List<&2, P.Decision>>:
  match tail:
    case Done{xs}:
      Done{value <> xs}
    case Fail{message}:
      Fail{message}

# The boundary accepts only explicit decisions. No Python policy executes here.
def parse(text: String) -> Result<String, List<&2, P.Decision>>:
  match text:
    case SNil{}:
      Done{Nil{}}
    case SCon{'a', rest}:
      prepend(P.Allow{}, parse(rest))
    case SCon{'q', rest}:
      prepend(P.Ask{}, parse(rest))
    case SCon{'d', rest}:
      prepend(P.Deny{}, parse(rest))
    case _:
      Fail{"invalid decision: expected a, q, or d"}

# Fuel decreases structurally; halves form independent parallel subtrees.
def tree(fuel: Nat, +xs: List<&2, P.Decision>) -> P.Decisions:
  match fuel xs:
    case _ Nil{}:
      P.Leaf{P.Allow{}}
    case _ value <> Nil{}:
      P.Leaf{value}
    case 0n _:
      P.Leaf{P.Deny{}}
    case 1n+ +rest _:
      +half = Nat.div(List.length(&2, P.Decision, xs), 2n)
      left right = tree(rest, List.take(&2, P.Decision, xs, half)) tree(rest, List.drop(&2, P.Decision, xs, half))
      P.Branch{left, right}

def show(value: P.Decision) -> String:
  match value:
    case P.Allow{}:
      "allow"
    case P.Ask{}:
      "ask"
    case P.Deny{}:
      "deny"

def emit(parsed: Result<String, List<&2, P.Decision>>) -> IO(Unit):
  match parsed:
    case Fail{message}:
      IO.die(Unit, 2, message)
    case Done{+xs}:
      IO.print(show(P.aggregate(tree(List.length(&2, P.Decision, xs), xs))))

def run(args: List<String>) -> IO(Unit):
  match args:
    case Nil{}:
      IO.pure(Unit, Unit{})
    case value <> rest:
      do IO<Unit>:
        ignored : Unit <- emit(parse(value))
        run(rest)

def main() -> IO(Unit):
  do IO<Unit>:
    args : List<String> <- IO.args()
    run(List.drop(&1, String, args, 1n))
