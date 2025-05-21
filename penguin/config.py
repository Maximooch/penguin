import os
from dataclasses import dataclass, field
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# import logging
from typing import Any, Dict, Optional, Literal

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
    """Load configuration from config.yml in the same directory as this file."""
    config_path = Path(__file__).parent / "config.yml"
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)

            # Initialize diagnostics based on config
            if "diagnostics" in config:
                # Move import inside the function to avoid circular imports
                try:
                    from penguin.utils.diagnostics import (
                        disable_diagnostics,
                        enable_diagnostics,
                    )

                    if not config["diagnostics"].get("enabled", False):
                        disable_diagnostics()
                    else:
                        enable_diagnostics()
                except ImportError:
                    logger.warning("Could not import diagnostics module, skipping diagnostics setup")

            return config
    except FileNotFoundError:
        return {}
    except yaml.YAMLError:
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
WORKSPACE_PATH = USER_HOME / "Documents" / "code" / "Penguin" / "penguin_workspace"

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

# Avoid noisy stdout during normal startup; log at DEBUG level instead.
logger.debug(f"Workspace path: {WORKSPACE_PATH}")

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
NEED_USER_CLARIFICATION_PHRASE = "NEED_USER_CLARIFICATION"  # Pause for user input
MAX_TASK_ITERATIONS = 100 # Check to see if it works fine with 100 messages before more


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
    workspace_dir: Path = field(default_factory=Path.cwd)
    cache_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("PENGUIN_CACHE_DIR", "~/.cache/penguin")
        ).expanduser()
    )
    
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

    @classmethod
    def load_config(cls, config_path: Optional[Path] = None) -> "Config":
        """Load configuration from config.yml"""
        # Import ModelConfig here to avoid circular imports
        from penguin.llm.model_config import ModelConfig as LLMModelConfig
        
        if config_path is None:
            # Default to loading from the same directory as this config.py file
            config_path = Path(__file__).parent / "config.yml"
            
        try:
            with open(config_path) as f:
                config_data = yaml.safe_load(f)
        except (FileNotFoundError, yaml.YAMLError):
            config_data = {}

        if not config_data:
            logging.getLogger(__name__).warning("Configuration file not found or empty. Using default settings.")
            # If config fails to load, create a default ModelConfig using environment variables
            default_llm_model_config = LLMModelConfig.from_env()
            return cls(model_config=default_llm_model_config)

        diagnostics_config = DiagnosticsConfig(
            enabled=config_data.get("diagnostics", {}).get("enabled", False),
            max_context_tokens=config_data.get("diagnostics", {}).get(
                "max_context_tokens", 200000
            ),
            log_to_file=config_data.get("diagnostics", {}).get("log_to_file", False),
            log_path=Path(config_data["diagnostics"]["log_path"]) if config_data.get("diagnostics", {}).get("log_path") else None
        )

        if diagnostics_config.enabled:
            log_level = logging.DEBUG if os.getenv("PENGUIN_DEBUG") else logging.INFO
            log_kwargs = {"level": log_level, "format": '%(asctime)s - %(name)s - %(levelname)s - %(message)s'}
            if diagnostics_config.log_to_file and diagnostics_config.log_path:
                diagnostics_config.log_path.parent.mkdir(parents=True, exist_ok=True)
                log_kwargs["filename"] = str(diagnostics_config.log_path)
                log_kwargs["filemode"] = 'a'
            logging.basicConfig(**log_kwargs)
            logging.info("Diagnostics enabled via config.yml.")

        # --- Determine Model Config --- #
        default_model_settings = config_data.get("model", {})
        # Use model ID from config if present, else default from env/hardcoded
        default_model_id = default_model_settings.get("default") or os.getenv("PENGUIN_DEFAULT_MODEL", "anthropic/claude-3-5-sonnet-20240620") 
        default_provider = default_model_settings.get("provider") or os.getenv("PENGUIN_DEFAULT_PROVIDER", "anthropic") 
        default_client_pref = default_model_settings.get("client_preference") or os.getenv("PENGUIN_CLIENT_PREFERENCE", "litellm")

        specific_config = config_data.get("model_configs", {}).get(default_model_id, {})

        model_name_for_init = specific_config.get("model", default_model_id)
        provider_for_init = specific_config.get("provider", default_provider)
        client_pref_for_init = specific_config.get("client_preference", default_client_pref)

        llm_model_config = LLMModelConfig(
            model=model_name_for_init,
            provider=provider_for_init,
            client_preference=client_pref_for_init,
            # Pull other settings from specific_config or defaults
            api_base=specific_config.get("api_base", default_model_settings.get("api_base", os.getenv("PENGUIN_API_BASE"))),
            max_tokens=specific_config.get("max_tokens", default_model_settings.get("max_tokens", int(os.getenv("PENGUIN_MAX_TOKENS")) if os.getenv("PENGUIN_MAX_TOKENS") else None)),
            temperature=specific_config.get("temperature", default_model_settings.get("temperature", float(os.getenv("PENGUIN_TEMPERATURE")) if os.getenv("PENGUIN_TEMPERATURE") else 0.7)),
            streaming_enabled=specific_config.get("streaming_enabled", default_model_settings.get("streaming_enabled", os.getenv("PENGUIN_STREAMING_ENABLED", "true").lower() == "true")),
            vision_enabled=specific_config.get("vision_enabled", default_model_settings.get("vision_enabled", os.getenv("PENGUIN_VISION_ENABLED", "").lower() == "true" if os.getenv("PENGUIN_VISION_ENABLED") != "" else None)),
            max_history_tokens=specific_config.get("max_history_tokens", default_model_settings.get("max_history_tokens", int(os.getenv("PENGUIN_MAX_HISTORY_TOKENS")) if os.getenv("PENGUIN_MAX_HISTORY_TOKENS") else None)),
            api_version=specific_config.get("api_version", default_model_settings.get("api_version", os.getenv("API_VERSION"))), # Added API version
        )

        return cls(
            model_config=llm_model_config,
            api=APIConfig(base_url=config_data.get("api", {}).get("base_url")),
            workspace_path=Path(WORKSPACE_PATH), # WORKSPACE_PATH is already defined globally
            temperature=config_data.get("temperature", llm_model_config.temperature), # Use model temp if global not set
            max_tokens=config_data.get("max_tokens", llm_model_config.max_tokens), # Use model max_tokens if global not set
            diagnostics=diagnostics_config,
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
            "workspace_dir": str(self.workspace_dir),
            "cache_dir": str(self.cache_dir),
            "workspace_path": str(self.workspace_path),
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
