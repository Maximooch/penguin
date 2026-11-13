import Base
import ./policy.bend as P

law incomplete_blocks:
  for e: Bool
  for p: Bool
  {P.deliver(False{}, e, p) == False{} : Bool}

law error_blocks:
  for d: Bool
  for p: Bool
  {P.deliver(d, True{}, p) == False{} : Bool}

law missing_path_blocks:
  for d: Bool
  for e: Bool
  {P.deliver(d, e, False{}) == False{} : Bool}

law successful_image_survives:
  {P.deliver(True{}, False{}, True{}) == True{} : Bool}
