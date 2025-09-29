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
# Web default
docker run --rm -p 8000:8000 \
  -e PENGUIN_CORS_ORIGINS="*" \
  penguin:web

# Health
curl -s http://localhost:8000/api/v1/health
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
