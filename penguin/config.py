import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler

logger = logging.getLogger(__name__)

# import logging
from typing import Any, Dict, Optional, Literal, List

import yaml  # type: ignore
from dotenv import load_dotenv  # type: ignore

# LinkAI Workspace Configuration
# LINKAI_WORKSPACE_ID = os.getenv('LINKAI_WORKSPACE_ID')
# LINKAI_API_KEY = os.getenv('LINKAI_API_KEY')

def get_project_root() -> Path:
    """Get the absolute path to the project root."""
    # If installed in site-packages
    if 'site-packages' in __file__:
        # Use environment variable or default to user's home directory
        return Path(os.getenv('PENGUIN_ROOT', Path.home() / '.penguin'))
    
    # If running from source
    return Path(__file__).parent.parent

def load_config():
    """Load configuration by merging multiple locations with clear precedence.

    Precedence (lowest → highest):
      1. Package default (penguin/penguin/config.yml)
      2. Development repo default (repo_root/penguin/config.yml)
      3. User config (~/.config/penguin/config.yml or %APPDATA%/penguin/config.yml)
      4. Project config (<project_root>/.penguin/config.yml)
      5. Project local overrides (<project_root>/.penguin/settings.local.yml)
      6. Explicit override via PENGUIN_CONFIG_PATH (highest single-file override)

    Note: Enterprise-managed policy layer can be added above these in future.
    """

    def deep_merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        for key, value in (override or {}).items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                base[key] = deep_merge_dicts(dict(base.get(key, {})), value)
            else:
                base[key] = value
        return base

    # 0) Start with empty config
    merged: Dict[str, Any] = {}

    # 1) Package default
    package_config_path = Path(__file__).parent / "config.yml"
    try:
        if package_config_path.exists():
            with open(package_config_path) as f:
                merged = deep_merge_dicts(merged, yaml.safe_load(f) or {})
                logger.debug(f"Loaded package default config: {package_config_path}")
    except Exception as e:
        logger.warning(f"Error loading package default config {package_config_path}: {e}")

    # 2) Development repo default (if running from source)
    try:
        project_root = get_project_root()
        if not str(project_root).endswith('.penguin'):
            dev_config_path = project_root / "penguin" / "config.yml"
            if dev_config_path.exists():
                with open(dev_config_path) as f:
                    merged = deep_merge_dicts(merged, yaml.safe_load(f) or {})
                    logger.debug(f"Loaded dev repo config: {dev_config_path}")
    except Exception:
        pass

    # 3) User config
    if os.name == 'posix':  # Linux/macOS
        config_base = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
        user_config_path = config_base / "penguin" / "config.yml"
    else:  # Windows
        config_base = Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming'))
        user_config_path = config_base / "penguin" / "config.yml"
    try:
        if user_config_path.exists():
            with open(user_config_path) as f:
                merged = deep_merge_dicts(merged, yaml.safe_load(f) or {})
                logger.debug(f"Loaded user config: {user_config_path}")
    except Exception as e:
        logger.warning(f"Error loading user config {user_config_path}: {e}")

    # 4) Project config + local overrides
    def find_git_root(start_path: Path) -> Optional[Path]:
        path = start_path
        while True:
            if (path / '.git').exists():
                return path
            if path.parent == path:
                return None
            path = path.parent

    try:
        start_dir = Path(os.environ.get('PENGUIN_CWD', os.getcwd())).resolve()
    except Exception:
        start_dir = Path.cwd().resolve()

    git_root = find_git_root(start_dir)
    project_root_for_config = git_root or start_dir
    project_config_dir = project_root_for_config / '.penguin'
    project_config_path = project_config_dir / 'config.yml'
    project_local_path = project_config_dir / 'settings.local.yml'

    try:
        if project_config_path.exists():
            with open(project_config_path) as f:
                merged = deep_merge_dicts(merged, yaml.safe_load(f) or {})
                logger.debug(f"Loaded project config: {project_config_path}")
    except Exception as e:
        logger.warning(f"Error loading project config {project_config_path}: {e}")

    try:
        if project_local_path.exists():
            with open(project_local_path) as f:
                merged = deep_merge_dicts(merged, yaml.safe_load(f) or {})
                logger.debug(f"Loaded project local overrides: {project_local_path}")
    except Exception as e:
        logger.warning(f"Error loading project local settings {project_local_path}: {e}")

    # 5) Explicit override (highest single-file override)
    try:
        if os.getenv('PENGUIN_CONFIG_PATH'):
            override_path = Path(os.getenv('PENGUIN_CONFIG_PATH'))
            if override_path.exists():
                with open(override_path) as f:
                    merged = deep_merge_dicts(merged, yaml.safe_load(f) or {})
                    logger.debug(f"Loaded override config: {override_path}")
    except Exception as e:
        logger.warning(f"Error loading override config via PENGUIN_CONFIG_PATH: {e}")

    # If still empty, try setup wizard (skip in non-interactive/CI)
    if not merged:
        # Detect CI/non-interactive environments to avoid prompting
        non_interactive = (
            os.environ.get("CI", "").lower() == "true"
            or os.environ.get("GITHUB_ACTIONS", "").lower() == "true"
            or os.environ.get("PENGUIN_NO_SETUP", "") == "1"
            or not sys.stdin.isatty()
        )
        if non_interactive:
            logger.debug("Non-interactive environment detected; skipping setup wizard and using defaults")
            logger.debug("No config file found, using defaults")
            return {}

        # New guard: do not run setup wizard during import unless explicitly enabled.
        # This prevents blocking behaviors when penguin is imported by standalone scripts.
        # CLI entry points can opt-in by setting PENGUIN_SETUP_ON_IMPORT=1 before import.
        if os.environ.get("PENGUIN_SETUP_ON_IMPORT", "").lower() != "1":
            logger.debug("Setup wizard disabled on import (PENGUIN_SETUP_ON_IMPORT not set). Using defaults")
            return {}

        try:
            from penguin.setup.wizard import check_first_run, run_setup_wizard_sync
            if check_first_run():
                logger.info("No user config detected. Launching setup wizard…")
                result = run_setup_wizard_sync()
                if isinstance(result, dict) and result and not result.get("error"):
                    return result
        except Exception as e:
            logger.debug(f"Setup wizard not available or failed to run: {e}")
        logger.debug("No config file found, using defaults")
        return {}

    return merged

# -------------------------
# Config helper utilities
# -------------------------

def _find_git_root(start_path: Path) -> Optional[Path]:
    path = start_path
    while True:
        if (path / '.git').exists():
            return path
        if path.parent == path:
            return None
        path = path.parent

def get_user_config_path() -> Path:
    if os.name == 'posix':
        base = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
    else:
        base = Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming'))
    return base / 'penguin' / 'config.yml'

def get_project_config_paths(cwd_override: Optional[str] = None) -> Dict[str, Path]:
    try:
        start_dir = Path(cwd_override or os.environ.get('PENGUIN_CWD') or os.getcwd()).resolve()
    except Exception:
        start_dir = Path.cwd().resolve()
    git_root = _find_git_root(start_dir)
    project_root = git_root or start_dir
    cfg_dir = project_root / '.penguin'
    return {
        'project_root': project_root,
        'dir': cfg_dir,
        'project': cfg_dir / 'config.yml',
        'local': cfg_dir / 'settings.local.yml',
    }

def _ensure_parent_dir(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

def _read_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, 'r') as f:
            data = yaml.safe_load(f) or {}
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _write_yaml(path: Path, data: Dict[str, Any]) -> None:
    _ensure_parent_dir(path)
    with open(path, 'w') as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
    # Auto-gitignore local settings in .penguin/.gitignore
    try:
        if path.name == 'settings.local.yml':
            gitignore = path.parent / '.gitignore'
            _ensure_parent_dir(gitignore)
            line = 'settings.local.yml\n'
            if gitignore.exists():
                existing = gitignore.read_text(encoding='utf-8')
                if 'settings.local.yml' not in existing:
                    with open(gitignore, 'a', encoding='utf-8') as gf:
                        gf.write(line)
            else:
                with open(gitignore, 'w', encoding='utf-8') as gf:
                    gf.write(line)
    except Exception:
        pass

def _set_nested(config_dict: Dict[str, Any], key_path: str, value: Any) -> None:
    parts = [p for p in key_path.split('.') if p]
    node = config_dict
    for p in parts[:-1]:
        if p not in node or not isinstance(node[p], dict):
            node[p] = {}
        node = node[p]
    node[parts[-1]] = value

def _get_nested(config_dict: Dict[str, Any], key_path: str, default=None):
    parts = [p for p in key_path.split('.') if p]
    node = config_dict
    for p in parts:
        if not isinstance(node, dict) or p not in node:
            return default
        node = node[p]
    return node

def set_config_value(key: str, value: Any, scope: str = 'project', cwd_override: Optional[str] = None, list_op: Optional[str] = None) -> Path:
    """Set or modify a config value in the selected scope.

    scope: 'project' (default) writes to .penguin/settings.local.yml;
           'global' writes to user config (~/.config/penguin/config.yml).
    list_op: 'add' | 'remove' for list manipulation.
    Returns the path written.
    """
    if scope not in ('project', 'global'):
        raise ValueError("scope must be 'project' or 'global'")

    if scope == 'global':
        target_path = get_user_config_path()
    else:
        paths = get_project_config_paths(cwd_override)
        target_path = paths['local']

    data = _read_yaml(target_path)
    current = _get_nested(data, key, None)

    if list_op:
        lst = current if isinstance(current, list) else ([] if current in (None, '') else [current])
        if list_op == 'add':
            if value not in lst:
                lst.append(value)
        elif list_op == 'remove':
            lst = [x for x in lst if x != value]
        else:
            raise ValueError("list_op must be 'add' or 'remove'")
        _set_nested(data, key, lst)
    else:
        _set_nested(data, key, value)

    _write_yaml(target_path, data)
    return target_path

def get_config_value(key: str, default=None, cwd_override: Optional[str] = None):
    cfg = load_config()
    return _get_nested(cfg, key, default)

def init_diagnostics(config_data: dict):
    """Initialize diagnostics based on configuration. Call this after config is loaded."""
    if "diagnostics" in config_data:
        try:
            from penguin.utils.diagnostics import (
                disable_diagnostics,
                enable_diagnostics,
            )

            if not config_data["diagnostics"].get("enabled", False):
                disable_diagnostics()
            else:
                enable_diagnostics()
        except ImportError as e:
            # Only show warning if diagnostics is explicitly enabled
            if config_data["diagnostics"].get("enabled", False):
                logger.warning(f"Could not import diagnostics module: {e}")
            # Continue without diagnostics

def get_workspace_root() -> Path:
    """Get the workspace root directory."""
    # Load config
    config_data = load_config()
    
    # Priority order:
    # 1. Environment variable
    # 2. Config file
    # 3. Default location
    workspace_root = os.getenv(
        'PENGUIN_WORKSPACE',
        config_data.get('workspace', {}).get('path', '~/penguin_workspace')
    )
    
    return Path(workspace_root).expanduser()

# Base paths
PROJECT_ROOT = get_project_root()

# Load config first (without initializing diagnostics yet)
config = load_config()

# Use workspace path from config.yml (respecting environment variable and config file)
WORKSPACE_PATH = get_workspace_root()

# Add explicit creation with better error handling
try:
    WORKSPACE_PATH.mkdir(parents=True, exist_ok=True)
except PermissionError as e:
    # Try to use a fallback workspace in user's home directory
    fallback_path = Path.home() / "penguin_workspace"
    logger.warning(f"Permission denied creating workspace at {WORKSPACE_PATH}. Using fallback: {fallback_path}")
    try:
        fallback_path.mkdir(parents=True, exist_ok=True)
        WORKSPACE_PATH = fallback_path
    except PermissionError:
        raise RuntimeError(
            f"Permission denied creating workspace at {WORKSPACE_PATH} and fallback {fallback_path}. "
            "Try setting PENGUIN_WORKSPACE environment variable to a writable location."
        ) from e
except FileNotFoundError as e:
    # This can happen if the parent directory doesn't exist and can't be created
    fallback_path = Path.home() / "penguin_workspace" 
    logger.warning(f"Cannot create workspace at {WORKSPACE_PATH} (path not found). Using fallback: {fallback_path}")
    try:
        fallback_path.mkdir(parents=True, exist_ok=True)
        WORKSPACE_PATH = fallback_path
    except Exception:
        raise RuntimeError(
            f"Cannot create workspace at {WORKSPACE_PATH} or fallback {fallback_path}. "
            "Try setting PENGUIN_WORKSPACE environment variable to a valid location."
        ) from e

# Create configured subdirectories
for subdir in config.get('workspace', {}).get('create_dirs', [
    'conversations',
    'memory_db',
    'logs'
]):
    (WORKSPACE_PATH / subdir).mkdir(exist_ok=True)

# Update config with resolved paths
config['paths'] = {
    'workspace': str(WORKSPACE_PATH),
    'conversations': str(WORKSPACE_PATH / 'conversations'),
    'memory_db': str(WORKSPACE_PATH / 'memory_db'),
    'logs': str(WORKSPACE_PATH / 'logs'),
}

def substitute_path_variables(obj, paths):
    """Simple template substitution for ${paths.*} variables"""
    if isinstance(obj, str):
        for key, value in paths.items():
            obj = obj.replace(f"${{paths.{key}}}", value)
        return obj
    elif isinstance(obj, dict):
        return {k: substitute_path_variables(v, paths) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [substitute_path_variables(item, paths) for item in obj]
    else:
        return obj

# Substitute path variables in the entire config
config = substitute_path_variables(config, config['paths'])

# Safe access to common sections
_MODEL = config.get('model', {}) if isinstance(config.get('model'), dict) else {}
_API = config.get('api', {}) if isinstance(config.get('api'), dict) else {}

# Now that WORKSPACE_PATH is defined and paths resolved, initialize diagnostics
init_diagnostics(config)

# Avoid noisy stdout during normal startup; log at DEBUG level instead.
logger.debug(f"Workspace path: {WORKSPACE_PATH}")

# Set up logging
# logging.basicConfig(level=logging.DEBUG)
# logger = logging.getLogger(__name__)

# Load environment variables from user-level and project .env files
# 1) User-level: ~/.config/penguin/.env (or APPDATA equivalent) – provides persistent keys
try:
    if os.name == 'posix':
        user_env_dir = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'penguin'
    else:
        user_env_dir = Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming')) / 'penguin'
    user_env_path = user_env_dir / '.env'
    if user_env_path.exists():
        load_dotenv(dotenv_path=str(user_env_path), override=False)
except Exception:
    # Non-fatal if user-level .env loading fails
    pass

# 2) Project-level: nearest .env up the CWD chain – overrides user-level values
load_dotenv(override=True)

# API Keys
# MODEL_API_KEY = os.environ.get("MODEL_API_KEY")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
PERPLEXITY_API_KEY = os.environ.get("PERPLEXITY_API_KEY")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")

# GitHub App Configuration
GITHUB_APP_ID = os.environ.get("GITHUB_APP_ID")
GITHUB_APP_PRIVATE_KEY_PATH = os.environ.get("GITHUB_APP_PRIVATE_KEY_PATH")
GITHUB_APP_INSTALLATION_ID = os.environ.get("GITHUB_APP_INSTALLATION_ID")

# Constants
# CONTINUATION_EXIT_PHRASE = "AUTOMODE_COMPLETE"
# MAX_CONTINUATION_ITERATIONS = 100
TASK_COMPLETION_PHRASE = "TASK_COMPLETED"  # Single task completion
CONTINUOUS_COMPLETION_PHRASE = "CONTINUOUS_COMPLETED"  # End of continuous session
EMERGENCY_STOP_PHRASE = "EMERGENCY_STOP"  # Immediate termination needed
NEED_USER_CLARIFICATION_PHRASE = "NEED_USER_CLARIFICATION"  # Pause for user input
MAX_TASK_ITERATIONS = 100 # Check to see if it works fine with 100 messages before more


# Default model configuration (safe defaults for CI/non-interactive)
DEFAULT_MODEL = os.getenv("PENGUIN_DEFAULT_MODEL", _MODEL.get("default")) or "openai/gpt-5"
DEFAULT_PROVIDER = os.getenv("PENGUIN_DEFAULT_PROVIDER", _MODEL.get("provider", "openai"))
DEFAULT_API_BASE = os.getenv("PENGUIN_DEFAULT_API_BASE", _API.get("base_url"))
USE_ASSISTANTS_API = _MODEL.get("use_assistants_api", True)

# Project Management Configuration
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", config.get("project", {}).get("github_repository"))

# Add assistant-specific configuration
ASSISTANT_CONFIG = {
    "provider": _MODEL.get("provider", "openai"),
    "enabled": _MODEL.get("use_assistants_api", False),
    "custom_llm_provider": "openai",  # Required by litellm
    "model_name_override": None,  # Optional override for assistant model name
}


def get_assistant_config() -> Dict[str, Any]:
    """Get the configuration for the Assistants API"""
    return {
        "provider": ASSISTANT_CONFIG["provider"],
        "enabled": ASSISTANT_CONFIG["enabled"],
        "custom_llm_provider": ASSISTANT_CONFIG["custom_llm_provider"],
        "model_name_override": ASSISTANT_CONFIG["model_name_override"],
    }


# Model-specific configurations
MODEL_CONFIGS = config.get("model_configs", {})


# Update the existing ModelConfig creation to include assistant config
def get_model_config(model_name: Optional[str] = None) -> Dict[str, Any]:
    """Get the configuration for a specific model"""
    model_name = model_name or DEFAULT_MODEL
    base_config = MODEL_CONFIGS.get(model_name, {})

    return {
        "model": model_name,
        "provider": base_config.get("provider", DEFAULT_PROVIDER),
        "api_base": base_config.get("api_base", DEFAULT_API_BASE),
        "max_tokens": base_config.get("max_tokens"),
        "temperature": base_config.get("temperature"),
        "use_assistants_api": _MODEL.get("use_assistants_api", False),
        "assistant_config": get_assistant_config() if _MODEL.get("use_assistants_api", False) else None,
    }


# Feature Flags
class FeatureFlags:
    DIAGNOSTICS_ENABLED = False


# Color Configuration
class Colors:
    USER_COLOR = "white"
    CLAUDE_COLOR = "blue"
    TOOL_COLOR = "yellow"
    RESULT_COLOR = "green"


# Configuration class
class Config:
    @classmethod
    def get(cls, key, default=None):
        return getattr(cls, key, default)

    @classmethod
    def set(cls, key, value):
        setattr(cls, key, value)

    @classmethod
    def enable_feature(cls, feature):
        setattr(FeatureFlags, feature, True)

    @classmethod
    def disable_feature(cls, feature):
        setattr(FeatureFlags, feature, False)

    @classmethod
    def is_feature_enabled(cls, feature):
        return getattr(FeatureFlags, feature, False)


# You can add more configuration settings here as needed


# Show tool output in the UI

# Show iteration messages in the UI.

# Show memory search results in the UI. ( I mean it is tool output, but it's a lot of output so we should have a flag for it )

#


@dataclass
class OutputConfig:
    prompt_style: str = field(default="steps_final")
    show_tool_results: bool = field(default=True)


@dataclass
class DiagnosticsConfig:
    enabled: bool = field(default=False)
    max_context_tokens: int = field(default=200000)
    log_to_file: bool = field(default=False)
    log_path: Optional[Path] = field(default=None)


@dataclass
class AgentModelSettings:
    """Model override declaration for an agent persona."""

    id: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    client_preference: Optional[str] = None
    api_base: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    streaming_enabled: Optional[bool] = None
    vision_enabled: Optional[bool] = None
    use_assistants_api: Optional[bool] = None
    reasoning: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentModelSettings":
        """Create settings from raw config dictionary."""

        return cls(
            id=data.get("id") or data.get("name"),
            model=data.get("model"),
            provider=data.get("provider"),
            client_preference=data.get("client_preference"),
            api_base=data.get("api_base"),
            temperature=data.get("temperature"),
            max_tokens=data.get("max_tokens"),
            streaming_enabled=data.get("streaming_enabled"),
            vision_enabled=data.get("vision_enabled"),
            use_assistants_api=data.get("use_assistants_api"),
            reasoning=dict(data.get("reasoning", {})),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a serialisable copy of the settings."""

        payload: Dict[str, Any] = {
            "id": self.id,
            "model": self.model,
            "provider": self.provider,
            "client_preference": self.client_preference,
            "api_base": self.api_base,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "streaming_enabled": self.streaming_enabled,
            "vision_enabled": self.vision_enabled,
            "use_assistants_api": self.use_assistants_api,
        }
        if self.reasoning:
            payload["reasoning"] = dict(self.reasoning)
        return {k: v for k, v in payload.items() if v is not None}


@dataclass
class AgentPersonaConfig:
    """Declarative configuration for a reusable agent persona."""

    name: str
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    model: Optional[AgentModelSettings] = None
    default_tools: Optional[List[str]] = None
    share_session_with: Optional[str] = None
    share_context_window_with: Optional[str] = None
    shared_cw_max_tokens: Optional[int] = None
    model_max_tokens: Optional[int] = None
    activate_by_default: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "AgentPersonaConfig":
        """Build a persona config from raw configuration data."""

        model_block = data.get("model") or {}
        model_settings = None
        if isinstance(model_block, dict) and model_block:
            model_settings = AgentModelSettings.from_dict(model_block)

        tools_block = data.get("default_tools")
        if tools_block is None:
            tools_block = data.get("tools")
        default_tools = list(tools_block) if isinstance(tools_block, list) else None

        return cls(
            name=name,
            description=data.get("description"),
            system_prompt=data.get("system_prompt"),
            model=model_settings,
            default_tools=default_tools,
            share_session_with=data.get("share_session_with"),
            share_context_window_with=data.get("share_context_window_with"),
            shared_cw_max_tokens=data.get("shared_cw_max_tokens"),
            model_max_tokens=data.get("model_max_tokens"),
            activate_by_default=bool(data.get("activate") or data.get("activate_by_default", False)),
            metadata=dict(data.get("metadata", {})),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a serialisable mapping representing the persona."""

        payload: Dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "default_tools": list(self.default_tools) if self.default_tools else None,
            "share_session_with": self.share_session_with,
            "share_context_window_with": self.share_context_window_with,
            "shared_cw_max_tokens": self.shared_cw_max_tokens,
            "model_max_tokens": self.model_max_tokens,
            "activate": self.activate_by_default,
            "metadata": dict(self.metadata) if self.metadata else None,
        }
        if self.model:
            payload["model"] = self.model.to_dict()
        return {k: v for k, v in payload.items() if v is not None}


@dataclass
class APIConfig:
    base_url: Optional[str] = None


@dataclass
class Config:
    # Use forward reference for type hint to avoid circular import
    model_config: Any = None  # Will be set in load_config
    api: APIConfig = field(default_factory=APIConfig)
    workspace_path: Path = field(default_factory=lambda: Path(WORKSPACE_PATH))
    temperature: float = field(default=0.7)
    max_tokens: Optional[int] = field(default=None)
    diagnostics: DiagnosticsConfig = field(default_factory=DiagnosticsConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    workspace_dir: Path = field(default_factory=Path.cwd)
    cache_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("PENGUIN_CACHE_DIR", "~/.cache/penguin")
        ).expanduser()
    )
    # Fast startup configuration
    fast_startup: bool = field(default=False)
    model_configs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    agent_personas: Dict[str, AgentPersonaConfig] = field(default_factory=dict)
    
    # Dictionary-like access to model settings
    @property
    def model(self) -> Dict[str, Any]:
        """
        Provide dictionary-like access to model settings.
        For compatibility with code expecting a dict-like interface.
        """
        if self.model_config is None:
            return {}
            
        result = {}
        # Common model parameters
        attrs = ["provider", "client_preference", "streaming_enabled", "api_base", 
                 "max_tokens", "temperature", "vision_enabled", "use_assistants_api"]
        
        for attr in attrs:
            if hasattr(self.model_config, attr):
                result[attr] = getattr(self.model_config, attr)
        
        # Add method for dictionary-like access
        def get(key, default=None):
            return result.get(key, default)
            
        result["get"] = get
        return result

    def __post_init__(self):
        # Initialize model_config if it's None
        if self.model_config is None:
            # Import inside the method to avoid circular imports
            from penguin.llm.model_config import ModelConfig as LLMModelConfig
            self.model_config = LLMModelConfig.from_env()
        if self.model_configs is None:
            self.model_configs = {}
        if self.agent_personas is None:
            self.agent_personas = {}
        if self.output is None:
            self.output = OutputConfig()

    @classmethod
    def load_config(cls, config_path: Optional[Path] = None) -> "Config":
        """Load effective Penguin config using the central resolver.

        This delegates to the top‑level load_config() in this module, which
        merges config from (in order): package defaults, dev repo defaults,
        user config (~/.config/penguin/config.yml), project overrides, and
        an explicit PENGUIN_CONFIG_PATH override. This avoids divergence
        between different config loading paths across the codebase.
        """
        # Import ModelConfig here to avoid circular imports
        from penguin.llm.model_config import ModelConfig as LLMModelConfig

        # Prefer the merged config resolver, unless an explicit file path was provided
        if config_path is None:
            config_data = load_config()
        else:
            try:
                with open(config_path) as f:
                    config_data = yaml.safe_load(f) or {}
            except (FileNotFoundError, yaml.YAMLError):
                config_data = {}

        if not isinstance(config_data, dict):
            config_data = {}

        if not config_data:
            logging.getLogger(__name__).warning(
                "No resolved config found. Falling back to environment defaults."
            )
            # Fall back to environment defaults
            default_llm_model_config = LLMModelConfig.from_env()
            return cls(model_config=default_llm_model_config)

        diagnostics_config = DiagnosticsConfig(
            enabled=config_data.get("diagnostics", {}).get("enabled", False),
            max_context_tokens=config_data.get("diagnostics", {}).get(
                "max_context_tokens", 400000 # TODO: Possible culprit. Make this a default value in the config.yml
            ),
            log_to_file=config_data.get("diagnostics", {}).get("log_to_file", False),
            log_path=Path(config_data["diagnostics"]["log_path"]) if config_data.get("diagnostics", {}).get("log_path") else None
        )

        output_settings = config_data.get("output", {})
        if not isinstance(output_settings, dict):
            output_settings = {}

        prompt_style_value = output_settings.get("prompt_style", "steps_final")
        if prompt_style_value is None:
            prompt_style_value = "steps_final"
        prompt_style = str(prompt_style_value).strip()
        if not prompt_style:
            prompt_style = "steps_final"

        show_tool_results_value = output_settings.get("show_tool_results", True)
        if isinstance(show_tool_results_value, str):
            show_tool_results = show_tool_results_value.strip().lower() in {"1", "true", "yes", "on"}
        else:
            show_tool_results = bool(show_tool_results_value)

        output_config = OutputConfig(
            prompt_style=prompt_style,
            show_tool_results=show_tool_results,
        )

        if diagnostics_config.enabled:
            log_level = logging.DEBUG if os.getenv("PENGUIN_DEBUG") else logging.INFO
            _configure_diagnostics_logging(diagnostics_config, log_level)
            logging.getLogger(__name__).info("Diagnostics enabled via config.yml.")
            
        # Initialize diagnostics using the loaded config
        init_diagnostics(config_data)

        # --- Determine Model Config --- #
        default_model_settings = config_data.get("model", {})
        # ENV VARS TAKE PRECEDENCE over config.yml for container deployments
        default_model_id = os.getenv("PENGUIN_DEFAULT_MODEL") or default_model_settings.get("default") or "anthropic/claude-3-5-sonnet-20240620"
        default_provider = os.getenv("PENGUIN_DEFAULT_PROVIDER") or default_model_settings.get("provider") or "anthropic"
        default_client_pref = os.getenv("PENGUIN_CLIENT_PREFERENCE") or default_model_settings.get("client_preference") or "litellm"

        model_configs_section = config_data.get("model_configs")
        if not isinstance(model_configs_section, dict):
            model_configs_section = {}

        # Use the new for_model() method to dynamically resolve model-specific configs
        llm_model_config = LLMModelConfig.for_model(
            model_name=default_model_id,
            provider=default_provider,
            client_preference=default_client_pref,
            model_configs=model_configs_section
        )

        # Resolve agent personas (Phase 1+ configuration surface)
        raw_personas = config_data.get("agents")
        if raw_personas is None:
            raw_personas = config_data.get("personas", {})
        agent_personas: Dict[str, AgentPersonaConfig] = {}
        if isinstance(raw_personas, dict):
            for persona_name, persona_config in raw_personas.items():
                if not isinstance(persona_config, dict):
                    logger.warning("Skipping persona '%s': expected a mapping, got %s", persona_name, type(persona_config).__name__)
                    continue
                try:
                    agent_personas[persona_name] = AgentPersonaConfig.from_dict(persona_name, persona_config)
                except Exception as exc:  # pragma: no cover - defensive, config errors should surface in logs
                    logger.warning("Failed to load agent persona '%s': %s", persona_name, exc)

        return cls(
            model_config=llm_model_config,
            api=APIConfig(base_url=config_data.get("api", {}).get("base_url")),
            workspace_path=Path(WORKSPACE_PATH), # WORKSPACE_PATH is already defined globally
            temperature=config_data.get("temperature", llm_model_config.temperature), # Use model temp if global not set
            max_tokens=config_data.get("max_tokens", llm_model_config.max_tokens), # Use model max_tokens if global not set
            diagnostics=diagnostics_config,
            output=output_config,
            fast_startup=config_data.get("performance", {}).get("fast_startup", False),
            model_configs=model_configs_section,
            agent_personas=agent_personas,
        )

    def to_dict(self) -> Dict[str, Any]:
        if not self.model_config.model:
            raise ValueError("model_name must be specified in the effective model config")

        return {
            "default_model_config": self.model_config.get_config(),
            "global_temperature": self.temperature,
            "global_max_tokens": self.max_tokens,
            "diagnostics": {
                "enabled": self.diagnostics.enabled,
                "max_context_tokens": self.diagnostics.max_context_tokens,
                "log_to_file": self.diagnostics.log_to_file,
                "log_path": str(self.diagnostics.log_path)
                if self.diagnostics.log_path
                else None,
            },
            "output": {
                "prompt_style": getattr(self.output, "prompt_style", "steps_final"),
                "show_tool_results": getattr(self.output, "show_tool_results", True),
            },
            "workspace_dir": str(self.workspace_dir),
            "cache_dir": str(self.cache_dir),
            "workspace_path": str(self.workspace_path),
            "model_configs": self.model_configs,
            "agent_personas": {name: persona.to_dict() for name, persona in self.agent_personas.items()},
        }


# Add to existing config.py
CONVERSATIONS_PATH = WORKSPACE_PATH / "conversations"
CONVERSATIONS_PATH.mkdir(exist_ok=True)

# Add conversation-specific configuration
CONVERSATION_CONFIG = {
    "max_history": 1000000,
    "auto_save": True,
    "save_format": "json",
}

# Add after loading config
# print("Loaded DEEPSEEK_API_KEY exists:", os.getenv("DEEPSEEK_API_KEY") is not None)  # Debug check

# class BrowserConfig:
#     preferred_browser: str = 'chromium'  # 'chrome' or 'chromium'
#     suppress_popups: bool = True

def _configure_diagnostics_logging(diagnostics_config: "DiagnosticsConfig", log_level: int) -> None:
    """Route diagnostics logs to a managed file instead of stdout."""
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Determine target log file
    if diagnostics_config.log_to_file and diagnostics_config.log_path:
        target_path = diagnostics_config.log_path
    else:
        log_dir = WORKSPACE_PATH / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        target_path = log_dir / "diagnostics.log"
        diagnostics_config.log_to_file = True
        diagnostics_config.log_path = target_path

    target_path.parent.mkdir(parents=True, exist_ok=True)

    handler_flag = "_penguin_diagnostics_handler"
    existing_handler = None
    for handler in list(root_logger.handlers):
        if getattr(handler, handler_flag, False):
            existing_handler = handler
            break

    if existing_handler:
        existing_path = Path(getattr(existing_handler, "baseFilename", ""))
        if existing_path != target_path:
            root_logger.removeHandler(existing_handler)
            existing_handler.close()
            existing_handler = None

    if not existing_handler:
        diagnostics_handler = RotatingFileHandler(
            target_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        diagnostics_handler.setLevel(log_level)
        diagnostics_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
        )
        setattr(diagnostics_handler, handler_flag, True)
        root_logger.addHandler(diagnostics_handler)

    # Ensure existing stdout/stderr handlers don't spam interactive sessions
    for handler in root_logger.handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.setLevel(max(handler.level, logging.WARNING))
