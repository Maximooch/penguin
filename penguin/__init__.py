"""Penguin AI Assistant - A modular, extensible AI coding agent.

Penguin is a comprehensive AI assistant for software development, featuring:
- Agent-based task execution with memory and tool use
- Local project and task management 
- Web API and CLI interfaces
- Extensible tool ecosystem
- Multiple LLM provider support via LiteLLM

Example Usage:
    ```python
    from penguin import PenguinAgent, PenguinCore, PenguinClient, create_client
    
    # Simple agent usage
    agent = PenguinAgent()
    result = await agent.chat("Help me analyze this code")
    
    # High-level client usage (recommended)
    async with create_client() as client:
        # Basic chat
        response = await client.chat("Help me optimize this code")
        
        # Checkpoint workflow
        checkpoint = await client.create_checkpoint("Before optimization")
        await client.rollback_to_checkpoint(checkpoint)
        
        # Model management
        models = await client.list_models()
        await client.switch_model("anthropic/claude-3-sonnet-20240229")
        
        # Task execution
        result = await client.execute_task("Create a web scraper")
    
    # Full core usage for advanced scenarios
    core = PenguinCore()
    await core.initialize()
    
    # Enhanced task execution
    response = await core.run_task("Create a simple web server")
    
    # System diagnostics
    info = core.get_system_info()
    status = core.get_system_status()
    ```
"""

import os
import sys

# Add package directory to Python path
package_dir = os.path.dirname(os.path.abspath(__file__))
if package_dir not in sys.path:
    sys.path.insert(0, package_dir)

# Core exports - main public API
from .core import PenguinCore
from .config import config
from .engine import Engine, EngineSettings

# ---------------------------------------------------------------------------
# Agent exports – simplified high-level wrapper
# ---------------------------------------------------------------------------

import warnings

# The canonical package layout places ``penguin.agent`` as a *sibling* package
# of this sub-package (``penguin.penguin``).  A simple relative import is all
# that is required – tinkering with ``sys.path`` is both fragile and can mask
# genuine packaging errors.

try:
    # NOTE: ``from ..agent`` resolves to the top-level ``penguin.agent`` because
    # ``penguin.penguin`` lives one level below the root package.
    from ..agent import PenguinAgent  # type: ignore
except ImportError as exc:  # pragma: no cover – only trips in broken installs
    # Emit a *single* runtime warning instead of writing directly to stderr so
    # that callers retain full control over visibility (e.g. ``-W error``).
    warnings.warn(
        "PenguinAgent could not be imported – the agent module is missing. "
        "Most high-level conveniences will be unavailable.\n"
        f"Underlying error: {exc}",
        category=ImportWarning,
        stacklevel=2,
    )

    class PenguinAgent:  # pylint: disable=too-few-public-methods
        """Placeholder that raises a helpful error when instantiated."""

        def __init__(self, *_, **__):
            raise ImportError(
                "PenguinAgent is unavailable – the 'penguin.agent' sub-package "
                "could not be imported. Please check your installation or "
                "ensure optional dependencies are installed."
            )

# Project management exports
from .project import ProjectManager, Project, Task

# Checkpoint management exports
try:
    from .system.checkpoint_manager import CheckpointManager, CheckpointConfig, CheckpointType, CheckpointMetadata
    _checkpoint_exports = ["CheckpointManager", "CheckpointConfig", "CheckpointType", "CheckpointMetadata"]
except ImportError:
    _checkpoint_exports = []

# Model configuration exports
try:
    from .llm.model_config import ModelConfig
    _model_exports = ["ModelConfig"]
except ImportError:
    _model_exports = []

# System diagnostics exports
try:
    from .system.conversation_manager import ConversationManager
    from .system.state import Session, Message, MessageCategory
    _system_exports = ["ConversationManager", "Session", "Message", "MessageCategory"]
except ImportError:
    _system_exports = []

# API client exports
try:
    from .api_client import PenguinClient, ChatOptions, TaskOptions, CheckpointInfo, ModelInfo, create_client
    _api_client_exports = ["PenguinClient", "ChatOptions", "TaskOptions", "CheckpointInfo", "ModelInfo", "create_client"]
except ImportError:
    _api_client_exports = []

# Version info
__version__ = "0.3.2.1"
__author__ = "Maximus Putnam"
__email__ = "MaximusPutnam@gmail.com"
__license__ = "AGPL-3.0-or-later"

# Public API surface - this is the contract we'll maintain
__all__ = [
    # Core classes
    "PenguinCore",
    "PenguinAgent", 
    "Engine",
    "EngineSettings",
    
    # Project management
    "ProjectManager",
    "Project", 
    "Task",
    
    # Configuration
    "config",
    
    # Version info
    "__version__",
    "__author__",
    "__email__",
    "__license__",
]

# Add conditional exports to __all__
__all__.extend(_checkpoint_exports)
__all__.extend(_model_exports)
__all__.extend(_system_exports)
__all__.extend(_api_client_exports)

# Optional exports that require extra dependencies
def _get_optional_exports():
    """Get optional exports based on available dependencies."""
    optional = {}
    
    # Web API exports (require fastapi)
    try:
        from .web import create_app, PenguinAPI, PenguinWeb
        optional.update({
            "create_app": create_app,
            "PenguinAPI": PenguinAPI,
            "PenguinWeb": PenguinWeb,
        })
    except ImportError:
        pass
    
    # CLI exports (require typer - but included by default now)
    try:
        from .cli import PenguinCLI, get_cli_app
        optional.update({
            "PenguinCLI": PenguinCLI,
            "get_cli_app": get_cli_app,
        })
    except ImportError:
        pass
        
    return optional

# Extend public API with available optional components
_optional_exports = _get_optional_exports()
__all__.extend(_optional_exports.keys())
globals().update(_optional_exports)
