import inspect
import sys
from pathlib import Path
import importlib

# Ensure repo root (one level above tests/) is first on import path so we
# import the *local* penguin package rather than any globally-installed one.
root_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root_dir))

sys.modules.pop("penguin", None)  # ensure fresh import from local path
pkg = importlib.import_module("penguin")


def test_public_surface_symbols_present():
    # Symbols expected to be exported by penguin.__all__
    expected = {
        "PenguinAgent",
        "PenguinAgentAsync",
        "PenguinCore",
        "Engine",
        "ToolManager",
        "__version__",
    }
    for symbol in expected:
        assert hasattr(pkg, symbol), f"{symbol} missing from penguin package"
        # Skip __version__ for class check
        if symbol != "__version__":
            obj = getattr(pkg, symbol)
            assert inspect.isclass(obj), f"{symbol} should be class, got {type(obj)}"


def test_version_string():
    assert isinstance(pkg.__version__, str) and pkg.__version__, "__version__ should be non-empty string" 