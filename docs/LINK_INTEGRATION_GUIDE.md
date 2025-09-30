# Link Chat App Integration with Penguin API

This guide shows how to integrate Link (or any chat application) with the containerized Penguin API.

## Prerequisites
- Penguin web container running (tested and working ✅)
- Link chat application
- Network connectivity between Link and Penguin

---

## Quick Start

### 1. Start Penguin Container

```bash
docker run --rm -d -p 8000:8000 \
  --env-file .env \
  -e PENGUIN_DEFAULT_MODEL="openai/gpt-5" \
  -e PENGUIN_DEFAULT_PROVIDER="openrouter" \
  -e PENGUIN_WORKSPACE="/home/penguinuser/penguin_workspace" \
  --name penguin-api \
  penguin:web-local
```

### 2. Verify Penguin is Running

```bash
curl http://localhost:8000/api/v1/health
# Should return: {"status":"healthy"}

curl http://localhost:8000/api/v1/capabilities | jq .
# Shows: model, vision_enabled, streaming_enabled, etc.
```

---

## Integration Pattern (Python Example)

```python
import requests

class PenguinClient:
    """Client for integrating with Penguin API."""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.conversation_id = None
    
    def get_capabilities(self):
        """Discover what Penguin can do."""
        resp = requests.get(f"{self.base_url}/api/v1/capabilities")
        return resp.json()
    
    def create_conversation(self, name: str = "Link conversation"):
        """Start a new conversation."""
        resp = requests.post(
            f"{self.base_url}/api/v1/conversations/create",
            json={"name": name}
        )
        data = resp.json()
        self.conversation_id = data.get("conversation_id") or data.get("id")
        return self.conversation_id
    
    def send_message(self, text: str, max_iterations: int = 5):
        """Send a message and get Penguin's response."""
        payload = {
            "text": text,
            "max_iterations": max_iterations
        }
        if self.conversation_id:
            payload["conversation_id"] = self.conversation_id
        
        resp = requests.post(
            f"{self.base_url}/api/v1/chat/message",
            json=payload,
            timeout=90
        )
        return resp.json()
    
    def get_history(self):
        """Get conversation history."""
        if not self.conversation_id:
            return []
        resp = requests.get(
            f"{self.base_url}/api/v1/conversations/{self.conversation_id}"
        )
        data = resp.json()
        return data.get("messages", data if isinstance(data, list) else [])


# Usage example
client = PenguinClient("http://localhost:8000")

# Discover capabilities
caps = client.get_capabilities()
print(f"Penguin model: {caps['model']}")
print(f"Vision enabled: {caps['vision_enabled']}")

# Start conversation
conv_id = client.create_conversation("My Link chat")
print(f"Conversation: {conv_id}")

# Chat with Penguin
response = client.send_message("Hello! What can you help me with?")
print(f"Penguin: {response['response'][:200]}...")

# Continue conversation
response = client.send_message("What is 2+2?")
print(f"Answer: {response['response']}")

# Get full history
history = client.get_history()
print(f"Total messages: {len(history)}")
```

---

## API Endpoints for Link

### Core Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/health` | Health check |
| GET | `/api/v1/capabilities` | Discover features |
| GET | `/api/v1/system/status` | Current status |

### Conversation Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/conversations/create` | Start new conversation |
| GET | `/api/v1/conversations` | List all conversations |
| GET | `/api/v1/conversations/{id}` | Get conversation history |

### Chat

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/chat/message` | Send message, get response |
| WebSocket | `/api/v1/chat/stream` | Stream responses in real-time |

### Model Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/models` | List available models |
| GET | `/api/v1/models/current` | Current model info |
| POST | `/api/v1/models/load` | Switch model at runtime |

---

## Request/Response Examples

### Send a Message

**Request:**
```json
POST /api/v1/chat/message
{
  "text": "What is the capital of France?",
  "conversation_id": "session_xyz",
  "max_iterations": 3
}
```

**Response:**
```json
{
  "response": "The capital of France is Paris.",
  "action_results": [],
  "conversation_id": "session_xyz"
}
```

### Send Message with Tool Usage

**Request:**
```json
POST /api/v1/chat/message
{
  "text": "What does https://example.com say?",
  "max_iterations": 5
}
```

**Response:**
```json
{
  "response": "The website says...",
  "action_results": [
    {
      "action_name": "pydoll_browser_navigate",
      "output": "...",
      "status": "completed"
    }
  ]
}
```

---

## WebSocket Streaming (for Real-Time UX)

```javascript
// JavaScript example for Link frontend
const ws = new WebSocket('ws://localhost:8000/api/v1/chat/stream');

ws.onopen = () => {
  ws.send(JSON.stringify({
    text: "Hello!",
    conversation_id: "session_xyz"
  }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(`Event: ${data.event}`, data.data);
  
  if (data.event === 'token') {
    // Stream individual tokens to UI
    appendToChat(data.data.content);
  } else if (data.event === 'complete') {
    // Response finished
    console.log('Complete:', data.data);
  }
};
```

---

## Deployment Options for Link

### Option 1: Link and Penguin on Same Host
```
Link App (localhost:3000)
   ↓
Penguin API (localhost:8000)
```

### Option 2: Link → Docker Network
```bash
# Create network
docker network create penguin-net

# Run Penguin
docker run -d --network penguin-net --name penguin-api penguin:web-local

# Run Link (connect via http://penguin-api:8000)
docker run -d --network penguin-net \
  -e PENGUIN_API_URL=http://penguin-api:8000 \
  link:latest
```

### Option 3: Link → Remote Penguin (Production)
```
Link App
   ↓ HTTPS
Load Balancer
   ↓
Kubernetes Service (penguin-web:80)
   ↓
Penguin Pods
```

---

## Testing Integration

Run the provided test to verify Link-style integration:

```bash
# Start Penguin
docker run --rm -d -p 8000:8000 --env-file .env penguin:web-local

# Test external client workflow
PENGUIN_API_URL=http://localhost:8000 python tests/api/test_external_client.py
```

**Expected output:**
```
✓ Penguin API ready
✓ Vision: False
✓ Streaming: True
✓ Model: openai/gpt-5
✓ Conversation ID: session_...
✓ Correct answer!
✓ History has 5 message(s)
✅ External client workflow test PASSED
```

---

## Security Considerations

### For Production

1. **Enable HTTPS**: Use TLS/SSL (Ingress with cert-manager)
2. **Add Authentication**: JWT tokens, API keys, or OAuth
3. **Rate Limiting**: Prevent abuse
4. **CORS**: Configure `PENGUIN_CORS_ORIGINS` properly
5. **Network Policy**: Restrict which pods can access Penguin

### Example CORS Configuration

```bash
# Allow only Link's domain
docker run -e PENGUIN_CORS_ORIGINS="https://link.yourdomain.com" penguin:web-local
```

---

## Tested & Working ✅

- ✅ Conversation creation and management
- ✅ Multi-turn chat with context preservation
- ✅ Tool usage (browser, search, code execution)
- ✅ Run mode (background and sync tasks)
- ✅ WebSocket streaming
- ✅ Model switching at runtime
- ✅ Health and status endpoints

**Link is ready to integrate with Penguin!**
