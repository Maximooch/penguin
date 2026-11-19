import Base

# A pure projection of ContextWindowManager.trim_session
# (penguin/system/context_window.py) for a session with SYSTEM and two
# trimmable categories: DIALOG (higher priority) and SYSTEM_OUTPUT (lower,
# trimmed first). Each category holds at most two messages, oldest first.
# Python still owns token counting, images and every other category.

# A category's messages, oldest first, as token counts.
type Cat is Data:
  Empty{}
  One{a: Nat}
  Two{a: Nat, b: Nat}

# What trimming one category kept, and how many tokens it removed.
type Cut is Data:
  Cut{kept: Cat, removed: Nat}

# What trimming kept of SYSTEM_OUTPUT and of DIALOG.
type Trim is Data:
  Trim{out: Cat, dia: Cat}

# The window and the two category budgets used by the differential test.
# The budgets add up to more than the window, as Penguin's defaults do.
def window() -> Nat:
  6n

def out_max() -> Nat:
  3n

def out_min() -> Nat:
  1n

def dia_max() -> Nat:
  4n

def dia_min() -> Nat:
  2n

# ---- Nat and Bool helpers (a match may only examine a parameter) ----

def add(a: Nat, b: Nat) -> Nat:
  match a:
    case 0n:
      b
    case 1n+x:
      1n+add(x, b)

# a - b, or 0 when b > a.
def sub(a: Nat, b: Nat) -> Nat:
  match a:
    case 0n:
      0n
    case 1n+x:
      match b:
        case 0n:
          1n+x
        case 1n+y:
          sub(x, y)

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

def not(b: Bool) -> Bool:
  match b:
    case True{}:
      False{}
    case False{}:
      True{}

def le(a: Nat, b: Nat) -> Bool:
  not(gt(a, b))

def pick(c: Bool, x: Nat, y: Nat) -> Nat:
  match c:
    case True{}:
      x
    case False{}:
      y

def nmin(+a: Nat, +b: Nat) -> Nat:
  pick(gt(a, b), b, a)

def nmax(+a: Nat, +b: Nat) -> Nat:
  pick(gt(a, b), a, b)

def both(a: Bool, b: Bool) -> Bool:
  match a:
    case True{}:
      b
    case False{}:
      False{}

def either(a: Bool, b: Bool) -> Bool:
  match a:
    case True{}:
      True{}
    case False{}:
      b

def implies(a: Bool, b: Bool) -> Bool:
  match a:
    case True{}:
      b
    case False{}:
      True{}

def same(+a: Nat, +b: Nat) -> Bool:
  both(le(a, b), le(b, a))

def tokens(c: Cat) -> Nat:
  match c:
    case Empty{}:
      0n
    case One{a}:
      a
    case Two{a, b}:
      add(a, b)

def count(c: Cat) -> Nat:
  match c:
    case Empty{}:
      0n
    case One{a}:
      1n
    case Two{a, b}:
      2n

# ---- The model ----

# Tokens still to trim before the session fits the window. Python's
# `total_over_budget` is exactly "this is above zero".
def start(s: Nat, +o: Cat, +d: Cat) -> Nat:
  sub(add(s, add(tokens(o), tokens(d))), window())

def excess_when(over: Bool, +tok: Nat, mx: Nat, mn: Nat, left: Nat) -> Nat:
  match over:
    case True{}:
      nmax(sub(tok, mx), nmin(left, sub(tok, mn)))
    case False{}:
      sub(tok, mx)

# A category over its own budget is trimmed back to it; while the session is
# over the window it is trimmed by what is still over, down to its minimum.
def excess(tok: Nat, mx: Nat, mn: Nat, +left: Nat) -> Nat:
  excess_when(gt(left, 0n), tok, mx, mn, left)

def cut_one(go: Bool, a: Nat) -> Cut:
  match go:
    case True{}:
      Cut{Empty{}, a}
    case False{}:
      Cut{One{a}, 0n}

def cut_second(go: Bool, a: Nat, b: Nat) -> Cut:
  match go:
    case True{}:
      Cut{Empty{}, add(a, b)}
    case False{}:
      Cut{One{b}, a}

def cut_first(go: Bool, ex: Nat, +a: Nat, b: Nat) -> Cut:
  match go:
    case True{}:
      cut_second(gt(ex, a), a, b)
    case False{}:
      Cut{Two{a, b}, 0n}

# Remove whole messages, oldest first, while fewer than `ex` tokens are gone.
def cut(c: Cat, +ex: Nat) -> Cut:
  match c:
    case Empty{}:
      Cut{Empty{}, 0n}
    case One{a}:
      cut_one(gt(ex, 0n), a)
    case Two{a, b}:
      cut_first(gt(ex, 0n), ex, a, b)

def cut_category(+c: Cat, mx: Nat, mn: Nat, left: Nat) -> Cut:
  cut(c, excess(tokens(c), mx, mn, left))

def kept_of(c: Cut) -> Cat:
  match c:
    case Cut{kept, removed}:
      kept

def then_dialog(c: Cut, d: Cat, left: Nat) -> Trim:
  match c:
    case Cut{kept, removed}:
      Trim{kept, kept_of(cut_category(d, dia_max(), dia_min(), sub(left, removed)))}

# SYSTEM_OUTPUT first, then DIALOG; SYSTEM is never trimmed.
def trim(+s: Nat, +o: Cat, +d: Cat) -> Trim:
  then_dialog(cut_category(o, out_max(), out_min(), start(s, o, d)), d, start(s, o, d))

def out_of(r: Trim) -> Cat:
  match r:
    case Trim{out, dia}:
      out

def dia_of(r: Trim) -> Cat:
  match r:
    case Trim{out, dia}:
      dia

# ---- Properties checked over every session in the enumerated space ----

type Law is Data:
  Fits{}
  Untouched{}
  OutputFirst{}
  Floor{}

def total(s: Nat, o: Cat, d: Cat) -> Nat:
  add(s, add(tokens(o), tokens(d)))

# The session fits the window, or both trimmable categories are at or below
# their minimums (only then can SYSTEM and the minimums keep it over).
def fits(s: Nat, +o: Cat, +d: Cat) -> Bool:
  either(le(total(s, o, d), window()), both(le(tokens(o), out_min()), le(tokens(d), dia_min())))

def within(s: Nat, +o: Cat, +d: Cat) -> Bool:
  both(le(total(s, o, d), window()), both(le(tokens(o), out_max()), le(tokens(d), dia_max())))

# A category at or below its minimum and within its budget loses nothing.
def floor_kept(+c: Cat, mx: Nat, +mn: Nat, k: Cat) -> Bool:
  implies(both(le(tokens(c), mn), le(tokens(c), mx)), same(count(k), count(c)))

def holds(rule: Law, +s: Nat, +o: Cat, +d: Cat) -> Bool:
  match rule:
    case Fits{}:
      fits(s, out_of(trim(s, o, d)), dia_of(trim(s, o, d)))
    case Untouched{}:
      implies(within(s, o, d), same(add(count(out_of(trim(s, o, d))), count(dia_of(trim(s, o, d)))), add(count(o), count(d))))
    case OutputFirst{}:
      implies(gt(count(d), count(dia_of(trim(s, o, d)))), either(gt(tokens(d), dia_max()), le(tokens(out_of(trim(s, o, d))), out_min())))
    case Floor{}:
      both(floor_kept(o, out_max(), out_min(), out_of(trim(s, o, d))), floor_kept(d, dia_max(), dia_min(), dia_of(trim(s, o, d))))

# ---- The enumerated space: SYSTEM 0 or 2 tokens; each trimmable category
# empty, one message of 1-3 tokens, or two messages of 1-3 tokens each. ----

def over_d(+rule: Law, +s: Nat, +o: Cat) -> Bool:
  holds(rule, s, o, Empty{}) && holds(rule, s, o, One{1n}) && holds(rule, s, o, One{2n}) && holds(rule, s, o, One{3n}) && holds(rule, s, o, Two{1n, 1n}) && holds(rule, s, o, Two{1n, 2n}) && holds(rule, s, o, Two{1n, 3n}) && holds(rule, s, o, Two{2n, 1n}) && holds(rule, s, o, Two{2n, 2n}) && holds(rule, s, o, Two{2n, 3n}) && holds(rule, s, o, Two{3n, 1n}) && holds(rule, s, o, Two{3n, 2n}) && holds(rule, s, o, Two{3n, 3n})

def over_o(+rule: Law, +s: Nat) -> Bool:
  over_d(rule, s, Empty{}) && over_d(rule, s, One{1n}) && over_d(rule, s, One{2n}) && over_d(rule, s, One{3n}) && over_d(rule, s, Two{1n, 1n}) && over_d(rule, s, Two{1n, 2n}) && over_d(rule, s, Two{1n, 3n}) && over_d(rule, s, Two{2n, 1n}) && over_d(rule, s, Two{2n, 2n}) && over_d(rule, s, Two{2n, 3n}) && over_d(rule, s, Two{3n, 1n}) && over_d(rule, s, Two{3n, 2n}) && over_d(rule, s, Two{3n, 3n})

def all(+rule: Law) -> Bool:
  over_o(rule, 0n) && over_o(rule, 2n)

# ---- The table the differential test compares with Python ----

def show(r: Trim) -> String:
  match r:
    case Trim{out, dia}:
      Nat.show(count(out)) ++ Nat.show(count(dia)) ++ ","

def row_d(+s: Nat, +o: Cat) -> String:
  show(trim(s, o, Empty{})) ++ show(trim(s, o, One{1n})) ++ show(trim(s, o, One{2n})) ++ show(trim(s, o, One{3n})) ++ show(trim(s, o, Two{1n, 1n})) ++ show(trim(s, o, Two{1n, 2n})) ++ show(trim(s, o, Two{1n, 3n})) ++ show(trim(s, o, Two{2n, 1n})) ++ show(trim(s, o, Two{2n, 2n})) ++ show(trim(s, o, Two{2n, 3n})) ++ show(trim(s, o, Two{3n, 1n})) ++ show(trim(s, o, Two{3n, 2n})) ++ show(trim(s, o, Two{3n, 3n}))

def row_o(+s: Nat) -> String:
  row_d(s, Empty{}) ++ row_d(s, One{1n}) ++ row_d(s, One{2n}) ++ row_d(s, One{3n}) ++ row_d(s, Two{1n, 1n}) ++ row_d(s, Two{1n, 2n}) ++ row_d(s, Two{1n, 3n}) ++ row_d(s, Two{2n, 1n}) ++ row_d(s, Two{2n, 2n}) ++ row_d(s, Two{2n, 3n}) ++ row_d(s, Two{3n, 1n}) ++ row_d(s, Two{3n, 2n}) ++ row_d(s, Two{3n, 3n})

# Kept message counts of SYSTEM_OUTPUT then DIALOG for every session: SYSTEM
# 0 then 2 tokens, SYSTEM_OUTPUT outer, DIALOG inner, in the order above.
def main() -> IO(Unit):
  IO.print(row_o(0n) ++ row_o(2n))
