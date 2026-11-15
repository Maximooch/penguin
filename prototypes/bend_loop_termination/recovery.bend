import Base

# A pure projection of the recovery-turn caps in Engine._iteration_loop
# (penguin/engine.py). An output-limit turn and a malformed-syntax repair turn
# each continue the loop until their cap; both counters reset only after an
# ordinary turn. Python still owns the conversation and every other check.

# What one turn did, as far as the caps are concerned.
type Turn is Data:
  OutputLimit{}
  BrokenSyntax{}
  Ordinary{}

# The loop after some turns: still going with its counters, or stopped at a
# 1-based turn number.
type Run is Data:
  Going{oc: Nat, rc: Nat}
  Stopped{at: U32}

# MAX_CONSECUTIVE_OUTPUT_CONTINUATIONS and MAX_MALFORMED_ACTION_REPAIRS.
def out_cap() -> Nat:
  8n

def rep_cap() -> Nat:
  3n

def gt(a: Nat, b: Nat) -> Bool:
  match a:
    case 0n:
      False{}
    case 1n+x:
      match b:
        case 0n:
          True{}
        case 1n+y:
          gt(x, y)

def cap(over: Bool, next: Run, at: U32) -> Run:
  match over:
    case True{}:
      Stopped{at}
    case False{}:
      next

def step(t: Turn, +oc: Nat, +rc: Nat, at: U32) -> Run:
  match t:
    case OutputLimit{}:
      cap(gt(1n+oc, out_cap()), Going{1n+oc, rc}, at)
    case BrokenSyntax{}:
      cap(gt(1n+rc, rep_cap()), Going{oc, 1n+rc}, at)
    case Ordinary{}:
      Going{0n, 0n}

def advance(s: Run, t: Turn, at: U32) -> Run:
  match s:
    case Going{oc, rc}:
      step(t, oc, rc, at)
    case Stopped{at0}:
      Stopped{at0}

def is_stopped(s: Run) -> Bool:
  match s:
    case Going{oc, rc}:
      False{}
    case Stopped{at}:
      True{}

# Whether every sequence of k recovery turns from s has stopped by its end.
def stops_within(+k: Nat, +s: Run) -> Bool:
  match k:
    case 0n:
      is_stopped(s)
    case 1n+p:
      stops_within(p, advance(s, OutputLimit{}, 0)) && stops_within(p, advance(s, BrokenSyntax{}, 0))

def show(s: Run) -> String:
  match s:
    case Going{oc, rc}:
      "0,"
    case Stopped{at}:
      U32.show(at) ++ ","

# The stop turn of every sequence of k recovery turns, first turn most
# significant, output limit before broken syntax.
def recovery_table(+k: Nat, +d: U32, +s: Run) -> String:
  match k:
    case 0n:
      show(s)
    case 1n+p:
      recovery_table(p, (d + 1 : U32), advance(s, OutputLimit{}, (d + 1 : U32))) ++ recovery_table(p, (d + 1 : U32), advance(s, BrokenSyntax{}, (d + 1 : U32)))

# The same for sequences that also contain ordinary turns.
def mixed_table(+k: Nat, +d: U32, +s: Run) -> String:
  match k:
    case 0n:
      show(s)
    case 1n+p:
      mixed_table(p, (d + 1 : U32), advance(s, OutputLimit{}, (d + 1 : U32))) ++ mixed_table(p, (d + 1 : U32), advance(s, BrokenSyntax{}, (d + 1 : U32))) ++ mixed_table(p, (d + 1 : U32), advance(s, Ordinary{}, (d + 1 : U32)))

def main() -> IO(Unit):
  IO.print(recovery_table(12n, 0, Going{0n, 0n}) ++ " " ++ mixed_table(6n, 0, Going{0n, 0n}))
