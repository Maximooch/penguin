## Penguin Containerization and GitHub App Integration TODO

Goal: ship a production-ready container for Penguin, then wire secure GitHub access via the Penguin Agent GitHub App. Keep it simple, robust, and reproducible.

### Outcomes
- Container image: small, fast, non-root, reproducible, with health/readiness checks.
- GitHub API auth: GitHub App → installation access token (preferred), PAT fallback.
- Git push auth: origin remote configured to use an ephemeral token (App token or PAT).
- Kubernetes-ready manifests: secrets, env, and runtime wiring.

---

## Phase 1 — Containerization ✅

### Notes
- ✅ Dockerfile.web created with UV, dual install modes, non-root user
- ✅ .dockerignore optimized for repo
- ✅ Build toolchain added/removed to support compiled deps (madoka)
- ⚠️  Config precedence: env vars MUST override baked-in config.yml; rebuild image when config.yml changes

### 1) Base image and system deps
- Use `python:3.12-slim`.
- Install tools needed at runtime: `git`, `ca-certificates`.

### 2) Dependencies and cache
- Leverage Docker layer caching: copy lock/requirements first, install, then app code.
- Prefer wheels and `--no-cache-dir`.

### 3) Multi‑stage build
- Stage 1: build wheels (optional if you have compiled deps).
- Stage 2: runtime with only needed artifacts.

### 4) Non‑root user
- Create `penguinuser`, drop privileges, fix ownership.

### 5) .dockerignore
- Exclude venvs, tests, `.git`, local caches, build artifacts, large assets not required at runtime.

### 6) Entrypoints
- Web/API (default): `penguin-web` or `python -m penguin.web.server` (uses Uvicorn internally). Alt: `uvicorn penguin.web.app:create_app --host 0.0.0.0 --port 8000 --factory`.
- CLI (optional): `penguin` or `python -m penguin.main`.

### 7) Healthcheck
- Web health endpoint is `/api/v1/health`. Expose TCP 8000 and probe this path.

### Example Dockerfile (UV, single-stage, dual install modes)
```dockerfile
FROM python:3.12-slim AS runtime

# System deps
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /app

# App code (present when building locally from repo)
COPY . .

# Dual install modes (default: release installs from PyPI; local installs from source)
ARG INSTALL_MODE=release
RUN if [ "$INSTALL_MODE" = "local" ]; then \
      uv pip install --system .[web]; \
    else \
      uv pip install --system penguin-ai; \
    fi

# Non-root user
RUN useradd -m penguinuser \
    && chown -R penguinuser:penguinuser /app
USER penguinuser

# Optional: healthcheck if running API server
# HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1:8000/api/v1/health || exit 1

# Example: Web (default; override with CMD/args)
EXPOSE 8000
CMD ["python", "-m", "penguin.web.server"]
```

### Example .dockerignore
```gitignore
.git
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
*.pyc
*.pyo
*.pyd
*.egg-info/
build/
dist/
.venv/
venv/
node_modules/
docs/
misc/
tmp*/
```

### Build and run
```bash
# Build from local source (INstall from repo)
docker build -t penguin:web-local -f docker/Dockerfile.web --build-arg INSTALL_MODE=local .

# Build release-style (install pip package)
docker build -t penguin:web -f docker/Dockerfile.web --build-arg INSTALL_MODE=release .

# Web default
docker run --rm -p 8000:8000 penguin:web
curl -s http://localhost:8000/api/v1/health

# CLI alternative
docker run --rm -it --entrypoint python penguin:web -m penguin.main --help
```

---

## Phase 2 — GitHub App/Bot Integration ✅

**Setup Guide:** See `docs/GITHUB_APP_SETUP.md` for detailed instructions on creating and configuring the Penguin Agent GitHub App with secure key management.

### ✅ Setup Verified (Docker)
- App ID: 1622624
- Installation ID: 88065184 (Maximooch account)
- PEM securely stored at `~/.penguin/secrets/github-app.pem`
- Docker volume mount tested and working
- Installation token obtained successfully
- Repo access confirmed: Maximooch/penguin

### ✅ PR Creation Working!
- **Test PR created:** https://github.com/Maximooch/penguin-test-repo/pull/13
- **Endpoint:** `POST /api/v1/tasks/execute-sync` (uses Engine.run_task)
- **Branch created:** penguin-test-20250930-025734
- **Committed and pushed** using GitHub App credentials
- **PR opened** with title and body
- **Full workflow verified:** Container → API → Engine → GitManager → GitHub

Penguin prefers authenticating as a GitHub App for API calls, with fallback to `GITHUB_TOKEN` if provided. For git push, configure `origin` to use an HTTPS URL with an ephemeral installation token or PAT.

### A) Configure environment/secrets
- Required for App auth (preferred):
  - `GITHUB_APP_ID`
  - `GITHUB_APP_INSTALLATION_ID`
  - `GITHUB_APP_PRIVATE_KEY_PATH` (mounted path to App PEM)
- Repo target:
  - `GITHUB_REPOSITORY` (e.g., `owner/repo`)
- Fallback or explicit git push token:
  - `GITHUB_TOKEN` (PAT or refreshed installation token)

### B) Provide the App private key
- Mount a read‑only secret file in the container, e.g., `/secrets/github-app.pem`, and set `GITHUB_APP_PRIVATE_KEY_PATH=/secrets/github-app.pem`.

### C) API auth (handled in code)
- Penguin uses GitHub App credentials to mint installation access tokens for API calls (PyGithub). If App auth is unavailable, it uses `GITHUB_TOKEN`.

### D) Git push configuration
- Ensure `origin` exists and points to the repo:
  ```bash
  git -C "$REPO_DIR" remote get-url origin >/dev/null 2>&1 || \
    git -C "$REPO_DIR" remote add origin "https://github.com/${GITHUB_REPOSITORY}.git"
  ```
- Provide credentials for HTTPS pushes:
  - Option 1 (recommended for automation): set `GITHUB_TOKEN` to an installation token or PAT and use the URL form `https://x-access-token:${GITHUB_TOKEN}@github.com/OWNER/REPO.git`.
  - Option 2: configure credential helper to read `~/.git-credentials` with a token you refresh out-of-band.
  ```bash
  git config --global credential.helper store
  printf "https://x-access-token:%s@github.com\n" "$GITHUB_TOKEN" > "$HOME/.git-credentials"
  ```

Notes:
- Penguin configures commit identity when an App is present (author name/email); it does not inject push credentials. You must supply the token via remote URL or a credential helper.

### E) Token lifecycle (operator‑managed by default)
- App installation tokens are short‑lived.
- Default: use a Kubernetes operator (e.g., GitHub Token Manager) to mint/refresh an installation token into a Secret that is mounted as `GITHUB_TOKEN`.
- Alternative: run a sidecar/cron to refresh and update `GITHUB_TOKEN` (and `~/.git-credentials`) periodically.

---

## Phase 3 — Kubernetes Wiring

### Secrets and Deployment (example)
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: penguin-github-app
type: Opaque
stringData:
  github-app.pem: |
    # <paste PEM here or use external secret solution>
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: penguin
spec:
  replicas: 1
  selector:
    matchLabels: { app: penguin }
  template:
    metadata:
      labels: { app: penguin }
    spec:
      containers:
        - name: penguin
          image: penguin:local
          env:
            - name: GITHUB_APP_ID
              value: "<app-id>"
            - name: GITHUB_APP_INSTALLATION_ID
              value: "<installation-id>"
            - name: GITHUB_APP_PRIVATE_KEY_PATH
              value: "/secrets/github-app.pem"
            - name: GITHUB_REPOSITORY
              value: "owner/repo"
            # Optional if using token for git push
            # - name: GITHUB_TOKEN
            #   valueFrom:
            #     secretKeyRef:
            #       name: penguin-installation-token
            #       key: token
          volumeMounts:
            - name: gh-app-key
              mountPath: /secrets
              readOnly: true
          ports:
            - containerPort: 8000
          livenessProbe:
            httpGet:
              path: /api/v1/health
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 30
          readinessProbe:
            httpGet:
              path: /api/v1/health
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 10
      volumes:
        - name: gh-app-key
          secret:
            secretName: penguin-github-app
            items:
              - key: github-app.pem
                path: github-app.pem
```

### Operator-managed tokens (default)
- Deploy a controller (e.g., GitHub Token Manager) to create a Secret with an auto‑refreshed installation token. Mount as `GITHUB_TOKEN`.

---

## Phase 2.5 — GitHub Mentions, Workflows, and Hooks (Bot)

### A) PR/Issue mentions (@Penguin)
- Configure the GitHub App to subscribe to: `issue_comment`, `pull_request`, `pull_request_review`, and `pull_request_review_comment` events.
- Add a webhook endpoint in the web API (e.g., `POST /api/v1/integrations/github/webhook`) that verifies `X-Hub-Signature-256` and processes events.
- Trigger actions on `@Penguin` mention or slash commands in comments, e.g.:
  - `@Penguin review` → run review, post findings, optionally request changes/approve.
  - `@Penguin fix tests` → create branch, attempt fixes, push, open/append PR.
  - `@Penguin plan` → generate implementation plan and checklist comment.
- Idempotency: dedupe by comment ID/event delivery ID to avoid double-processing.

### B) Workflow integration
- Post status via Checks API: `penguin/review`, `penguin/tests`, `penguin/plan` with links back to logs.
- Labels and triage: add labels (e.g., `penguin:needs-input`, `penguin:auto`) based on outcomes.
- PR body updates: append validation summaries and task IDs.

### C) Permissions & safety
- Enforce allow/ask/deny policies for repo write, shell, network per config (align with parity checklist permissions model).
- Require explicit opt-in labels (e.g., `penguin:auto`) before write operations in org‑wide mode.

### D) Hooks (extensibility)
- Define pre/post hooks around key actions: `branch.create`, `commit.create`, `push`, `pr.create`, `review.run`.
- Hook runner executes configured commands or Python callables with a structured context payload.
- Use cases: auto-format, run tests, notify Slack, enforce commit message conventions.

### E) Configuration
- Add webhook secret and allowed repos/orgs in `.penguin/config.yml`.
- Expose toggles for which triggers are enabled and which commands are allowed in PRs/issues.

---

## Phase 4 — Security Hardening
- Run non‑root; mount secrets read‑only; narrow file permissions.
- Minimize image (slim base, remove build caches).
- Pin dependency versions; enable vulnerability scans in CI.
- Limit GitHub App permissions to least privilege.

---

## Phase 5 — CI/CD
- Pipeline: lint (ruff), test (pytest), build, SBOM/scan, sign, push.
- Build args for provenance (commit SHA, build time); embed labels.
- Use OIDC for CI→cloud auth where possible; inject GH secrets via CI key vault.

### Image tag strategy — pros/cons
- `:latest`
  - Pros: easy to consume; defaults in examples
  - Cons: non-deterministic; can break deployments unexpectedly
- `:sha-<gitsha>` (immutable)
  - Pros: reproducible, traceable, safe rollbacks
  - Cons: more tags, need automation for promotion
- `:vX.Y.Z`
  - Pros: semantic versioning, human-friendly
  - Cons: must manage version bumps and backports

Recommendation: publish `:sha` always; optionally promote to `:vX.Y.Z` and `:latest` via CI gates.

---

## Phase 6 — Validation Checklist
- Image runs under non‑root.
- App boots (CLI or web) without interactive input.
- App can create branches/commits and PRs via API (App auth path).
- `git push` works to `origin` using configured credentials.
- Tokens rotate without downtime.

---

## Phase 1.5 — Tool Usage & Run Mode Testing ✅

### Test Summary
- ✅ All tool usage tests passing (2/2)
- ✅ All run mode tests passing (2/2)
- ✅ WebSocket streaming verified (1/1)
- ✅ External client integration verified (1/1) - **Link chat app ready**
- ✅ Verified: PyDoll browser, Perplexity search, code execution tools work
- ✅ Verified: Background and sync task execution functional

### Tool Usage Tests ✅
- ✅ POST `/api/v1/chat/message` with tool-requiring prompt (Wikipedia penguin fetch)
- ✅ Verified `action_results` contains tool executions (PyDoll browser, Perplexity)
- ✅ Validated tool outputs included in response (first paragraph extracted)

### Run Mode Tests ✅
- ✅ POST `/api/v1/tasks/execute` — background task execution via RunMode
- ✅ POST `/api/v1/tasks/execute-sync` — synchronous task via Engine (10 iterations)
- ✅ WebSocket `/api/v1/tasks/stream` — streaming connection verified (callback impl pending)

### Test files
- ✅ `tests/api/test_web_api_tools.py` — tool usage verification
- ✅ `tests/api/test_web_api_runmode.py` — run mode execution
- ✅ `tests/api/test_web_api_websocket.py` — WebSocket streaming
- ✅ `tests/api/test_external_client.py` — external chat app integration (Link)
- ✅ `tests/api/test_github_pr_creation.py` — **PR creation working!** (uses task endpoint)
- ✅ `tests/api/test_github_app_auth.py` — GitHub App authentication

### Notes
- PR creation via simple chat requires project/task workflow (not just chat endpoint)
- External client (Link) integration fully functional and ready
- DeepSeek has issues with complex/long prompts; prefer GPT-5 or Claude for complex tasks

---

## Phase 7 — API Testing ✅

### Test Summary
- ✅ All Priority 1 tests passing (9/9)
- ✅ Real LLM calls verified (DeepSeek via OpenRouter)
- ✅ Container health, chat, conversations, projects all functional
- 🐛 Fixed: OpenAI adapter URL.rstrip() bug discovered via testing

### Priority 1: Core Functionality (smoke tests) ✅
- ✅ GET `/api/v1/health` — basic health check (container test)
- ✅ POST `/api/v1/chat/message` — send a chat message
- ✅ GET `/api/v1/conversations` — list conversations
- ✅ POST `/api/v1/conversations/create` — create conversation
- ✅ GET `/api/v1/capabilities` — discover API capabilities
- ✅ GET `/api/v1/system/status` — runtime status
- ✅ POST `/api/v1/projects` — create project
- ✅ GET `/api/v1/projects` — list projects
- ✅ GET `/api/v1/projects/{project_id}` — get project details

### Priority 2: Model & Discovery
- GET `/api/v1/models` — list available models
- GET `/api/v1/models/current` — current model info
- GET `/api/v1/system/info` — detailed system info

### Priority 3: Advanced Features
- POST `/api/v1/checkpoints/create` — manual checkpoint
- GET `/api/v1/checkpoints` — list checkpoints
- POST `/api/v1/tasks/execute-sync` — synchronous task execution
- POST `/api/v1/upload` — file upload (images)

### Priority 4: WebSocket & Streaming
- WebSocket `/api/v1/chat/stream` — streaming chat
- WebSocket `/api/v1/tasks/stream` — streaming task updates

### Test organization
- ✅ `tests/docker/test_web_container.py` — Docker health & lifecycle
- ✅ `tests/api/test_web_api_smoke.py` — Priority 1 basic endpoints (health, capabilities, status, conversations)
- ✅ `tests/api/test_web_api_core.py` — Priority 1 chat & project management (requires API keys)
- `tests/api/test_web_api_models.py` — Priority 2: Model management & switching
- `tests/api/test_web_api_checkpoints.py` — Priority 3: Checkpoint management
- `tests/api/test_web_api_integration.py` — Full workflow integration tests

---

## Quick Reference (env)
- `GITHUB_APP_ID`, `GITHUB_APP_INSTALLATION_ID`, `GITHUB_APP_PRIVATE_KEY_PATH`
- `GITHUB_REPOSITORY` (e.g., `owner/repo`)
- `GITHUB_TOKEN` (optional; PAT or refreshed installation token for git push)

---

## Decisions
- Use operator‑managed installation tokens by default for git push.
- Default container entrypoint: Web server on port 8000.
- Health endpoint: `/api/v1/health`.
- Build with `uv`; install mode configurable via `INSTALL_MODE=local|release`.
- Per-model configs in `config.yml` with appropriate token limits.
- Link chat app integration ready via external API.

## Known Issues & Next Steps

### Working ✅
- Container build and deployment
- All core API endpoints (chat, conversations, projects)
- Tool usage (browser, search, code execution)
- Run mode (background & sync)
- WebSocket streaming infrastructure
- GitHub App authentication
- External client integration (Link ready)
- Per-model token limit configuration

### Needs Attention ⚠️
- WebSocket streaming callback needs RunMode integration (minor)
- 🐛 **Local CLI issues:**
  - Multiple flags don't work together (`--old-cli --root workspace` fails)
  - CLI uses cwd instead of PENGUIN_WORKSPACE by default
  - GitHub App credentials not loaded in CLI (exist in .env but need to be passed through)

### Fixed ✅ (Image Rebuilt)
- ~~Runtime model switching~~ → Fixed with `ModelConfig.for_model()` dynamic resolution
- ~~Config precedence~~ → Fixed: env vars now properly override config.yml
- ~~PR creation~~ → Working via `/api/v1/tasks/execute-sync` endpoint
- ~~GitHub tools visibility~~ → Moved from PLACEHOLDER to ACTION_SYNTAX in prompt_actions.py
- ~~Assistant message storage~~ → Fixed in `engine.py:518-533` (finalize_streaming_message)
- ~~OpenAI URL bug~~ → Fixed `URL.rstrip()` TypeError
- ~~Build toolchain~~ → Added build-essential for madoka compilation

### Phase 2.5 Next Steps (Bot Features)
1. Implement webhook endpoint (`POST /api/v1/integrations/github/webhook`)
2. Add @Penguin mention detection and command parsing
3. Add Checks API integration for status updates
4. Implement hooks system (pre/post actions)
5. Add labels/triage automation

---

## Future consideration — Kubernetes deployment
- Provide `deploy/k8s/` manifests (Deployment, Service, Ingress, Secrets, RBAC if webhook receiver needed).
- Add Helm chart or Kustomize overlays for environments (dev/stage/prod).
- Document external secret managers (e.g., AWS/GCP) and operator-managed tokens.
- Webhook secret handling: Kubernetes Secret vs external secret manager (and rotation cadence).
- Allowed commands for @Penguin mentions (default set and org overrides).
- Checks API adoption: which checks to publish by default and required status rules.
- Minimal App permissions needed (repo scope matrix) and org rollout plan.


