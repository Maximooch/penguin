# Using OpenRouter with Penguin

OpenRouter provides access to 200+ models through a single API. This guide explains how to set up and use OpenRouter effectively with Penguin.

## Setup

1. **Get an API Key**:
   - Sign up at [OpenRouter.ai](https://openrouter.ai/)
   - Get your API key from the dashboard

2. **Set Environment Variables**:
   ```bash
   export OPENROUTER_API_KEY=sk-or-xxxx
   export OPENROUTER_SITE_URL=https://penguinagents.com  # Optional override; this is the default
   export OPENROUTER_SITE_TITLE="Penguin"  # Optional override; this is the default
   ```

3. **Configure Penguin**:
   ```yaml
   # In config.yml
   model:
     default: "openai/gpt-3.5-turbo-0125"  # Free reliable model
     provider: "openrouter"
     client_preference: "openrouter"
   ```

## App attribution

The Python OpenRouter gateway defaults to `HTTP-Referer: https://penguinagents.com`
and `X-Title: Penguin`, including streaming and direct reasoning requests. Existing
constructor arguments and `OPENROUTER_SITE_URL` / `OPENROUTER_SITE_TITLE` overrides
remain supported; explicitly empty environment values omit the respective header.
Additional caller headers retain precedence. OpenRouter-compatible proxies used
through this gateway receive these headers too; they must forward them for upstream
attribution. Other Python provider adapters are unchanged.

The bundled TypeScript provider loaders identify Penguin for OpenRouter, Vercel
AI Gateway, and ZenMux. Provider-configured headers can override their defaults.

OpenRouter documents these headers in its quickstart. Attribution identifies the
application, not the end user, and does not change authentication or billing keys.

## Available Models

OpenRouter provides access to models from:
- OpenAI (GPT-4, GPT-3.5)
- Anthropic (Claude)
- Google (Gemini)
- Mistral
- Meta (Llama)
- And many others

### Free/Lower-Cost Models

These models have higher free quotas or lower costs:
- `openai/gpt-3.5-turbo-0125`
- `google/gemini-pro`
- `mistral/mistral-large-latest`
- `google/gemini-2.0-flash-exp:free`

## Model Comparison

| Model | Strengths | Limitations |
|-------|-----------|-------------|
| OpenAI GPT-4o | Versatile, powerful | Expensive |
| Anthropic Claude-3.5 | Great reasoning, long context | Expensive |
| Google Gemini Pro | Good reasoning, free | Rate limits, sometimes empty responses |
| Mistral Large | Good instructions, cheaper | Limited compared to top models |
| GPT-3.5 Turbo | Good general purpose, free | Less capable than newer models |

## Troubleshooting

### Quota Issues

If you see errors like:
```
[Error: Provider quota exceeded (Google). Quota exceeded for aiplatform.googleapis.com/...]
```

Solutions:
1. Switch to another model in `config.yml` (e.g., from Gemini to GPT-3.5)
2. Wait a few minutes and try again
3. Use providers with higher free quotas (like OpenAI or Mistral)

### Empty Responses

Some models (particularly DeepSeek Chat and occasionally Gemini) may return empty responses. When you see:
```
[Note: Model processed the request but returned empty content. Try rephrasing your query.]
```

Solutions:
1. **Switch Models**: Use a more reliable model like GPT-3.5 Turbo or Claude
2. **Adjust Parameters**: For DeepSeek models, try:
   ```yaml
   temperature: 0.9  # Higher temperature 
   top_p: 0.95       # Slightly lower top_p
   frequency_penalty: 0.1
   ```
3. **Simplify Prompts**: Break complex requests into simpler ones
4. **Avoid System Prompts**: Some models handle system prompts differently

For DeepSeek models specifically, they sometimes return empty strings when they're unsure or when the system prompt contains constraints they try to respect but can't formulate a response for.

### Vision/Multimodal Issues

Not all models support images. If you need vision capabilities:
1. Ensure you're using a vision-capable model (GPT-4o, Claude-3, Gemini)
2. Check that `vision_enabled: true` is set in the model's config

## Switching Models

To temporarily use a different model:
```python
from penguin.llm.model_config import ModelConfig
from penguin.llm.api_client import APIClient

# Create model config
model_config = ModelConfig(
    model="openai/gpt-3.5-turbo-0125",  # Switch to this model
    provider="openrouter",
    client_preference="openrouter"
)

# Initialize API client
api_client = APIClient(model_config)
```

## Best Practices

1. **For Development/Testing**: Use free models like GPT-3.5 or Gemini Pro
2. **For Complex Tasks**: Use more capable models like GPT-4o or Claude-3.5
3. **For Production**: Consider setting up fallback models in case of rate limits
4. **For Vision Tasks**: Ensure the model supports vision features 