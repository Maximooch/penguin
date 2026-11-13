import Base
import ./LAWS.bend as Laws

def Laws.missing_error(r, s, t, b):
  {==}

def Laws.emitted_text_blocks(e, r, t, b):
  match e r:
    case False{} _:
      {==}
    case True{} False{}:
      {==}
    case True{} True{}:
      {==}

def Laws.pending_tool_blocks(e, r, s, b):
  match e r s:
    case False{} _ _:
      {==}
    case True{} False{} _:
      {==}
    case True{} True{} True{}:
      {==}
    case True{} True{} False{}:
      {==}

def Laws.clean_retryable_failure():
  {==}


def Laws.non_retryable_blocks(e, s, t, b):
  match e:
    case False{}:
      {==}
    case True{}:
      {==}

def Laws.useful_response_blocks(e, r, s, t):
  match e r s t:
    case False{} _ _ _:
      {==}
    case True{} False{} _ _:
      {==}
    case True{} True{} True{} _:
      {==}
    case True{} True{} False{} True{}:
      {==}
    case True{} True{} False{} False{}:
      {==}
