"""Orchestration configuration and backend factory.

Provides configuration for orchestration backends and a factory function
to get the configured backend instance.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .backend import OrchestrationBackend

logger = logging.getLogger(__name__)


@dataclass
class TemporalConfig:
    """Configuration for Temporal backend."""
    
    address: str = "localhost:7233"
    namespace: str = "penguin"
    task_queue: str = "penguin-ituv"
    auto_start: bool = True  # Auto-start local Temporal server in dev mode
    
    # Timeouts (seconds)
    workflow_execution_timeout: int = 3600  # 1 hour
    workflow_run_timeout: int = 1800  # 30 minutes
    activity_start_to_close_timeout: int = 600  # 10 minutes
    
    # Retry policy
    max_retries: int = 3
    initial_interval_sec: int = 1
    max_interval_sec: int = 60
    backoff_coefficient: float = 2.0


@dataclass
class OrchestrationConfig:
    """Configuration for orchestration system."""
    
    # Backend selection: "native" or "temporal"
    backend: str = "native"
    
    # Storage path for workflow state
    storage_path: Optional[Path] = None
    
    # Temporal-specific config
    temporal: TemporalConfig = field(default_factory=TemporalConfig)
    
    # ITUV phase timeouts (seconds)
    phase_timeouts: Dict[str, int] = field(default_factory=lambda: {
        "implement": 600,
        "test": 300,
        "use": 180,
        "verify": 120,
    })
    
    # Default retry settings
    default_max_retries: int = 3
    default_retry_delay_sec: int = 5
    
    # Cleanup settings
    cleanup_completed_after_days: int = 30
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OrchestrationConfig":
        """Create config from dictionary (e.g., from config.yml)."""
        temporal_data = data.get("temporal", {})
        temporal_config = TemporalConfig(
            address=temporal_data.get("address", "localhost:7233"),
            namespace=temporal_data.get("namespace", "penguin"),
            task_queue=temporal_data.get("task_queue", "penguin-ituv"),
            auto_start=temporal_data.get("auto_start", True),
            workflow_execution_timeout=temporal_data.get("workflow_execution_timeout", 3600),
            workflow_run_timeout=temporal_data.get("workflow_run_timeout", 1800),
            activity_start_to_close_timeout=temporal_data.get("activity_start_to_close_timeout", 600),
            max_retries=temporal_data.get("max_retries", 3),
            initial_interval_sec=temporal_data.get("initial_interval_sec", 1),
            max_interval_sec=temporal_data.get("max_interval_sec", 60),
            backoff_coefficient=temporal_data.get("backoff_coefficient", 2.0),
        )
        
        storage_path = data.get("storage_path")
        if storage_path:
            storage_path = Path(storage_path)
        
        return cls(
            backend=data.get("backend", "native"),
            storage_path=storage_path,
            temporal=temporal_config,
            phase_timeouts=data.get("phase_timeouts", {
                "implement": 600,
                "test": 300,
                "use": 180,
                "verify": 120,
            }),
            default_max_retries=data.get("default_max_retries", 3),
            default_retry_delay_sec=data.get("default_retry_delay_sec", 5),
            cleanup_completed_after_days=data.get("cleanup_completed_after_days", 30),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "backend": self.backend,
            "storage_path": str(self.storage_path) if self.storage_path else None,
            "temporal": {
                "address": self.temporal.address,
                "namespace": self.temporal.namespace,
                "task_queue": self.temporal.task_queue,
                "auto_start": self.temporal.auto_start,
                "workflow_execution_timeout": self.temporal.workflow_execution_timeout,
                "workflow_run_timeout": self.temporal.workflow_run_timeout,
                "activity_start_to_close_timeout": self.temporal.activity_start_to_close_timeout,
                "max_retries": self.temporal.max_retries,
                "initial_interval_sec": self.temporal.initial_interval_sec,
                "max_interval_sec": self.temporal.max_interval_sec,
                "backoff_coefficient": self.temporal.backoff_coefficient,
            },
            "phase_timeouts": self.phase_timeouts,
            "default_max_retries": self.default_max_retries,
            "default_retry_delay_sec": self.default_retry_delay_sec,
            "cleanup_completed_after_days": self.cleanup_completed_after_days,
        }


# Global config instance (set by Penguin config system)
_config: Optional[OrchestrationConfig] = None
_backend: Optional["OrchestrationBackend"] = None


def set_config(config: OrchestrationConfig) -> None:
    """Set the global orchestration config."""
    global _config, _backend
    _config = config
    _backend = None  # Reset backend when config changes
    logger.info(f"Orchestration config set: backend={config.backend}")


def get_config() -> OrchestrationConfig:
    """Get the current orchestration config."""
    global _config
    if _config is None:
        _config = OrchestrationConfig()
        logger.debug("Using default orchestration config")
    return _config


def get_backend(
    config: Optional[OrchestrationConfig] = None,
    workspace_path: Optional[Path] = None,
) -> "OrchestrationBackend":
    """Get or create the orchestration backend.
    
    Args:
        config: Optional config override.
        workspace_path: Optional workspace path for storage.
        
    Returns:
        Configured OrchestrationBackend instance.
    """
    global _backend, _config
    
    if config is not None:
        _config = config
        _backend = None
    
    if _backend is not None:
        return _backend
    
    cfg = get_config()
    
    # Determine storage path
    storage_path = cfg.storage_path
    if storage_path is None and workspace_path:
        storage_path = workspace_path / "workflow_state.db"
    elif storage_path is None:
        storage_path = Path.cwd() / "workflow_state.db"
    
    if cfg.backend == "temporal":
        try:
            from .temporal import TemporalBackend
            _backend = TemporalBackend(cfg, storage_path)
            logger.info("Using Temporal orchestration backend")
        except ImportError as e:
            logger.warning(f"Temporal not available ({e}), falling back to native backend")
            from .native import NativeBackend
            _backend = NativeBackend(cfg, storage_path)
    else:
        from .native import NativeBackend
        _backend = NativeBackend(cfg, storage_path)
        logger.info("Using native orchestration backend")
    
    return _backend


def reset_backend() -> None:
    """Reset the backend instance (for testing)."""
    global _backend
    _backend = None

