
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from pathlib import Path

@dataclass
class PenguinConfig:
    """Centralized configuration for Penguin."""
    model: str
    provider: str
    api_base: str
    workspace_path: Path
    diagnostics_enabled: bool = True
    system