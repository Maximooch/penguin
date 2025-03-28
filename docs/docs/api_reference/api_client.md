# API Client

The `APIClient` class provides a unified interface for interacting with various AI model APIs, handling both native provider-specific implementations and generic model access through LiteLLM.

## Architecture

The API client architecture consists of:

1. **APIClient** - Main interface for model interactions
2. **Provider Adapters** - Provider-specific implementations for each LLM service 
3. **Native Adapters** - Direct SDK implementations for optimal performance

```mermaid
classDiagram
    class APIClient {
        +ModelConfig model_config
        +BaseAdapter adapter
        +String system_prompt
        +set_system_prompt()
        +create_message()
        +process_response()
        +count_tokens()
        +get_response()
    }
    
    class BaseAdapter {
        <<Interface>>
        +format_messages()
        +process_response()
        +count_tokens()
        +supports_system_messages()
    }
    
    class NativeAdapter {
        <<Abstract>>
        +create_message()
        +count_tokens()
        +create_completion()
    }
    
    class LiteLLMAdapter {
        +format_messages()
        +process_response()
        +count_tokens()
    }
    
    class AnthropicAdapter {
        +provider = "anthropic"
        +format_messages()
        +count_tokens()
        +create_completion()
    }
    
    class OpenAIAdapter {
        +provider = "openai"
        +format_messages()
        +process_response()
    }
    
    class OllamaAdapter {
        +provider = "ollama" 
        +format_messages()
        +process_response()
    }
    
    class DeepseekAdapter {
        +provider = "deepseek"
        +format_messages()
        +process_response()
    }
    
    APIClient --> BaseAdapter : uses
    BaseAdapter <|-- NativeAdapter : implements
    BaseAdapter <|-- LiteLLMAdapter : implements
    NativeAdapter <|-- AnthropicAdapter : extends
    BaseAdapter <|-- OpenAIAdapter : implements
    BaseAdapter <|-- OllamaAdapter : implements
    BaseAdapter <|-- DeepseekAdapter : implements
```

## Provider Architecture

```mermaid
flowchart TD
    User([User]) --> APIClient[APIClient]
    
    APIClient --> AdapterChoice{Use Native Adapter?}
    
    AdapterChoice -- Yes --> FindNative{Native Available?}
    AdapterChoice -- No --> LiteLLM[LiteLLM Adapter]
    
    FindNative -- Yes --> NativeAdapter[Native Adapter]
    FindNative -- No --> LiteLLM
    
    NativeAdapter --> Anthropic[Anthropic SDK]
    
    LiteLLM --> AnthropicLL[Anthropic]
    LiteLLM --> OpenAILL[OpenAI]
    LiteLLM --> OllamaLL[Ollama]
    LiteLLM --> Azure[Azure OpenAI]
    LiteLLM --> Bedrock[AWS Bedrock]
    LiteLLM --> DeepseekLL[Deepseek]
    LiteLLM --> More[... and more]
    
    classDef client fill:#f9f,stroke:#333,stroke-width:2px
    classDef native fill:#bbf,stroke:#333,stroke-width:1px
    classDef external fill:#bfb,stroke:#333,stroke-width:1px
    classDef planned fill:#fbb,stroke:#333,stroke-width:1px,stroke-dasharray: 5 5
    
    class APIClient client
    class NativeAdapter,FindNative native
    class LiteLLM,AnthropicLL,OpenAILL,OllamaLL,Azure,Bedrock,DeepseekLL,More external
```

## Message Flow

```mermaid
sequenceDiagram
    participant Core as PenguinCore
    participant API as APIClient
    participant Adapter as Provider Adapter
    participant LLM as LLM Service
    
    Core->>API: get_response(messages)
    
    API->>API: Add system prompt if needed
    
    alt Native adapter
        API->>Adapter: create_message()
        Adapter->>LLM: Format & send request
        LLM-->>Adapter: Raw response
        Adapter-->>API: Processed response
    else LiteLLM
        API->>Adapter: format_messages()
        API->>LLM: acompletion() via LiteLLM
        LLM-->>API: Raw response
        API->>Adapter: process_response()
        Adapter-->>API: Processed response
    end
    
    API-->>Core: Return final response
```

## Initialization

```python
def __init__(self, model_config: ModelConfig):
    """
    Initialize the APIClient.

    Args:
        model_config (ModelConfig): Configuration for the AI model.
    """
```

The client automatically attempts to use the most appropriate adapter:
1. First tries to use a native, provider-specific adapter (e.g., direct Anthropic SDK)
2. Falls back to generic provider adapters via LiteLLM if native adapter isn't available

## Key Methods

### Message Creation

```python
async def create_message(
    self,
    messages: List[Dict[str, Any]],
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
) -> Any
```

Creates a message using the configured model and appropriate adapter.

### Response Processing

```python
def process_response(self, response: Any) -> tuple[str, List[Any]]
```

Processes the raw response from the AI model using the provider-specific adapter.

### Token Counting

```python
def count_tokens(self, content: Union[str, List, Dict]) -> int
```

Counts tokens for content, using the provider's specific tokenizer when available.

### Message Streaming

```python
async def get_response(
    self,
    messages: List[Dict[str, Any]],
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    stream: Optional[bool] = None,
    stream_callback: Optional[Callable[[str], None]] = None
) -> str
```

Unified interface for both streaming and non-streaming responses.

### System Prompt Management

```python
def set_system_prompt(self, prompt: str) -> None
```

Sets the system prompt and updates assistant if using Assistants API.

## Multi-Provider Support

The `APIClient` supports multiple providers through adapter architecture:

1. **Native Adapters**: Direct SDK implementations for:
   - Anthropic (Claude models)
   - *OpenAI (GPT models) - Planned but not yet implemented*
   - More to come

2. **Generic Adapters** via LiteLLM:
   - OpenAI
   - Anthropic
   - Ollama
   - DeepSeek
   - Azure OpenAI
   - AWS Bedrock
   - And many more

The selection between native and generic adapters is controlled by the `use_native_adapter` flag in the model configuration.

## Provider-Specific Features

### Anthropic (Native Adapter)

```python
class AnthropicAdapter(BaseAdapter):
    # Direct implementation using Anthropic's SDK
```

- Native multi-modal support
- Streaming implementation
- Direct token counting
- Base64 image handling
- Vision support for Claude 3 models

### OpenAI (via LiteLLM)

```python
class OpenAIAdapter(ProviderAdapter):
    # Implementation for OpenAI through provider adapter
```

- Multi-modal content support
- Message formatting for OpenAI-specific features
- Support for OpenAI's message structure

### Ollama (via LiteLLM)

```python
class OllamaAdapter(ProviderAdapter):
    # Implementation for Ollama through provider adapter
```

- Local model support
- Basic message formatting

### DeepSeek (via LiteLLM)

```python
class DeepseekAdapter(ProviderAdapter):
    # Implementation for DeepSeek through provider adapter
```

- System message handling
- Role alternation enforcement

## Configuration

Configure the API client through `ModelConfig`:

```python
@dataclass
class ModelConfig:
    model: str
    provider: str
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    api_version: Optional[str] = None
    max_tokens: Optional[int] = None
    max_history_tokens: Optional[int] = None
    temperature: float = 0.7
    use_assistants_api: bool = False
    use_native_adapter: bool = True  # Controls adapter selection
    streaming_enabled: bool = False
    enable_token_counting: bool = True
    vision_enabled: bool = None
```

Setting `use_native_adapter=False` forces the use of LiteLLM adapters.

## Usage Example

```python
# Initialize with native Anthropic adapter
model_config = ModelConfig(
    model="claude-3-5-sonnet",
    provider="anthropic",
    use_native_adapter=True
)

# Create client
api_client = APIClient(model_config=model_config)

# Set system prompt
api_client.set_system_prompt("You are a helpful assistant.")

# Prepare messages
messages = [
    {"role": "user", "content": "Hello, how are you?"}
]

# Get response (non-streaming)
response = await api_client.get_response(messages)
print(response)

# Get streaming response with callback
def on_chunk(chunk: str):
    print(chunk, end="", flush=True)

streaming_response = await api_client.get_response(
    messages, 
    stream=True,
    stream_callback=on_chunk
)
```

## Multi-modal Content

The client supports images and other multi-modal content:

```python
# Encode image to base64
base64_image = api_client.encode_image_to_base64("path/to/image.jpg")

# Create multi-modal message
messages = [
    {
        "role": "user",
        "content": [
            {"type": "text", "text": "What's in this image?"},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{base64_image}"
                }
            }
        ]
    }
]

# Process normally
response = await api_client.get_response(messages)
```

## Extension Points

To add a new provider:

1. Create a new adapter implementing `BaseAdapter` interface or extend the `ProviderAdapter` class
2. Implement the required methods: `format_messages()`, `process_response()`, and `count_tokens()`
3. Add to provider_adapters.py to register the adapter
4. For native adapters, create a new implementation in the adapters directory 