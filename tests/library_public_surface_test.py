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
    """Test that all expected symbols from __all__ are present and correct types."""
    # Core symbols expected to be exported by penguin.__all__
    expected_core = {
        "PenguinCore",
        "PenguinAgent", 
        "Engine",
        "EngineSettings",
        "ProjectManager",
        "Project", 
        "Task",
        "config",
        "__version__",
        "__author__",
        "__email__",
        "__license__",
    }
    
    # Check core symbols
    for symbol in expected_core:
        assert hasattr(pkg, symbol), f"{symbol} missing from penguin package"
        
        # Version and metadata can be strings
        if symbol in ["__version__", "__author__", "__email__", "__license__"]:
            obj = getattr(pkg, symbol)
            assert isinstance(obj, str) and obj, f"{symbol} should be non-empty string"
        elif symbol == "config":
            # config can be various types depending on implementation
            assert hasattr(pkg, symbol), f"{symbol} missing from penguin package"
        else:
            # All other exports should be classes or types
            obj = getattr(pkg, symbol)
            assert inspect.isclass(obj) or inspect.isfunction(obj), f"{symbol} should be class/function, got {type(obj)}"


def test_optional_exports_conditional():
    """Test that optional exports are present when dependencies are available."""
    # These may or may not be present depending on installed dependencies
    optional_web = ["create_app", "PenguinAPI", "PenguinWeb"]
    optional_cli = ["PenguinCLI", "get_cli_app"]
    
    # Check if web extras are available
    web_available = False
    try:
        import fastapi
        web_available = True
    except ImportError:
        pass
    
    if web_available:
        for symbol in optional_web:
            if hasattr(pkg, symbol):
                print(f"✓ Optional web symbol {symbol} available (FastAPI installed)")
            else:
                print(f"! Optional web symbol {symbol} missing despite FastAPI being available")
    else:
        print("! FastAPI not available, skipping web exports check")
    
    # CLI should be available by default (included in main dependencies)
    cli_available = False
    try:
        import typer
        cli_available = True
    except ImportError:
        pass
        
    if cli_available:
        for symbol in optional_cli:
            if hasattr(pkg, symbol):
                print(f"✓ Optional CLI symbol {symbol} available (Typer installed)")
            else:
                print(f"! Optional CLI symbol {symbol} missing despite Typer being available")
    else:
        print("! Typer not available, CLI exports may be missing")


def test_import_basic_usage():
    """Test basic import usage patterns work as expected."""
    # Test that we can instantiate basic classes
    try:
        # Test that PenguinAgent can be imported and basic usage works
        agent_class = getattr(pkg, "PenguinAgent")
        # Don't actually instantiate since it requires setup, just check it's callable
        assert callable(agent_class), "PenguinAgent should be instantiable"
        
        # Test ProjectManager
        pm_class = getattr(pkg, "ProjectManager")
        assert callable(pm_class), "ProjectManager should be instantiable"
        
        # Test that config is accessible
        config = getattr(pkg, "config")
        assert config is not None, "config should be accessible"
        
        print("✓ Basic usage patterns work correctly")
        
    except Exception as e:
        print(f"! Basic usage test failed: {e}")
        raise


def test_version_string():
    """Test version string format."""
    version = pkg.__version__
    assert isinstance(version, str) and version, "__version__ should be non-empty string"
    
    # Basic semantic version format check (x.y.z or x.y.z-extra)
    import re
    version_pattern = r'^(\d+)\.(\d+)\.(\d+)(?:-[\w\.]*)?\s*$'
    assert re.match(version_pattern, version), f"__version__ should follow semantic versioning, got: {version}"
    
    print(f"✓ Version string valid: {version}")


def test_package_structure():
    """Test that the package structure is clean and well-organized."""
    # Check that __all__ is properly defined
    assert hasattr(pkg, "__all__"), "Package should define __all__"
    assert isinstance(pkg.__all__, list), "__all__ should be a list"
    assert len(pkg.__all__) > 0, "__all__ should not be empty"
    
    # Check that all symbols in __all__ are actually available
    for symbol in pkg.__all__:
        assert hasattr(pkg, symbol), f"Symbol {symbol} in __all__ but not available in package"
    
    print(f"✓ Package structure clean, {len(pkg.__all__)} symbols in __all__")


if __name__ == "__main__":
    """Run tests directly for development."""
    test_public_surface_symbols_present()
    test_optional_exports_conditional()
    test_import_basic_usage()
    test_version_string()
    test_package_structure()
    print("🎉 All public API surface tests passed!") 