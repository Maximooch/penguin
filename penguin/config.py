import os
from dataclasses import dataclass, field
from pathlib import Path

# import logging
from typing import Any, Dict, Optional

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
    """Load configuration from config.yml"""
    config_path = Path(__file__).parent.parent / "config.yml"
    try:
        with open(config_path) as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        return {}

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

# Get user's actual home directory
USER_HOME = Path(os.path.expanduser("~"))
WORKSPACE_PATH = USER_HOME / "Documents" / "code" / "penguin_workspace"

# Add explicit creation with error handling
try:
    WORKSPACE_PATH.mkdir(parents=True, exist_ok=True)
except PermissionError as e:
    raise RuntimeError(
        f"Permission denied creating workspace at {WORKSPACE_PATH}. "
        "Try running as administrator or choose a different location."
    ) from e

# Move config loading before its first use
config = load_config()

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

print(f"Workspace path: {WORKSPACE_PATH}")  # This will help us confirm the correct path

# Set up logging
# logging.basicConfig(level=logging.DEBUG)
# logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# API Keys
# MODEL_API_KEY = os.environ.get("MODEL_API_KEY")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
PERPLEXITY_API_KEY = os.environ.get("PERPLEXITY_API_KEY")

# Constants
# CONTINUATION_EXIT_PHRASE = "AUTOMODE_COMPLETE"
# MAX_CONTINUATION_ITERATIONS = 100
TASK_COMPLETION_PHRASE = "TASK_COMPLETED"  # Single task completion
CONTINUOUS_COMPLETION_PHRASE = "CONTINUOUS_COMPLETED"  # End of continuous session
EMERGENCY_STOP_PHRASE = "EMERGENCY_STOP"  # Immediate termination needed
MAX_TASK_ITERATIONS = 100


def load_config():
    config_path = Path(__file__).parent.parent / "config.yml"
    # logger.debug(f"Attempting to load config from: {config_path}")
    try:
        with open(config_path) as config_file:
            config = yaml.safe_load(config_file)

            # Initialize diagnostics based on config
            if "diagnostics" in config:
                from penguin.utils.diagnostics import (
                    disable_diagnostics,
                    enable_diagnostics,
                )

                if not config["diagnostics"].get("enabled", False):
                    disable_diagnostics()
                else:
                    enable_diagnostics()

            return config
    except FileNotFoundError:
        # logger.error(f"Config file not found at {config_path}")
        return {}
    except yaml.YAMLError:
        # logger.error(f"Error parsing config file: {e}")
        return {}


# Default model configuration
DEFAULT_MODEL = os.getenv("PENGUIN_DEFAULT_MODEL", config["model"]["default"])
DEFAULT_PROVIDER = os.getenv("PENGUIN_DEFAULT_PROVIDER", config["model"]["provider"])
DEFAULT_API_BASE = os.getenv("PENGUIN_DEFAULT_API_BASE", config["api"]["base_url"])
USE_ASSISTANTS_API = config["model"].get("use_assistants_api", True)

# Add assistant-specific configuration
ASSISTANT_CONFIG = {
    "provider": config["model"].get("provider", "openai"),
    "enabled": config["model"].get("use_assistants_api", False),
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
        "use_assistants_api": config["model"].get("use_assistants_api", False),
        "assistant_config": get_assistant_config()
        if config["model"].get("use_assistants_api", False)
        else None,
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
class DiagnosticsConfig:
    enabled: bool = field(default=False)
    max_context_tokens: int = field(default=200000)
    log_to_file: bool = field(default=False)
    log_path: Optional[Path] = field(default=None)


@dataclass
class ModelConfig:
    default: str = "gpt-4"
    provider: str = "openai"
    use_assistants_api: bool = False


@dataclass
class APIConfig:
    base_url: Optional[str] = None


@dataclass
class Config:
    model: ModelConfig = field(default_factory=ModelConfig)
    api: APIConfig = field(default_factory=APIConfig)
    workspace_path: Path = field(default_factory=lambda: Path(WORKSPACE_PATH))
    temperature: float = field(default=0.7)
    max_tokens: Optional[int] = field(default=None)
    diagnostics: DiagnosticsConfig = field(default_factory=DiagnosticsConfig)
    workspace_dir: Path = field(default_factory=Path.cwd)
    cache_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("PENGUIN_CACHE_DIR", "~/.cache/penguin")
        ).expanduser()
    )

    @classmethod
    def load_config(cls, config_path: Optional[Path] = None) -> "Config":
        """Load configuration from config.yml"""
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config.yml"

        try:
            with open(config_path) as f:
                config_data = yaml.safe_load(f)

            # Load diagnostics config
            diagnostics_config = DiagnosticsConfig(
                enabled=config_data.get("diagnostics", {}).get("enabled", False),
                max_context_tokens=config_data.get("diagnostics", {}).get(
                    "max_context_tokens", 200000
                ),
            )

            # Initialize diagnostics based on config
            if not diagnostics_config.enabled:
                from utils.diagnostics import disable_diagnostics

                disable_diagnostics()

            return cls(
                model=ModelConfig(
                    default=config_data.get("model", {}).get("default", "gpt-4"),
                    provider=config_data.get("model", {}).get("provider", "openai"),
                    use_assistants_api=config_data.get("model", {}).get(
                        "use_assistants_api", False
                    ),
                ),
                api=APIConfig(base_url=config_data.get("api", {}).get("base_url")),
                workspace_path=Path(WORKSPACE_PATH),
                temperature=config_data.get("temperature", 0.7),
                max_tokens=config_data.get("max_tokens"),
                diagnostics=diagnostics_config,
            )

        except (FileNotFoundError, yaml.YAMLError):
            return cls()  # Return default config if file not found or invalid

    def to_dict(self) -> Dict[str, Any]:
        if not self.model.default:
            raise ValueError("model_name must be specified")

        return {
            "model_name": self.model.default,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "diagnostics": {
                "enabled": self.diagnostics.enabled,
                "max_context_tokens": self.diagnostics.max_context_tokens,
                "log_to_file": self.diagnostics.log_to_file,
                "log_path": str(self.diagnostics.log_path)
                if self.diagnostics.log_path
                else None,
            },
            "workspace_dir": str(self.workspace_dir),
            "cache_dir": str(self.cache_dir),
        }


# Add to existing config.py
CONVERSATIONS_PATH = os.path.join(WORKSPACE_PATH, "conversations")
os.makedirs(CONVERSATIONS_PATH, exist_ok=True)

# Add conversation-specific configuration
CONVERSATION_CONFIG = {
    "max_history": 1000000,  # Maximum number of messages to keep in history
    "auto_save": True,  # Automatically save conversations
    "save_format": "json",  # Format to save conversations in
}

# Add after loading config
# print("Loaded DEEPSEEK_API_KEY exists:", os.getenv("DEEPSEEK_API_KEY") is not None)  # Debug check
