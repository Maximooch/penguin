# Penguin Docker

## Images
- Web API image (default): serves FastAPI on port 8000.

## Build
```bash
# Local dev (install from repo)
DOCKER_BUILDKIT=1 docker build -t penguin:web-local -f docker/Dockerfile.web --build-arg INSTALL_MODE=local .

# Release-style (install pip package)
DOCKER_BUILDKIT=1 docker build -t penguin:web -f docker/Dockerfile.web --build-arg INSTALL_MODE=release .
```

## Run
```bash
# Web default with OpenRouter (recommended for latest models)
docker run --rm -p 8000:8000 \
  --env-file .env \
  -e PENGUIN_DEFAULT_MODEL="deepseek/deepseek-v3.2-exp" \
  -e PENGUIN_DEFAULT_PROVIDER="openrouter" \
  -e PENGUIN_CLIENT_PREFERENCE="openrouter" \
  -e DEBUG="true" \
  penguin:web

# Or with GPT-5 via OpenRouter
docker run --rm -p 8000:8000 \
  --env-file .env \
  -e PENGUIN_DEFAULT_MODEL="openai/gpt-5" \
  -e PENGUIN_DEFAULT_PROVIDER="openrouter" \
  -e PENGUIN_CLIENT_PREFERENCE="openrouter" \
  penguin:web

# Or direct OpenAI
docker run --rm -p 8000:8000 \
  --env-file .env \
  -e PENGUIN_DEFAULT_MODEL="openai/gpt-4o" \
  -e PENGUIN_DEFAULT_PROVIDER="openai" \
  -e PENGUIN_CLIENT_PREFERENCE="native" \
  penguin:web

# Health
curl -s http://localhost:8000/api/v1/health

# Capabilities (shows current model)
curl -s http://localhost:8000/api/v1/capabilities | jq .
```

## Required env vars (.env file)
```env
# API Key (choose based on provider)
OPENROUTER_API_KEY=sk-or-...  # Recommended for latest models
# Or direct provider keys:
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# Model configuration (matches config.example.yml)
PENGUIN_DEFAULT_MODEL=deepseek/deepseek-v3.2-exp
PENGUIN_DEFAULT_PROVIDER=openrouter
PENGUIN_CLIENT_PREFERENCE=openrouter

# Workspace path (must be writable by penguinuser uid 10001)
PENGUIN_WORKSPACE=/home/penguinuser/penguin_workspace

# Optional: Enable debug logging to see LLM requests
PENGUIN_DEBUG=1
```

## GitHub App credentials
- Preferred: operator-managed installation token mounted as GITHUB_TOKEN.
- For App auth:
  - GITHUB_APP_ID, GITHUB_APP_INSTALLATION_ID, GITHUB_APP_PRIVATE_KEY_PATH (mount PEM at /secrets/github-app.pem)
  - GITHUB_REPOSITORY (e.g., owner/repo)

## Notes
- Runs as non-root user uid 10001.
- Health endpoint: /api/v1/health.
- Default CMD: python -m penguin.web.server.
- Image tags: publish immutable :sha and optionally promote to :latest / :vX.Y.Z.
