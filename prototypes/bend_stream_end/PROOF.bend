import Base
import ./LAWS.bend as Laws

def Laws.cancelled_wins(e, t, x, o, s):
  {==}

def Laws.provider_error_wins(t, x, o, s):
  {==}

def Laws.no_end_marker_is_incomplete(x, o, s):
  {==}

def Laws.cancelled_drops_tool_calls(e, t, x, o, s):
  {==}

def Laws.provider_error_drops_tool_calls(c, t, x, o, s):
  match c:
    case True{}:
      {==}
    case False{}:
      {==}

def Laws.incomplete_drops_tool_calls(c, e, x, o, s):
  match c e:
    case True{} _:
      {==}
    case False{} True{}:
      {==}
    case False{} False{}:
      {==}

def Laws.length_cut_drops_tool_calls(c, e, t, o, s):
  match c e t:
    case True{} _ _:
      {==}
    case False{} True{} _:
      {==}
    case False{} False{} False{}:
      {==}
    case False{} False{} True{}:
      {==}

def Laws.filter_cut_drops_tool_calls(c, e, t, o, s):
  match c e t:
    case True{} _ _:
      {==}
    case False{} True{} _:
      {==}
    case False{} False{} False{}:
      {==}
    case False{} False{} True{}:
      {==}

def Laws.clean_tool_call_is_kept(s):
  {==}

def Laws.clean_text_is_text():
  {==}
