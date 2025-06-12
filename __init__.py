import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure embedded sub-package path ('penguin/penguin') is importable BEFORE
# any sub-modules are imported (e.g., penguin.core -> system_prompt -> prompt_workflow)
# ---------------------------------------------------------------------------
_subpkg_path = Path(__file__).resolve().parent / "penguin"
if _subpkg_path.exists() and str(_subpkg_path) not in sys.path:
    sys.path.insert(0, str(_subpkg_path))

# ---------------------------------------------------------------------------
# Re-export public convenience classes (imports below rely on path tweak above)
# ---------------------------------------------------------------------------

from penguin.agent import PenguinAgent, PenguinAgentAsync  # noqa: E402

# Handle Core import for both mono-package and nested package layouts
try:
    from penguin.core import PenguinCore  # type: ignore
except ImportError:  # fallback for repo layout with nested penguin/core.py
    from penguin.penguin.core import PenguinCore  # type: ignore

# Handle Engine import for both mono-package and nested package layouts
try:
    from penguin.engine import Engine  # type: ignore
except ImportError:  # fallback for repo layout with nested penguin/engine.py
    from penguin.penguin.engine import Engine  # type: ignore

from penguin.tools import ToolManager  # noqa: E402

# Version helper
try:
    __version__ = version("penguin-ai")
except PackageNotFoundError:  # Local dev mode (editable install)
    __version__ = "0.1.2-dev"

__all__ = [
    "Engine",
    "PenguinAgent",
    "PenguinAgentAsync",
    "PenguinCore",
    "ToolManager",
    "__version__",
]
