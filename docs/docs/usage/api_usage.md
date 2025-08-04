# Using Penguin's API

This guide provides examples and code snippets for interacting with Penguin's API endpoints in various programming languages and environments.

## Overview

Penguin provides a comprehensive REST API and WebSocket interface for integrating with applications, scripts, and other services. The API allows you to:

- Send messages and receive responses
- Stream responses in real-time
- Manage conversations
- Execute tasks
- Access context files
- Monitor token usage

## Quick Start

### Basic Chat Request

```python
import requests

# Send a simple message
response = requests.post(
    "http://localhost:8000/api/v1/chat/message",
    json={
        "text": "Write a Python function to calculate the Fibonacci sequence."
    }
)

# Print the response
print(response.json()["response"])
```

### JavaScript Example

```javascript
// Send a message using fetch
async function sendMessage(text) {
  const response = await fetch('http://localhost:8000/api/v1/chat/message', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      text: text
    })
  });
  
  const data = await response.json();
  return data.response;
}

// Usage
sendMessage("Explain quantum computing in simple terms")
  .then(response => console.log(response))
  .catch(error => console.error('Error:', error));
```

## Chat API

### Regular Chat

To send a message and receive a response:

```bash
curl -X POST http://localhost:8000/api/v1/chat/message \
  -H "Content-Type: application/json" \
  -d '{"text": "Generate a hello world program in Rust"}'
```

#### With Conversation Context

To continue an existing conversation:

```bash
curl -X POST http://localhost:8000/api/v1/chat/message \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Explain the key components of the code you just generated",
    "conversation_id": "conversation_20240330_123456"
  }'
```

### Streaming Responses

For real-time streaming of responses, use the WebSocket API:

```javascript
// Create WebSocket connection
const socket = new WebSocket('ws://localhost:8000/api/v1/chat/stream');

// Connection opened
socket.addEventListener('open', (event) => {
    socket.send(JSON.stringify({
        text: "Write a step-by-step guide to installing TensorFlow."
    }));
});

// Listen for messages
socket.addEventListener('message', (event) => {
    const data = JSON.parse(event.data);
    
    if (data.event === 'start') {
        console.log('Response started');
    } else if (data.event === 'token') {
        process.stdout.write(data.data.token);
    } else if (data.event === 'complete') {
        console.log('\nResponse completed');
        console.log('Action results:', data.data.action_results);
    }
});
```

## Conversation Management

### List Conversations

```python
import requests

# Get all conversations
response = requests.get("http://localhost:8000/api/v1/conversations")
conversations = response.json()["conversations"]

for conv in conversations:
    print(f"ID: {conv['session_id']}, Messages: {conv['message_count']}")
```

### Create New Conversation

```python
import requests

# Create a new conversation
response = requests.post("http://localhost:8000/api/v1/conversations/create")
conversation_id = response.json()["conversation_id"]

print(f"Created conversation: {conversation_id}")
```

### Retrieve Conversation

```python
import requests

# Get a specific conversation
conversation_id = "conversation_20240330_123456"
response = requests.get(f"http://localhost:8000/api/v1/conversations/{conversation_id}")
data = response.json()

# Get messages
for message in data["messages"]:
    print(f"{message['role']}: {message['content']}")
```

## Project and Task Management

### Create Project

```python
import requests

# Create a new project
response = requests.post(
    "http://localhost:8000/api/v1/projects",
    json={
        "name": "Website Development",
        "description": "Create a responsive website with React and FastAPI backend"
    }
)

project_data = response.json()
print(f"Created project: {project_data}")
```

### Execute Task

```python
import requests

# Run a task
response = requests.post(
    "http://localhost:8000/api/v1/tasks/execute",
    json={
        "name": "Generate API documentation",
        "description": "Create OpenAPI documentation for all endpoints",
        "continuous": False,
        "time_limit": 30  # minutes
    }
)

print(f"Task execution started: {response.json()}")
```

## Utility Endpoints

### Token Usage

```python
import requests

# Get token usage stats
response = requests.get("http://localhost:8000/api/v1/token-usage")
usage = response.json()["usage"]

print(f"Main model usage: {usage['main_model']['total']} tokens")
```

### Context Files

```python
import requests

# List available context files
response = requests.get("http://localhost:8000/api/v1/context-files")
files = response.json()["files"]

for file in files:
    print(f"File: {file['path']}, Size: {file['size']}")

# Load a context file
response = requests.post(
    "http://localhost:8000/api/v1/context-files/load",
    json={
        "file_path": "docs/api_reference.md"
    }
)

print(f"Context file loaded: {response.json()}")
```

## Error Handling

The API uses standard HTTP status codes:

- 200: Success
- 400: Bad Request (invalid parameters)
- 404: Not Found (resource doesn't exist)
- 500: Server Error

Example error handling:

```python
import requests

try:
    response = requests.post(
        "http://localhost:8000/api/v1/chat/message",
        json={"invalid_param": "value"}
    )
    response.raise_for_status()
    
    data = response.json()
    print(data["response"])
    
except requests.exceptions.HTTPError as e:
    if response.status_code == 400:
        print(f"Bad request: {response.json().get('detail')}")
    elif response.status_code == 500:
        print(f"Server error: {response.json().get('detail')}")
    else:
        print(f"HTTP error: {e}")
        
except Exception as e:
    print(f"Error: {e}")
```

## Integrating with Other Languages

### cURL

```bash
# Send a message
curl -X POST http://localhost:8000/api/v1/chat/message \
  -H "Content-Type: application/json" \
  -d '{"text": "What are the key features of Penguin?"}'
```

### Java

```java
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;

public class PenguinApiExample {
    public static void main(String[] args) {
        try {
            HttpClient client = HttpClient.newHttpClient();
            
            String requestBody = "{\"text\": \"Explain SOLID principles\"}";
            
            HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create("http://localhost:8000/api/v1/chat/message"))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(requestBody))
                .build();
                
            HttpResponse<String> response = client.send(request, 
                HttpResponse.BodyHandlers.ofString());
                
            System.out.println(response.body());
        } catch (Exception e) {
            e.printStackTrace();
        }
    }
}
```

### Go

```go
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io/ioutil"
	"net/http"
)

func main() {
	// Create request body
	requestBody, _ := json.Marshal(map[string]string{
		"text": "Explain container orchestration",
	})

	// Send POST request
	resp, err := http.Post(
		"http://localhost:8000/api/v1/chat/message",
		"application/json",
		bytes.NewBuffer(requestBody),
	)
	
	if err != nil {
		fmt.Println("Error:", err)
		return
	}
	defer resp.Body.Close()

	// Read response
	body, _ := ioutil.ReadAll(resp.Body)
	
	// Parse JSON response
	var result map[string]interface{}
	json.Unmarshal(body, &result)
	
	fmt.Println(result["response"])
}
```

## Rate Limiting

The API currently does not implement rate limiting, but best practices include:

- Limit request frequency to avoid overloading the server
- Implement retries with exponential backoff for failed requests
- Use a single conversation for related messages to maintain context

## Security Considerations

When deploying Penguin in a production environment:

- Use HTTPS for all API communication
- Implement proper authentication and authorization
- Restrict CORS settings to known domains
- Review and limit model capabilities as needed

<!-- TODO: Test these before making them public -->
<!-- ## Additional APIs

### Checkpoint Management

```python
import requests

# Create a checkpoint
response = requests.post(
    "http://localhost:8000/api/v1/checkpoints/create",
    json={
        "name": "Before refactor",
        "description": "Save state prior to major refactor"
    }
)
checkpoint_id = response.json()["checkpoint_id"]

# List checkpoints
checkpoints = requests.get("http://localhost:8000/api/v1/checkpoints").json()["checkpoints"]

# Rollback
requests.post(f"http://localhost:8000/api/v1/checkpoints/{checkpoint_id}/rollback")
```

### Model Management

```python
import requests

# List available models
models = requests.get("http://localhost:8000/api/v1/models").json()["models"]

# Switch model
requests.post(
    "http://localhost:8000/api/v1/models/load",
    json={"model_id": "openai/gpt-4o"}
)

# Get current model
current = requests.get("http://localhost:8000/api/v1/models/current").json()
```

### Memory API

```python
import requests

# Store memory
memory = requests.post(
    "http://localhost:8000/api/v1/memory/store",
    json={
        "content": "Remember that Friday is deploy day",
        "categories": ["dev_notes"]
    }
).json()

# Search memory
results = requests.post(
    "http://localhost:8000/api/v1/memory/search",
    json={"query": "deploy day", "max_results": 3}
).json()["results"]
```

### System & Capabilities

```bash
# Capabilities
curl http://localhost:8000/api/v1/capabilities

# System status
curl http://localhost:8000/api/v1/system/status
``` -->

## Next Steps

- Review the [API Reference Documentation](/docs/api_reference/api_server) for detailed endpoint specifications
- Explore the [Web Interface](/docs/api_reference/webui) for a browser-based experience
- Consider [setting up a proxy](/docs/advanced/deployment) for production deployments 