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

# Re-export all classes from the inner penguin package
try:
    from penguin.penguin import (
        EngineSettings, ProjectManager, Project, Task, config,
        __author__, __email__, __license__
    )
    _inner_exports = ["EngineSettings", "ProjectManager", "Project", "Task", "config", "__author__", "__email__", "__license__"]
except ImportError:
    _inner_exports = []

# Re-export conditional classes from inner package
try:
    from penguin.penguin import (
        CheckpointManager, CheckpointConfig, CheckpointType, CheckpointMetadata,
        ModelConfig,
        ConversationManager, Session, Message, MessageCategory,
        PenguinClient, ChatOptions, TaskOptions, CheckpointInfo, ModelInfo, create_client
    )
    _conditional_exports = [
        "CheckpointManager", "CheckpointConfig", "CheckpointType", "CheckpointMetadata",
        "ModelConfig",
        "ConversationManager", "Session", "Message", "MessageCategory", 
        "PenguinClient", "ChatOptions", "TaskOptions", "CheckpointInfo", "ModelInfo", "create_client"
    ]
except ImportError:
    _conditional_exports = []

# Re-export optional web/CLI classes from inner package
try:
    from penguin.penguin import create_app, PenguinAPI, PenguinWeb, PenguinCLI, get_cli_app
    _web_exports = ["create_app", "PenguinAPI", "PenguinWeb", "PenguinCLI", "get_cli_app"]
except ImportError:
    _web_exports = []

# Version helper - prefer inner package version over installed package version
try:
    from penguin.penguin import __version__
except ImportError:
    # Fallback to installed package version
    try:
        __version__ = version("penguin-ai")
    except PackageNotFoundError:  # Local dev mode
        __version__ = "0.1.2-dev"

__all__ = [
    "Engine",
    "PenguinAgent", 
    "PenguinAgentAsync",
    "PenguinCore",
    "ToolManager",
    "__version__",
]

# Add all successfully imported classes to __all__
__all__.extend(_inner_exports)
__all__.extend(_conditional_exports)
__all__.extend(_web_exports)
