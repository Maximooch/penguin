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

# Project management exports - lazy load to avoid import overhead
# from .project import ProjectManager, Project, Task

# Checkpoint management exports - lazy load
_checkpoint_exports = ["CheckpointManager", "CheckpointConfig", "CheckpointType", "CheckpointMetadata"]

# Model configuration exports - lazy load  
_model_exports = ["ModelConfig"]

# System diagnostics exports - lazy load
_system_exports = ["ConversationManager", "Session", "Message", "MessageCategory"]

# API client exports - lazy load
_api_client_exports = ["PenguinClient", "ChatOptions", "TaskOptions", "CheckpointInfo", "ModelInfo", "create_client"]

# Version info
__version__ = "0.3.3.3.post1"
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
# Don't load optional exports at import time - use lazy loading instead
_optional_exports = {}

def __getattr__(name):
    """Lazy loading for optional exports to avoid import overhead."""
    if name in _optional_exports:
        return _optional_exports[name]
    
    # Try to load project management exports
    if name in ['ProjectManager', 'Project', 'Task']:
        try:
            from .project import ProjectManager, Project, Task
            _optional_exports.update({
                "ProjectManager": ProjectManager,
                "Project": Project,
                "Task": Task,
            })
            if name in _optional_exports:
                return _optional_exports[name]
        except ImportError:
            pass
    
    # Try to load checkpoint management exports
    if name in _checkpoint_exports:
        try:
            from .system.checkpoint_manager import CheckpointManager, CheckpointConfig, CheckpointType, CheckpointMetadata
            _optional_exports.update({
                "CheckpointManager": CheckpointManager,
                "CheckpointConfig": CheckpointConfig,
                "CheckpointType": CheckpointType,
                "CheckpointMetadata": CheckpointMetadata,
            })
            if name in _optional_exports:
                return _optional_exports[name]
        except ImportError:
            pass
    
    # Try to load model configuration exports
    if name in _model_exports:
        try:
            from .llm.model_config import ModelConfig
            _optional_exports.update({
                "ModelConfig": ModelConfig,
            })
            if name in _optional_exports:
                return _optional_exports[name]
        except ImportError:
            pass
    
    # Try to load system diagnostics exports
    if name in _system_exports:
        try:
            from .system.conversation_manager import ConversationManager
            from .system.state import Session, Message, MessageCategory
            _optional_exports.update({
                "ConversationManager": ConversationManager,
                "Session": Session,
                "Message": Message,
                "MessageCategory": MessageCategory,
            })
            if name in _optional_exports:
                return _optional_exports[name]
        except ImportError:
            pass
    
    # Try to load API client exports
    if name in _api_client_exports:
        try:
            from .api_client import PenguinClient, ChatOptions, TaskOptions, CheckpointInfo, ModelInfo, create_client
            _optional_exports.update({
                "PenguinClient": PenguinClient,
                "ChatOptions": ChatOptions,
                "TaskOptions": TaskOptions,
                "CheckpointInfo": CheckpointInfo,
                "ModelInfo": ModelInfo,
                "create_client": create_client,
            })
            if name in _optional_exports:
                return _optional_exports[name]
        except ImportError:
            pass
    
    # Try to load CLI exports
    if name in ['PenguinCLI', 'get_cli_app']:
        try:
            from .cli import PenguinCLI, get_cli_app
            _optional_exports.update({
                "PenguinCLI": PenguinCLI,
                "get_cli_app": get_cli_app,
            })
            if name in _optional_exports:
                return _optional_exports[name]
        except ImportError:
            pass
    
    # Try to load web exports  
    if name in ['create_app', 'PenguinAPI', 'PenguinWeb']:
        try:
            from .web import create_app, PenguinAPI, PenguinWeb
            _optional_exports.update({
                "create_app": create_app,
                "PenguinAPI": PenguinAPI,
                "PenguinWeb": PenguinWeb,
            })
            if name in _optional_exports:
                return _optional_exports[name]
        except ImportError:
            pass
    
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
