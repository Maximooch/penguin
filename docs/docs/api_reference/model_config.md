# ModelConfig

The `ModelConfig` class provides configuration for AI model interactions, including provider selection, parameters, and feature flags.

## Overview

```mermaid
classDiagram
    class ModelConfig {
        +String model
        +String provider
        +String client_preference
        +Optional~String~ api_base
        +Optional~String~ api_key
        +Optional~String~ api_version
        +Optional~Int~ max_output_tokens
        +Optional~Int~ max_context_window_tokens
        +Optional~Int~ max_history_tokens
        +Float temperature
        +Boolean use_assistants_api
        +Boolean streaming_enabled
        +Boolean enable_token_counting
        +Optional~Boolean~ vision_enabled
        +Boolean use_responses_api
        +Boolean interrupt_on_action
        +Optional~String~ service_tier
        +Optional~Boolean~ reasoning_enabled
        +__post_init__()
        +get_config()
        +from_env()
        +for_model()
    }
```

## Properties

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `model` | `str` | Required | The model identifier (e.g., "claude-sonnet-4.5") |
| `provider` | `str` | Required | The provider name (e.g., "anthropic", "openai") |
| `client_preference` | `str` | `"openrouter"` | Adapter preference: `native` \| `litellm` \| `openrouter` \| `link` |
| `api_base` | `Optional[str]` | `None` | Custom API base URL |
| `api_key` | `Optional[str]` | `None` | API key for authentication (from `<PROVIDER>_API_KEY` env) |
| `api_version` | `Optional[str]` | `None` | API version identifier |
| `max_output_tokens` | `Optional[int]` | `None` | Maximum tokens to generate in response |
| `max_context_window_tokens` | `Optional[int]` | `None` | Maximum context window capacity |
| `max_history_tokens` | `Optional[int]` | `None` | Maximum tokens to retain in history |
| `temperature` | `float` | `0.7` | Temperature for sampling (0.0-1.0) |
| `use_assistants_api` | `bool` | `False` | Whether to use OpenAI Assistants API |
| `streaming_enabled` | `bool` | `False` | Whether to enable streaming responses |
| `enable_token_counting` | `bool` | `True` | Whether to track token usage |
| `vision_enabled` | `Optional[bool]` | `None` | Whether to enable vision capabilities (auto-detected) |
| `use_responses_api` | `bool` | `False` | Whether to use the OpenAI Responses API |
| `interrupt_on_action` | `bool` | `True` | Whether to interrupt on tool actions |
| `service_tier` | `Optional[str]` | `None` | OpenAI service tier: `auto` \| `default` \| `flex` \| `priority` |
| `reasoning_enabled` | `Optional[bool]` | `None` | Whether reasoning tokens are enabled |
| `reasoning_effort` | `Optional[str]` | `None` | Reasoning effort level |
| `reasoning_max_tokens` | `Optional[int]` | `None` | Reasoning token budget |

## Methods

### \_\_post_init\_\_

```python
def __post_init__(self):
```

This method is called after initialization to:
- Set `reasoning_enabled` default and record explicit reasoning settings
- Normalize the OpenAI service tier
- Auto-enable native tools for models known to require them
- Set supported reasoning levels for known models
- Resolve the API key from `<PROVIDER>_API_KEY` when not provided
- Auto-detect vision capabilities based on model name
- Set backward compatibility properties

### get_config

```python
def get_config(self) -> Dict[str, Any]:
```

Returns a dictionary with the configuration values.

### from_env

```python
@classmethod
def from_env(cls):
```

Creates a ModelConfig instance from environment variables:

| Environment Variable | Property |
|---------------------|----------|
| `PENGUIN_CLIENT_PREFERENCE` | `client_preference` (`native`\|`litellm`\|`openrouter`\|`link`) |
| `PENGUIN_MODEL` | `model` |
| `PENGUIN_PROVIDER` | `provider` |
| `PENGUIN_API_BASE` | `api_base` |
| `PENGUIN_MAX_OUTPUT_TOKENS` | `max_output_tokens` (alias: `PENGUIN_MAX_TOKENS`) |
| `PENGUIN_MAX_CONTEXT_WINDOW_TOKENS` | `max_context_window_tokens` (alias: `PENGUIN_CONTEXT_WINDOW`) |
| `PENGUIN_TEMPERATURE` | `temperature` |
| `PENGUIN_MAX_HISTORY_TOKENS` | `max_history_tokens` |
| `PENGUIN_STREAMING_ENABLED` | `streaming_enabled` |
| `PENGUIN_VISION_ENABLED` | `vision_enabled` |
| `PENGUIN_USE_RESPONSES_API` | `use_responses_api` |
| `PENGUIN_INTERRUPT_ON_ACTION` | `interrupt_on_action` |
| `PENGUIN_REASONING_ENABLED` | `reasoning_enabled` |
| `PENGUIN_REASONING_EFFORT` | `reasoning_effort` |
| `PENGUIN_REASONING_MAX_TOKENS` | `reasoning_max_tokens` |
| `PENGUIN_REASONING_EXCLUDE` | `reasoning_exclude` |
| `PENGUIN_OPENAI_SERVICE_TIER` | `service_tier` (alias: `OPENAI_SERVICE_TIER`) |

## Auto-Detection Features

### Vision Capabilities

The `vision_enabled` property is auto-detected if not explicitly set:
- For Anthropic: True if model name contains "claude-3"
- For OpenAI: True if model name contains "gpt-4" and "vision"
- Default: False for other models

## Usage Examples

### Basic Configuration

```python
from penguin.llm.model_config import ModelConfig

# Create basic config
config = ModelConfig(
    model="claude-3-5-sonnet",
    provider="anthropic",
    temperature=0.7
)
```

### Configuration with Advanced Options

```python
# Create config with advanced options
config = ModelConfig(
    model="claude-sonnet-4.5",
    provider="anthropic",
    max_output_tokens=4096,
    temperature=0.5,
    client_preference="native",
    streaming_enabled=True,
    vision_enabled=True,
    reasoning_enabled=True,
    reasoning_effort="high"
)
```

### Loading from Environment

```python
# Set environment variables
os.environ["PENGUIN_MODEL"] = "gpt-4-turbo"
os.environ["PENGUIN_PROVIDER"] = "openai"
os.environ["PENGUIN_TEMPERATURE"] = "0.8"

# Load from environment
config = ModelConfig.from_env()
```

## Provider-Specific Features

### Anthropic Models

For Anthropic Claude models:
- Vision automatically enabled for Claude 3+ models
- `client_preference="native"` uses Anthropic's Python SDK directly
- Direct token counting for accurate token usage tracking

### OpenAI Models

For OpenAI GPT models:
- Vision automatically enabled for GPT-4 Vision models
- Assistants API optionally available through `use_assistants_api=True`
- Responses API available through `use_responses_api=True` 