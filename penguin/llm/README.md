# Penguin LLM Integration

This package provides integrations with various LLM providers.

## Available Integrations

Penguin supports multiple ways to connect to LLM providers:

### 1. Native Adapters

Direct integration with provider-specific SDKs:
- Anthropic (Claude models)
- OpenAI (GPT models)
- Google (Gemini models)

### 2. LiteLLM Gateway

Unified access to 100+ LLMs through the LiteLLM library, which automatically handles:
- API format standardization
- Model aliases
- Complex routing

### 3. OpenRouter Gateway

Access to 200+ models through OpenRouter's unified API, offering:
- Consistent interface across providers (OpenAI-compatible)
- Cost optimization
- Fallback capability
- Model availability and uptime advantages

## Configuration

Configure your preferred models in `config.yml`:

```yaml
# Top-level model configuration
model:
  default: "anthropic/claude-3-7-sonnet-20250219"  # Default model
  provider: "anthropic"                           # Provider name
  client_preference: "litellm"                    # Integration method ("native", "litellm", or "openrouter")
  streaming_enabled: true
  # other settings...

# Model-specific configurations
model_configs:
  # Native adapter example
  anthropic-native/claude-3-opus-20240229:
    model: claude-3-opus-20240229
    provider: anthropic
    client_preference: native
    max_tokens: 4096
    
  # LiteLLM example
  openai/gpt-4o:
    provider: openai
    client_preference: litellm
    max_tokens: 4096
    
  # OpenRouter example
  google/gemini-2.0-flash:
    model: google/gemini-2.0-flash-exp:free
    provider: openrouter
    client_preference: openrouter
    max_tokens: 4096
```

## Environment Variables

Set the appropriate environment variables for your chosen provider:

```
# For native adapters or LiteLLM
ANTHROPIC_API_KEY=your_anthropic_key
OPENAI_API_KEY=your_openai_key
GOOGLE_API_KEY=your_google_key

# For OpenRouter
OPENROUTER_API_KEY=your_openrouter_key
OPENROUTER_SITE_URL=your_site_url  # Optional for OpenRouter leaderboards
OPENROUTER_SITE_TITLE=your_app_name  # Optional for OpenRouter leaderboards
```

## Usage

The `APIClient` will automatically use the appropriate gateway based on the `client_preference` setting:

```python
from penguin.llm.model_config import ModelConfig
from penguin.llm.api_client import APIClient

# Create model config (or load from config.yml)
model_config = ModelConfig(
    model="google/gemini-2.0-flash-exp:free",
    provider="openrouter",
    client_preference="openrouter"
)

# Initialize API client
client = APIClient(model_config)

# Use the client with any supported model
response = await client.get_response(
    messages=[{"role": "user", "content": "Hello, world!"}]
)
``` 