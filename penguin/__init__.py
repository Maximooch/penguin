"""Penguin AI Assistant - A modular, extensible AI coding agent.

Penguin is a comprehensive AI assistant for software development, featuring:
- Agent-based task execution with memory and tool use
- Local project and task management 
- Web API and CLI interfaces
- Extensible tool ecosystem
- Multiple LLM provider support via LiteLLM

Example Usage:
    ```python
    from penguin import PenguinAgent, PenguinCore
    
    # Simple agent usage
    agent = PenguinAgent()
    result = await agent.chat("Help me analyze this code")
    
    # Full core usage
    core = PenguinCore()
    await core.initialize()
    response = await core.run_task("Create a simple web server")
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

# Agent exports - simplified interface
try:
    # Agent is in the parent directory at same level as main penguin package
    import sys
    from pathlib import Path
    agent_path = Path(__file__).parent.parent / "agent"
    if str(agent_path) not in sys.path:
        sys.path.insert(0, str(agent_path))
    from penguin.agent import PenguinAgent
except ImportError:
    try:
        # Alternative: try importing directly without path manipulation
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from agent import PenguinAgent
    except ImportError:
        # Final fallback: create a placeholder
        class PenguinAgent:
            def __init__(self):
                raise ImportError("PenguinAgent not available - agent module not found")
        print("Warning: PenguinAgent not available - agent module not found")

# Project management exports
from .project import ProjectManager, Project, Task

# Version info
__version__ = "0.2.0"
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
