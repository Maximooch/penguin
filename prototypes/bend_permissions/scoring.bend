import Base

# Synthetic pure scoring kernel, NOT Penguin production permission checks.
# Every leaf must contribute to the checksum (no DENY short-circuit shortcut).
def score(work: Nat, state: U32) -> U32:
  match work:
    case 0n:
      state
    case 1n+rest:
      score(rest, (state * 1664525 + 1013904223 : U32))

# Fork only the top levels, then process sequentially within each task.
def batch(depth: Nat, forks: Nat, +work: Nat, +seed: U32) -> U32:
  match depth forks:
    case 0n _:
      score(work, seed)
    case 1n+ +d 0n:
      left = batch(d, 0n, work, (seed * 2 : U32))
      right = batch(d, 0n, work, (seed * 2 + 1 : U32))
      (left + right : U32)
    case 1n+ +d 1n+ +f:
      left right = batch(d, f, work, (seed * 2 : U32)) batch(d, f, work, (seed * 2 + 1 : U32))
      (left + right : U32)

def parsed(depth: Maybe<&2, Nat>, forks: Maybe<&2, Nat>, work: Maybe<&2, Nat>) -> IO(Unit):
  match depth forks work:
    case Some{d} Some{f} Some{w}:
      IO.print(U32.show(batch(d, f, w, 1)))
    case _ _ _:
      IO.die(Unit, 2, "expected nonnegative integer depth, forks, work")

def run(args: List<String>) -> IO(Unit):
  match args:
    case depth <> forks <> work <> Nil{}:
      parsed(Nat.read(depth), Nat.read(forks), Nat.read(work))
    case _:
      IO.die(Unit, 2, "usage: scoring DEPTH FORKS WORK")

def main() -> IO(Unit):
  do IO<Unit>:
    args : List<String> <- IO.args()
    run(List.drop(&1, String, args, 1n))
