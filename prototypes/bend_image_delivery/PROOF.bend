import Base
import ./LAWS.bend as Laws

def Laws.incomplete_blocks(e, p):
  {==}

def Laws.error_blocks(d, p):
  match d:
    case False{}:
      {==}
    case True{}:
      {==}

def Laws.missing_path_blocks(d, e):
  match d e:
    case False{} _:
      {==}
    case True{} True{}:
      {==}
    case True{} False{}:
      {==}

def Laws.successful_image_survives():
  {==}
