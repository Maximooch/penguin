import os
import sys
from pathlib import Path

# Ensure a writable workspace early to avoid import-time logging failures
_ws = Path(os.environ.get("PENGUIN_WORKSPACE", str(Path(__file__).resolve().parent.parent / "tmp_workspace")))
os.environ.setdefault("PENGUIN_WORKSPACE", str(_ws))
_ws.mkdir(parents=True, exist_ok=True)

# Add the project's root source directory ('penguin/') to the Python path
# so that tests can perform absolute imports like 'from penguin.agent import ...'
# This is executed by pytest before it collects any tests.
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root)) 
