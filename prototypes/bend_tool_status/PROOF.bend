import Base
import ./LAWS.bend as Laws

def Laws.error_flag_wins(r):
  {==}

def Laws.pending_approval_requires_approval():
  {==}

def Laws.requires_approval_requires_approval():
  {==}

def Laws.pending_approval_halts(e):
  match e:
    case True{}:
      {==}
    case False{}:
      {==}

def Laws.requires_approval_halts(e):
  match e:
    case True{}:
      {==}
    case False{}:
      {==}

def Laws.error_halts(e):
  match e:
    case True{}:
      {==}
    case False{}:
      {==}

def Laws.cancelled_halts(e):
  match e:
    case True{}:
      {==}
    case False{}:
      {==}

def Laws.reported_error_halts(r):
  {==}

def Laws.clean_completion_continues():
  {==}
