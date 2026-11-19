import Base

# A pure projection of penguin.llm.stream_end.classify_stream_end and
# keeps_tool_calls. Python still owns the provider request, event parsing and
# tool-call accumulation; this model starts from the facts an adapter holds
# when its event loop ends.

# Whether the provider cut the output short, and why.
type Early is Data:
  NoEarly{}
  Length{}
  Filter{}

# StreamEnd in penguin/llm/stream_end.py.
type End is Data:
  Cancelled{}
  ProviderError{}
  Incomplete{}
  Truncated{}
  Filtered{}
  ToolCalls{}
  Answer{}
  Empty{}

def end(cancelled: Bool, error: Bool, terminal: Bool, early: Early, tool: Bool, text: Bool) -> End:
  match cancelled error terminal early tool text:
    case True{} _ _ _ _ _:
      Cancelled{}
    case False{} True{} _ _ _ _:
      ProviderError{}
    case False{} False{} False{} _ _ _:
      Incomplete{}
    case False{} False{} True{} Filter{} _ _:
      Filtered{}
    case False{} False{} True{} Length{} _ _:
      Truncated{}
    case False{} False{} True{} NoEarly{} True{} _:
      ToolCalls{}
    case False{} False{} True{} NoEarly{} False{} True{}:
      Answer{}
    case False{} False{} True{} NoEarly{} False{} False{}:
      Empty{}

# Whether tool calls gathered during the stream may be executed.
def keeps(e: End) -> Bool:
  match e:
    case ToolCalls{}:
      True{}
    case Cancelled{}:
      False{}
    case ProviderError{}:
      False{}
    case Incomplete{}:
      False{}
    case Truncated{}:
      False{}
    case Filtered{}:
      False{}
    case Answer{}:
      False{}
    case Empty{}:
      False{}

def show(e: End) -> String:
  match e:
    case Cancelled{}:
      "c"
    case ProviderError{}:
      "p"
    case Incomplete{}:
      "i"
    case Truncated{}:
      "l"
    case Filtered{}:
      "f"
    case ToolCalls{}:
      "t"
    case Answer{}:
      "x"
    case Empty{}:
      "e"

def flag(b: Bool) -> String:
  match b:
    case True{}:
      "1"
    case False{}:
      "0"

def cell(+c: Bool, +e: Bool, +t: Bool, +x: Early, +o: Bool, +s: Bool) -> String:
  show(end(c, e, t, x, o, s)) ++ flag(keeps(end(c, e, t, x, o, s)))

def texts(+c: Bool, +e: Bool, +t: Bool, +x: Early, +o: Bool) -> String:
  cell(c, e, t, x, o, False{}) ++ cell(c, e, t, x, o, True{})

def tools(+c: Bool, +e: Bool, +t: Bool, +x: Early) -> String:
  texts(c, e, t, x, False{}) ++ texts(c, e, t, x, True{})

def earlies(+c: Bool, +e: Bool, +t: Bool) -> String:
  tools(c, e, t, NoEarly{}) ++ tools(c, e, t, Length{}) ++ tools(c, e, t, Filter{})

def terminals(+c: Bool, +e: Bool) -> String:
  earlies(c, e, False{}) ++ earlies(c, e, True{})

def errors(+c: Bool) -> String:
  terminals(c, False{}) ++ terminals(c, True{})

def main() -> IO(Unit):
  IO.print(errors(False{}) ++ errors(True{}))
