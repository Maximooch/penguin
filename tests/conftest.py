import sys
from pathlib import Path

# Add the project's root source directory ('penguin/') to the Python path
# so that tests can perform absolute imports like 'from penguin.agent import ...'
# This is executed by pytest before it collects any tests.
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root)) 