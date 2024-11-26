import os
from dotenv import load_dotenv # type: ignore
import yaml # type: ignore
from pathlib import Path
# import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

# LinkAI Workspace Configuration
# LINKAI_WORKSPACE_ID = os.getenv('LINKAI_WORKSPACE_ID')
# LINKAI_API_KEY = os.getenv('LINKAI_API_KEY')

WORKSPACE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'workspace')
os.makedirs(WORKSPACE_PATH, exist_ok=True)

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
TASK_COMPLETION_PHRASE = "TASK_COMPLETED"
MAX_TASK_ITERATIONS = 100



def load_config():
    config_path = Path(__file__).parent.parent / 'config.yml'
    # logger.debug(f"Attempting to load config from: {config_path}")
    try:
        with open(config_path, 'r') as config_file:
            config = yaml.safe_load(config_file)
            
            # Initialize diagnostics based on config
            if 'diagnostics' in config:
                from utils.diagnostics import disable_diagnostics, enable_diagnostics
                if not config['diagnostics'].get('enabled', False):
                    disable_diagnostics()
                else:
                    enable_diagnostics()
                    
            return config
    except FileNotFoundError:
        # logger.error(f"Config file not found at {config_path}")
        return {}
    except yaml.YAMLError as e:
        # logger.error(f"Error parsing config file: {e}")
        return {}
    

config = load_config()

# Default model configuration
DEFAULT_MODEL = os.getenv('PENGUIN_DEFAULT_MODEL', config['model']['default'])
DEFAULT_PROVIDER = os.getenv('PENGUIN_DEFAULT_PROVIDER', config['model']['provider'])
DEFAULT_API_BASE = os.getenv('PENGUIN_DEFAULT_API_BASE', config['api']['base_url'])
USE_ASSISTANTS_API = config['model'].get('use_assistants_api', True)  

# Add assistant-specific configuration
ASSISTANT_CONFIG = {
    'provider': config['model'].get('provider', 'openai'),
    'enabled': config['model'].get('use_assistants_api', False),
    'custom_llm_provider': 'openai',  # Required by litellm
    'model_name_override': None  # Optional override for assistant model name
}

def get_assistant_config() -> Dict[str, Any]:
    """Get the configuration for the Assistants API"""
    return {
        'provider': ASSISTANT_CONFIG['provider'],
        'enabled': ASSISTANT_CONFIG['enabled'],
        'custom_llm_provider': ASSISTANT_CONFIG['custom_llm_provider'],
        'model_name_override': ASSISTANT_CONFIG['model_name_override']
    }

# Model-specific configurations
MODEL_CONFIGS = config.get('model_configs', {})

# Update the existing ModelConfig creation to include assistant config
def get_model_config(model_name: Optional[str] = None) -> Dict[str, Any]:
    """Get the configuration for a specific model"""
    model_name = model_name or DEFAULT_MODEL
    base_config = MODEL_CONFIGS.get(model_name, {})
    
    return {
        'model': model_name,
        'provider': base_config.get('provider', DEFAULT_PROVIDER),
        'api_base': base_config.get('api_base', DEFAULT_API_BASE),
        'max_tokens': base_config.get('max_tokens'),
        'temperature': base_config.get('temperature'),
        'use_assistants_api': config['model'].get('use_assistants_api', False),
        'assistant_config': get_assistant_config() if config['model'].get('use_assistants_api', False) else None
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
    enabled: bool = False  # Default to False
    max_context_tokens: int = 200000
    log_to_file: bool = False
    log_path: Optional[Path] = None

@dataclass
class Config:
    model_name: Optional[str] = None
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    diagnostics: DiagnosticsConfig = DiagnosticsConfig()
    workspace_dir: Path = Path.cwd()
    cache_dir: Path = Path(os.getenv('PENGUIN_CACHE_DIR', '~/.cache/penguin')).expanduser()

    @classmethod
    def load_config(cls, config_path: Optional[Path] = None) -> 'Config':
        """Load configuration from config.yml"""
        if config_path is None:
            config_path = Path(__file__).parent.parent / 'config.yml'

        try:
            with open(config_path) as f:
                config_data = yaml.safe_load(f)
                
            # Load diagnostics config
            diagnostics_config = DiagnosticsConfig(
                enabled=config_data.get('diagnostics', {}).get('enabled', False),
                max_context_tokens=config_data.get('diagnostics', {}).get('max_context_tokens', 200000)
            )
            
            # Initialize diagnostics based on config
            if not diagnostics_config.enabled:
                from utils.diagnostics import disable_diagnostics
                disable_diagnostics()
            
            return cls(
                diagnostics=diagnostics_config
            )
                
        except FileNotFoundError:
            return cls()
        except yaml.YAMLError:
            return cls()

    def to_dict(self) -> Dict[str, Any]:
        if not self.model_name:
            raise ValueError("model_name must be specified")
            
        return {
            "model_name": self.model_name,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "diagnostics": {
                "enabled": self.diagnostics.enabled,
                "max_context_tokens": self.diagnostics.max_context_tokens,
                "log_to_file": self.diagnostics.log_to_file,
                "log_path": str(self.diagnostics.log_path) if self.diagnostics.log_path else None
            },
            "workspace_dir": str(self.workspace_dir),
            "cache_dir": str(self.cache_dir)
        }
