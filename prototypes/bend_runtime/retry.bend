import Base

# A pure projection of runtime.should_retry_provider_failure.
# Error existence, retryability, emitted text/tools and response classification
# are provided by Python; no provider request or side effect executes here.
def retry(exists: Bool, retryable: Bool, emitted: Bool, tool: Bool, blocked: Bool) -> Bool:
  match exists retryable emitted tool blocked:
    case True{} True{} False{} False{} False{}:
      True{}
    case _ _ _ _ _:
      False{}

def show(value: Bool) -> String:
  match value:
    case True{}:
      "1"
    case False{}:
      "0"

# The two sides of each pair are independent pure computations.
def pair(+e: Bool, +r: Bool, +s: Bool, +t: Bool) -> String:
  a b = retry(e, r, s, t, False{}) retry(e, r, s, t, True{})
  show(a) ++ show(b)

def tools(+e: Bool, +r: Bool, +s: Bool) -> String:
  a b = pair(e, r, s, False{}) pair(e, r, s, True{})
  a ++ b

def streams(+e: Bool, +r: Bool) -> String:
  a b = tools(e, r, False{}) tools(e, r, True{})
  a ++ b

def errors(+e: Bool) -> String:
  a b = streams(e, False{}) streams(e, True{})
  a ++ b

def main() -> IO(Unit):
  a b = errors(False{}) errors(True{})
  IO.print(a ++ b)
