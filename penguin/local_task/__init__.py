from .manager import ProjectManager

__all__ = ["ProjectManager", "ProjectVisualizer"]

# Lazy load ProjectVisualizer to avoid matplotlib import at startup
def __getattr__(name):
    if name == "ProjectVisualizer":
        from .vis import ProjectVisualizer
        return ProjectVisualizer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
