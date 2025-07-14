# Reasoning Tokens Support in Penguin

Penguin now supports reasoning tokens for models that offer transparent insight into their reasoning process. This feature is particularly useful for understanding how models approach complex problems and can improve response quality.

## Supported Models

### OpenRouter
- **DeepSeek R1** models (`deepseek/deepseek-r1`, `deepseek/deepseek-r1:free`, etc.)
- **Gemini Thinking** models (`google/gemini-2.5-flash-preview:thinking`)
- **Anthropic Claude** models with reasoning support
- **OpenAI o-series** models (when available through OpenRouter)
- **Grok** models

## Configuration

### Model Configuration

Reasoning tokens are automatically enabled for supported models. You can customize the behavior in your model configuration:

```python
from penguin.llm.model_config import ModelConfig

# Auto-detected reasoning configuration
model_config = ModelConfig(
    model="deepseek/deepseek-r1",
    provider="openrouter",
    client_preference="openrouter"
)

# Manual reasoning configuration
model_config = ModelConfig(
    model="deepseek/deepseek-r1", 
    provider="openrouter",
    client_preference="openrouter",
    reasoning_enabled=True,
    reasoning_effort="high",  # "low", "medium", "high" (for OpenAI-style models)
    reasoning_max_tokens=2000,  # For Anthropic/Gemini-style models
    reasoning_exclude=False  # Set to True to use reasoning internally but not show it
)
```

### Environment Variables

You can also configure reasoning tokens via environment variables:

```bash
export PENGUIN_REASONING_ENABLED=true
export PENGUIN_REASONING_EFFORT=medium  # low, medium, high
export PENGUIN_REASONING_MAX_TOKENS=2000
export PENGUIN_REASONING_EXCLUDE=false
```

### Config File

Add reasoning configuration to your `config.yml`:

```yaml
model_configs:
  deepseek-reasoning:
    model: "deepseek/deepseek-r1"
    provider: "openrouter"
    client_preference: "openrouter"
    reasoning_enabled: true
    reasoning_effort: "high"
    streaming_enabled: true
    
  gemini-thinking:
    model: "google/gemini-2.5-flash-preview:thinking"
    provider: "openrouter" 
    client_preference: "openrouter"
    reasoning_enabled: true
    reasoning_max_tokens: 3000
    streaming_enabled: true
```

## Usage

### Basic Usage

Reasoning tokens work automatically when enabled:

```python
import asyncio
from penguin.core import PenguinCore

async def main():
    # Initialize with a reasoning-capable model
    core = await PenguinCore.create(
        model="deepseek/deepseek-r1",
        provider="openrouter"
    )
    
    # Ask a complex question
    response = await core.process_message(
        "Solve this step by step: If a train leaves NYC at 2 PM going 60 mph, "
        "and another leaves Boston at 3 PM going 80 mph, when do they meet?"
    )
    
    print(response)

asyncio.run(main())
```

### Streaming with Reasoning

Reasoning tokens are streamed separately from the main response:

```python
async def stream_callback(chunk: str, message_type: str):
    if message_type == "reasoning":
        print(f"🤔 THINKING: {chunk}", end="", flush=True)
    else:
        print(f"💭 RESPONSE: {chunk}", end="", flush=True)

response = await core.process(
    "Explain quantum entanglement",
    streaming=True,
    stream_callback=stream_callback
)
```

### UI Events

The core emits specialized events for reasoning tokens:

```python
def handle_ui_event(event_type: str, data: dict):
    if event_type == "stream_chunk" and data.get("is_reasoning"):
        print(f"Reasoning: {data['chunk']}")
    elif event_type == "message" and data.get("reasoning"):
        print(f"Final reasoning: {data['reasoning']}")

core.register_ui(handle_ui_event)
```

## Understanding Reasoning Styles

### Effort-Based (OpenAI o-series, Grok)
- `"low"`: ~20% of max_tokens allocated to reasoning
- `"medium"`: ~50% of max_tokens allocated to reasoning  
- `"high"`: ~80% of max_tokens allocated to reasoning

### Token-Based (Anthropic, Gemini)
- Specify exact number of tokens for reasoning
- Typical range: 1000-5000 tokens
- Higher values allow more detailed reasoning

### Auto-Detection

Penguin automatically detects reasoning capabilities:

```python
model_config = ModelConfig(model="deepseek/deepseek-r1", provider="openrouter")
print(f"Supports reasoning: {model_config.supports_reasoning}")  # True
print(f"Uses effort style: {model_config._uses_effort_style()}")  # False
print(f"Uses token style: {model_config._uses_max_tokens_style()}")  # True
```

## Advanced Features

### Excluding Reasoning from Response

Use reasoning internally but don't show it to users:

```python
model_config.reasoning_exclude = True
```

### Preserving Reasoning Across Tool Calls

When using tools, reasoning blocks are preserved automatically:

```python
# Reasoning context is maintained across tool invocations
response = await core.process_message(
    "Check the weather in Boston and recommend what to wear",
    tools_enabled=True
)
```

### Token Counting

Reasoning tokens are counted separately:

```python
usage = core.get_token_usage()
print(f"Total tokens: {usage['main_model']['total']}")
# Reasoning tokens are included in the total count
```

## Troubleshooting

### Model Not Supporting Reasoning

If reasoning tokens don't appear:

1. Verify the model supports reasoning tokens
2. Check that `reasoning_enabled=True`
3. Ensure you're using OpenRouter client preference
4. Check the model name includes reasoning variants (e.g., `:thinking`)

### Streaming Issues

If reasoning tokens don't stream properly:

1. Ensure streaming is enabled
2. Verify your callback accepts `(chunk, message_type)` parameters
3. Check for API key permissions

### Configuration Issues

```python
# Debug reasoning configuration
config = model_config.get_reasoning_config()
print(f"Reasoning config: {config}")

# Check auto-detection
print(f"Detected reasoning support: {model_config.supports_reasoning}")
```

## CLI Integration

The Penguin CLI automatically displays reasoning tokens in a different style:

```bash
# Reasoning tokens appear in a dimmed/italic style
# Regular response appears in normal text
penguin chat --model deepseek/deepseek-r1 "Solve this complex math problem..."
```

## Best Practices

1. **Use reasoning for complex problems**: Logic puzzles, math, analysis
2. **Monitor token usage**: Reasoning tokens count toward your quota
3. **Adjust effort/tokens**: Higher values for more complex reasoning
4. **Test different models**: Each model has different reasoning styles
5. **Stream for real-time insight**: See the model's thought process unfold

## Examples

See the `examples/` directory for complete examples of:
- Basic reasoning usage
- Streaming reasoning tokens
- Complex problem solving
- Tool usage with reasoning
- Custom UI integration 