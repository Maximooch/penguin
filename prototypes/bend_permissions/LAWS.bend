import Base
import ./permissions.bend as P

# Proposed model contracts for human review; not proofs of Python code.
# Preserve these claims when changing the implementation or its proofs.
law deny_left:
  for x: P.Decision
  {P.combine(P.Deny{}, x) == P.Deny{} : P.Decision}

law deny_right:
  for x: P.Decision
  {P.combine(x, P.Deny{}) == P.Deny{} : P.Decision}

law allow_identity:
  for x: P.Decision
  {P.combine(P.Allow{}, x) == x : P.Decision}

law ask_requires_approval:
  {P.combine(P.Ask{}, P.Allow{}) == P.Ask{} : P.Decision}

law commutative:
  for a: P.Decision
  for b: P.Decision
  {P.combine(a, b) == P.combine(b, a) : P.Decision}

law associative:
  for a: P.Decision
  for b: P.Decision
  for c: P.Decision
  {P.combine(P.combine(a, b), c) == P.combine(a, P.combine(b, c)) : P.Decision}

law branch_combines_children:
  for left: P.Decisions
  for right: P.Decisions
  {P.aggregate(P.Branch{left, right}) == P.combine(P.aggregate(left), P.aggregate(right)) : P.Decision}

# Every leaf must preserve its supplied decision, not silently weaken it.
law leaf_identity:
  for x: P.Decision
  {P.aggregate(P.Leaf{x}) == x : P.Decision}
