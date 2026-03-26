# Penguin LLM Integration with Link

> **Purpose:** Guide for configuring Penguin to route LLM requests through Link's inference proxy for unified billing, analytics, and future RL/finetuning data collection.
>
> **Last Updated:** 2025-12-18
> **Link Version:** MVP (auth middleware + user API keys)

---

## Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        INTEGRATION FLOW                          │
│                                                                  │
│  User opens session in Link (userId known)                      │
│           ↓                                                      │
│  Link starts Penguin with user context                          │
│           ↓                                                      │
│  Penguin makes LLM call with X-Link-* headers                   │
│           ↓                                                      │
│  Link Backend validates auth + proxies to OpenRouter            │
│           ↓                                                      │
│  Billing event queued to Polar.sh                               │
└─────────────────────────────────────────────────────────────────┘
```

Link's inference proxy at `/api/v1/chat/completions` is **fully OpenAI-compatible**. Penguin just needs to:
1. Point its LLM client at Link's URL
2. Pass user context in headers
3. Optionally implement fallback to direct OpenRouter

---

## Quick Start

### Option 1: Penguin config.yml (Recommended)

Configure Penguin's `config.yml` to route through Link:

```yaml
# penguin/config.yml

model:
  model: anthropic/claude-sonnet-4
  provider: openrouter  # Keep as openrouter - Link's proxy is OpenRouter-compatible
  client_preference: openrouter
  streaming_enabled: true
  temperature: 0.5
  context_window: 200000
  max_output_tokens: 64000

api:
  base_url: http://localhost:3001/api/v1  # Point to Link's inference proxy
  # Production: base_url: https://your-link-domain.com/api/v1
```

And in Penguin's `.env`:

```bash
# Use your Link API key (create in Settings → API Keys → Link API Keys)
OPENROUTER_API_KEY=sk-link-xxxxxxxxxxxxxxxx
```

**Why this works:** Link's inference proxy is OpenRouter-compatible, so `provider: openrouter` format works. The `sk-link-*` API key tells Link which user to bill.

### Option 2: Environment Variables Only

```bash
# Point to Link's inference proxy
OPENAI_BASE_URL=http://localhost:3001/api/v1  # Local dev
# OPENAI_BASE_URL=https://linkplatform.ai/api/v1  # Production

# Use your Link API key
OPENROUTER_API_KEY=sk-link-xxxxxxxxxxxxxxxx

# Or for internal traffic (no API key needed):
# LINK_USER_ID=your-user-id
```

That's it for MVP. Penguin's OpenAI SDK calls will automatically route through Link.

---

## Authentication

Link's inference proxy supports multiple auth modes (checked in order):

### 1. User API Key (Recommended for Production)

Create API keys in Settings → API Keys → Link API Keys section:

```python
# In Penguin's LLM client
headers = {
    "Authorization": f"Bearer {os.getenv('LINK_API_KEY')}",  # e.g., sk-link-abc12345...
    "X-Link-Session-Id": session_id,  # Optional, for tracking
    "X-Link-Agent-Id": agent_id,      # Optional, for multi-agent
}
```

User API keys:
- Start with `sk-link-` prefix (triggers GitHub/GitLab secret scanning)
- Are validated against the database (hashed storage)
- Automatically associate usage with the user who created them
- Can be revoked anytime from the settings UI

### 2. Admin API Key (Environment Variable)

For server-to-server communication where you need to specify a different user:

```python
headers = {
    "Authorization": f"Bearer {os.getenv('LINK_INFERENCE_API_KEY')}",  # Admin key from env
    "X-Link-User-Id": user_id,      # Required - which user to bill
    "X-Link-Session-Id": session_id,
    "X-Link-Agent-Id": agent_id,
}
```

### 3. Internal Headers (MVP/Local)

For same-machine traffic (Link and Penguin on localhost), just pass the headers:

```python
headers = {
    "X-Link-User-Id": user_id,      # Required for billing
    "X-Link-Session-Id": session_id,  # Optional, for session tracking
    "X-Link-Agent-Id": agent_id,      # Optional, for multi-agent scenarios
}
```

### 3. BYOK (Bring Your Own Key)

Users can use their own OpenRouter API key to bypass Link billing:

```python
headers = {
    "X-Link-User-Id": user_id,
    "X-Link-BYOK": "true",  # Skip billing queue
}
```

---

## Required Headers

| Header | Required | Description |
|--------|----------|-------------|
| `X-Link-User-Id` | Yes | Link user ID for billing attribution |
| `X-Link-Session-Id` | No | Session ID for usage tracking |
| `X-Link-Agent-Id` | No | Agent ID for multi-agent scenarios |
| `X-Link-Workspace-Id` | No | Workspace ID for org-level billing |
| `X-Link-BYOK` | No | Set to `"true"` to skip billing |
| `Authorization` | Production | `Bearer <LINK_INFERENCE_API_KEY>` |

---

## Penguin Implementation Changes

### Option A: Environment Variable Override

If Penguin uses the OpenAI SDK, it should respect `OPENAI_BASE_URL`:

```python
# penguin/llm/client.py
import os
from openai import OpenAI

def get_llm_client():
    base_url = os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")

    return OpenAI(
        base_url=base_url,
        api_key=api_key,
        default_headers=_get_link_headers(),
    )

def _get_link_headers():
    """Get Link context headers from environment or runtime context."""
    headers = {}

    # From environment (set by Link when spawning Penguin)
    if os.getenv("LINK_USER_ID"):
        headers["X-Link-User-Id"] = os.getenv("LINK_USER_ID")
    if os.getenv("LINK_SESSION_ID"):
        headers["X-Link-Session-Id"] = os.getenv("LINK_SESSION_ID")
    if os.getenv("LINK_AGENT_ID"):
        headers["X-Link-Agent-Id"] = os.getenv("LINK_AGENT_ID")

    # API key for production
    if os.getenv("LINK_INFERENCE_API_KEY"):
        headers["Authorization"] = f"Bearer {os.getenv('LINK_INFERENCE_API_KEY')}"

    return headers
```

### Option B: Config File (config.yml)

Penguin's actual `config.yml` format (see [config.example.yml](https://github.com/Maximooch/penguin/blob/main/penguin/config.example.yml)):

```yaml
# penguin/config.yml

model:
  model: anthropic/claude-sonnet-4
  provider: openrouter  # Keep as openrouter - Link proxy is OpenRouter-compatible
  client_preference: openrouter
  streaming_enabled: true
  temperature: 0.5
  context_window: 200000
  max_output_tokens: 64000

api:
  base_url: http://localhost:3001/api/v1  # Link's inference proxy

# Agent-specific overrides (optional)
agents:
  researcher:
    model: anthropic/claude-haiku-4.5
    provider: openrouter
  implementer:
    model: anthropic/claude-sonnet-4
    provider: openrouter
```

Combined with `.env`:

```bash
# Link API key (created in Settings → API Keys)
OPENROUTER_API_KEY=sk-link-xxxxxxxxxxxxxxxx
```

**Note:** The `provider: openrouter` setting is correct because Link's proxy accepts OpenRouter-format requests. The `sk-link-*` API key is validated by Link and used for billing attribution.

### Option C: Runtime API

Add endpoint to set LLM base URL at runtime:

```python
# In Penguin's routes.py
@router.post("/api/v1/system/config/llm")
async def set_llm_config(request: LLMConfigRequest, core: PenguinCore = Depends(get_core)):
    """Configure LLM endpoint at runtime."""
    if request.base_url:
        core.llm_config.set_base_url(request.base_url)
    if request.link_user_id:
        core.llm_config.set_link_user_id(request.link_user_id)
    if request.link_session_id:
        core.llm_config.set_link_session_id(request.link_session_id)

    return {
        "status": "success",
        "base_url": core.llm_config.base_url,
        "link_user_id": core.llm_config.link_user_id,
    }
```

---

## Fallback Behavior

When Link is unavailable, Penguin should fall back to direct OpenRouter:

```python
# penguin/llm/client.py
import httpx
from typing import Optional

class LLMClient:
    def __init__(self, config):
        self.primary_url = config.get("base_url", "http://localhost:3001/api/v1")
        self.fallback_url = config.get("fallback", {}).get("base_url", "https://openrouter.ai/api/v1")
        self.fallback_enabled = config.get("fallback", {}).get("enabled", True)
        self.timeout = config.get("fallback", {}).get("timeout_ms", 5000) / 1000

        self.link_headers = self._build_link_headers(config)

    async def chat_completion(self, messages, model, **kwargs):
        """Make chat completion request with automatic fallback."""
        try:
            return await self._request(self.primary_url, messages, model, **kwargs)
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            if self.fallback_enabled:
                logger.warning(f"Link proxy unavailable ({e}), falling back to direct OpenRouter")
                # Clear Link-specific headers for direct OpenRouter
                return await self._request(
                    self.fallback_url,
                    messages,
                    model,
                    skip_link_headers=True,
                    **kwargs
                )
            raise

    async def _request(self, base_url, messages, model, skip_link_headers=False, **kwargs):
        headers = {"Content-Type": "application/json"}

        if not skip_link_headers:
            headers.update(self.link_headers)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                json={"messages": messages, "model": model, **kwargs},
                headers=headers,
            )
            response.raise_for_status()
            return response.json()
```

---

## Link Backend Integration

When Link starts a Penguin session, it should pass user context:

```typescript
// apps/backend/src/services/penguinService.ts

export class PenguinService {
  /**
   * Start a new Penguin session with user context
   */
  async startSession(session: AgentSession, userId: string) {
    // Set LLM config with Link user context
    await fetch(`${this.config.apiUrl}/api/v1/system/config/llm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        base_url: process.env.LINK_INFERENCE_URL || 'http://localhost:3001/api/v1',
        link_user_id: userId,
        link_session_id: session.id,
        link_agent_id: session.agentId,
      }),
    });

    // ... rest of session initialization
  }
}
```

Or pass via environment when spawning Penguin:

```typescript
// When spawning Penguin process
const env = {
  ...process.env,
  OPENAI_BASE_URL: 'http://localhost:3001/api/v1',
  LINK_USER_ID: userId,
  LINK_SESSION_ID: sessionId,
  LINK_AGENT_ID: agentId,
};
```

---

## Environment Variables Reference

### Penguin Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_BASE_URL` | `https://openrouter.ai/api/v1` | LLM API base URL |
| `OPENROUTER_API_KEY` | - | API key for OpenRouter (or Link `sk-link-*` key) |
| `LINK_USER_ID` | - | User ID for billing attribution (internal headers) |
| `LINK_SESSION_ID` | - | Session ID for usage tracking |
| `LINK_AGENT_ID` | - | Agent ID for multi-agent scenarios |

### Link Backend Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | - | Link's OpenRouter API key (for proxying to OpenRouter) |
| `LINK_INFERENCE_API_KEY` | - | Admin API key for server-to-server auth |
| `INFERENCE_ALLOW_ANONYMOUS` | `false` | Allow requests without auth (dev only) |

---

## Cloud Container Deployment (Future)

For Penguin instances running in cloud containers:

### Per-Container Configuration

Each container gets its own `config.yml`:

```yaml
# Container config
api:
  base_url: https://link.yourplatform.com/api/v1  # Production Link proxy

model:
  provider: openrouter
  model: anthropic/claude-sonnet-4
```

With environment variable for the Link API key:

```bash
# Each container uses a Link API key
OPENROUTER_API_KEY=sk-link-container-specific-key
```

### Multi-Tenant with User Context

For multi-tenant scenarios (one Penguin serving multiple users), use internal headers:

```bash
# Container env
OPENAI_BASE_URL=https://link.yourplatform.com/api/v1
```

And pass user context per-request via headers:

```python
# Per-request user context
headers = {
    "X-Link-User-Id": current_user_id,
    "X-Link-Session-Id": session_id,
}
```

### Future: Runtime Config API

Penguin could add a runtime config endpoint for Link to configure per-session:

```python
# Proposed: POST /api/v1/system/config/llm
{
    "base_url": "https://link.yourplatform.com/api/v1",
    "link_user_id": "user-123",
    "link_session_id": "session-456"
}
```

This would allow Link to dynamically configure Penguin instances without container restarts.

---

## Testing

### 1. Test with curl

```bash
# Test Link's inference proxy directly
curl -X POST http://localhost:3001/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Link-User-Id: test-user" \
  -H "X-Link-Session-Id: test-session" \
  -d '{
    "model": "anthropic/claude-3.5-haiku",
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 100
  }'
```

### 2. Test with Link's chat CLI

```bash
cd apps/backend
pnpm run chat-cli
# This uses the inference proxy with test user context
```

### 3. Penguin Integration Test

**IMPORTANT**: For Penguin's tests to actually route through Link, you MUST set `base_url` explicitly:

```python
# ✅ CORRECT: Routes through Link
base_url = "http://localhost:3001/api/v1"  # Link proxy

# ❌ WRONG: Routes directly to OpenRouter (bypasses Link)
base_url = None  # Defaults to https://openrouter.ai/api/v1
```

Example test that actually tests Link integration:

```python
def test_link_integration():
    """Test that requests route through Link's proxy."""
    # MUST specify Link's URL explicitly
    client = OpenAI(
        base_url="http://localhost:3001/api/v1",
        api_key="not-needed-for-internal",  # Uses headers instead
        default_headers={
            "X-Link-User-Id": "test-user",
            "X-Link-Session-Id": "test-session",
        },
    )

    response = client.chat.completions.create(
        model="anthropic/claude-3.5-haiku",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=10,
    )

    # Verify response came through
    assert response.choices[0].message.content
```

To verify requests are hitting Link, check the backend logs:

```
[OpenRouter] Non-streaming chat completion: anthropic/claude-3.5-haiku (user: test-user, auth: internal-headers)
```

### 4. Verify billing

Check the billing queue logs:
```bash
# In Link backend logs, you should see:
# [BillingQueue] Enqueued event for user test-user, model anthropic/claude-3.5-haiku
```

---

## Troubleshooting

### 401 Unauthorized

- Check if `LINK_INFERENCE_API_KEY` is set (production)
- Check if `INFERENCE_ALLOW_ANONYMOUS=true` (development)
- Verify `X-Link-User-Id` header is being sent

### Connection Refused

- Ensure Link backend is running on port 3001
- Check `OPENAI_BASE_URL` is correct
- Verify no firewall blocking the connection

### Billing Not Working

- Check `X-Link-User-Id` is not `anonymous`
- Verify `X-Link-BYOK` is not set to `true`
- Check Link backend logs for billing queue events

---

## Related Documentation

- [Backend Inference Routing](link_todo_backend_inference.md) - Full inference architecture
- [Penguin Integration](Penguin_Integration.md) - Overall Link ↔ Penguin integration
- [Architecture](../architecture.md) - System architecture overview

---

## Changelog

### 2025-12-18
- Added Penguin `config.yml` examples with actual format from config.example.yml
- Updated Quick Start with recommended config.yml approach
- Clarified that `provider: openrouter` works because Link proxy is OpenRouter-compatible
- Added reference to Penguin's config.example.yml on GitHub

### 2025-12-16
- Added Google OAuth login page for agentboard-web
- Added AuthContext provider for frontend session management
- Settings router now uses authenticated user's ID for API key operations
- Added `/api/auth/me` endpoint for frontend session validation
- Added logout button to Settings → General tab
- All authenticated pages now require login (redirect to `/login` if not authenticated)

### 2025-12-15
- Initial document
- Added auth middleware to Link backend (`inference/auth.ts`)
- Updated `openrouter.ts` to use auth context
- Added BYOK support (skip billing)
- Added system user detection
