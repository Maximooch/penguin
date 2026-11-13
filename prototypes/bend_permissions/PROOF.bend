import Base
import ./LAWS.bend as Laws
import ./permissions.bend as P

def Laws.deny_left(x):
  match x:
    case P.Allow{}:
      {==}
    case P.Ask{}:
      {==}
    case P.Deny{}:
      {==}

def Laws.deny_right(x):
  match x:
    case P.Allow{}:
      {==}
    case P.Ask{}:
      {==}
    case P.Deny{}:
      {==}

def Laws.allow_identity(x):
  match x:
    case P.Allow{}:
      {==}
    case P.Ask{}:
      {==}
    case P.Deny{}:
      {==}

def Laws.commutative(a, b):
  match a b:
    case P.Allow{} P.Allow{}:
      {==}
    case P.Allow{} P.Ask{}:
      {==}
    case P.Allow{} P.Deny{}:
      {==}
    case P.Ask{} P.Allow{}:
      {==}
    case P.Ask{} P.Ask{}:
      {==}
    case P.Ask{} P.Deny{}:
      {==}
    case P.Deny{} P.Allow{}:
      {==}
    case P.Deny{} P.Ask{}:
      {==}
    case P.Deny{} P.Deny{}:
      {==}

def Laws.associative(a, b, c):
  match a b c:
    case P.Allow{} P.Allow{} P.Allow{}:
      {==}
    case P.Allow{} P.Allow{} P.Ask{}:
      {==}
    case P.Allow{} P.Allow{} P.Deny{}:
      {==}
    case P.Allow{} P.Ask{} P.Allow{}:
      {==}
    case P.Allow{} P.Ask{} P.Ask{}:
      {==}
    case P.Allow{} P.Ask{} P.Deny{}:
      {==}
    case P.Allow{} P.Deny{} P.Allow{}:
      {==}
    case P.Allow{} P.Deny{} P.Ask{}:
      {==}
    case P.Allow{} P.Deny{} P.Deny{}:
      {==}
    case P.Ask{} P.Allow{} P.Allow{}:
      {==}
    case P.Ask{} P.Allow{} P.Ask{}:
      {==}
    case P.Ask{} P.Allow{} P.Deny{}:
      {==}
    case P.Ask{} P.Ask{} P.Allow{}:
      {==}
    case P.Ask{} P.Ask{} P.Ask{}:
      {==}
    case P.Ask{} P.Ask{} P.Deny{}:
      {==}
    case P.Ask{} P.Deny{} P.Allow{}:
      {==}
    case P.Ask{} P.Deny{} P.Ask{}:
      {==}
    case P.Ask{} P.Deny{} P.Deny{}:
      {==}
    case P.Deny{} P.Allow{} P.Allow{}:
      {==}
    case P.Deny{} P.Allow{} P.Ask{}:
      {==}
    case P.Deny{} P.Allow{} P.Deny{}:
      {==}
    case P.Deny{} P.Ask{} P.Allow{}:
      {==}
    case P.Deny{} P.Ask{} P.Ask{}:
      {==}
    case P.Deny{} P.Ask{} P.Deny{}:
      {==}
    case P.Deny{} P.Deny{} P.Allow{}:
      {==}
    case P.Deny{} P.Deny{} P.Ask{}:
      {==}
    case P.Deny{} P.Deny{} P.Deny{}:
      {==}

def Laws.ask_requires_approval():
  {==}

def Laws.branch_combines_children(left, right):
  {==}

def Laws.leaf_identity(x):
  {==}
