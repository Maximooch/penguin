# Penguin Networking & Deployment Strategy

## Overview
Design for production gateway architecture and local development environment.

---

## Production Gateway Architecture

### Gateway Choice: Traefik
**Why Traefik?**
- Native Kubernetes CRD support
- Automatic service discovery
- Built-in middleware (auth, rate limiting, CORS)
- SSL/TLS termination with Let's Encrypt
- No config reloads (dynamic configuration)

### Architecture Diagram
```
Internet
    │
    ▼
┌─────────────────────────────────────────────────────┐
│                   Cloudflare/CDN                     │
│              (DDoS protection, WAF)                  │
└─────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────┐
│              Traefik Gateway (Ingress)              │
│  ┌──────────────────────────────────────────────┐  │
│  │  Middleware Stack:                           │  │
│  │  - SSL/TLS termination                       │  │
│  │  - OAuth2/OIDC auth (Keycloak/Auth0)         │  │
│  │  - Rate limiting (100 req/min per IP)        │  │
│  │  - Request ID injection                      │  │
│  │  - CORS headers                              │  │
│  └──────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
    │
    ├──────────────┬──────────────┬──────────────┐
    ▼              ▼              ▼              ▼
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
│ Penguin  │  │ Penguin  │  │ Penguin  │  │ Dashboard│
│ API #1   │  │ API #2   │  │ API #3   │  │ (Telemetry)│
│ :8000    │  │ :8000    │  │ :8000    │  │          │
└──────────┘  └──────────┘  └──────────┘  └──────────┘
    │              │              │
    └──────────────┴──────────────┘
                   │
                   ▼
          ┌────────────────┐
          │ Shared Storage │
          │ (PVC: workspace)│
          └────────────────┘
```

### Traefik Configuration (K8s)

#### IngressRoute Example
```yaml
apiVersion: traefik.containo.us/v1alpha1
kind: IngressRoute
metadata:
  name: penguin-api
  namespace: penguin
spec:
  entryPoints:
    - websecure
  routes:
    - match: Host(`api.penguin.example.com`)
      kind: Rule
      middlewares:
        - name: penguin-auth
        - name: penguin-ratelimit
        - name: penguin-headers
      services:
        - name: penguin-web
          port: 80
  tls:
    certResolver: letsencrypt
```

#### Middleware Stack
```yaml
# OAuth2/OIDC Authentication
apiVersion: traefik.containo.us/v1alpha1
kind: Middleware
metadata:
  name: penguin-auth
spec:
  forwardAuth:
    address: http://oauth2-proxy:4181/oauth2/auth
    trustForwardHeader: true

# Rate Limiting
apiVersion: traefik.containo.us/v1alpha1
kind: Middleware
metadata:
  name: penguin-ratelimit
spec:
  rateLimit:
    average: 100
    burst: 50
    period: 1m

# Security Headers
apiVersion: traefik.containo.us/v1alpha1
kind: Middleware
metadata:
  name: penguin-headers
spec:
  headers:
    sslRedirect: true
    stsSeconds: 31536000
    frameDeny: true
    browserXssFilter: true
    contentTypeNosniff: true
    customFrameOptionsValue: "SAMEORIGIN"
```

### Service Mesh Consideration (Optional)
**When to add Istio/Linkerd:**
- Multi-tenant isolation requirements
- Advanced observability (distributed tracing)
- Canary deployments with traffic shifting
- Zero-trust network policies

**For now:** Skip service mesh - Traefik + K8s network policies sufficient.

---

## Local Development Environment

### Docker Compose Stack
```yaml
version: '3.9'

services:
  # Penguin Web API
  penguin:
    build:
      context: .
      dockerfile: docker/Dockerfile.web
      args:
        INSTALL_MODE: local
    ports:
      - "8000:8000"
    environment:
      - PENGUIN_DEFAULT_MODEL=deepseek/deepseek-v3.2-exp
      - PENGUIN_DEFAULT_PROVIDER=openrouter
      - PENGUIN_CLIENT_PREFERENCE=openrouter
      - PENGUIN_CORS_ORIGINS=*
      - PENGUIN_DEBUG=1
      - PENGUIN_WORKSPACE=/workspace
    env_file:
      - .env
    volumes:
      - ./workspace:/workspace
      - ./penguin:/app/penguin:ro  # Hot-reload for dev
    networks:
      - penguin-net
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://localhost:8000/api/v1/health"]
      interval: 10s
      timeout: 5s
      retries: 3
    restart: unless-stopped

  # Traefik Gateway (local)
  gateway:
    image: traefik:v3.0
    ports:
      - "80:80"
      - "443:443"
      - "8080:8080"  # Dashboard
    volumes:
      - ./deploy/traefik/traefik.yml:/etc/traefik/traefik.yml:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - penguin-net
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.dashboard.rule=Host(`traefik.localhost`)"
      - "traefik.http.routers.dashboard.service=api@internal"

  # Redis (for future: caching, sessions)
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    networks:
      - penguin-net
    volumes:
      - redis-data:/data
    command: redis-server --appendonly yes

  # PostgreSQL (for future: projects DB, if needed)
  postgres:
    image: postgres:16-alpine
    ports:
      - "5432:5432"
    environment:
      - POSTGRES_USER=penguin
      - POSTGRES_PASSWORD=penguin
      - POSTGRES_DB=penguin
    networks:
      - penguin-net
    volumes:
      - postgres-data:/var/lib/postgresql/data

  # Jaeger (tracing, optional)
  jaeger:
    image: jaegertracing/all-in-one:latest
    ports:
      - "16686:16686"  # UI
      - "14268:14268"  # HTTP thrift
    environment:
      - COLLECTOR_OTLP_ENABLED=true
    networks:
      - penguin-net

networks:
  penguin-net:
    driver: bridge

volumes:
  redis-data:
  postgres-data:
```

### Local Traefik Config
```yaml
# deploy/traefik/traefik.yml
api:
  dashboard: true
  insecure: true

entryPoints:
  web:
    address: ":80"
  websecure:
    address: ":443"

providers:
  docker:
    exposedByDefault: false
```

### Docker Labels for Service Discovery
Add to `penguin` service in compose:
```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.penguin.rule=Host(`penguin.localhost`)"
  - "traefik.http.services.penguin.loadbalancer.server.port=8000"
  - "traefik.http.middlewares.cors.headers.accesscontrolallowmethods=GET,POST,OPTIONS,PUT,DELETE"
  - "traefik.http.middlewares.cors.headers.accesscontrolallowheaders=Content-Type,Authorization"
  - "traefik.http.middlewares.cors.headers.accesscontrolalloworiginlist=*"
```

---

## Networking Strategy

### Service Communication Patterns

**1. External → Gateway → Penguin API**
- Path: `/api/v1/*` → Penguin container
- Auth: OAuth2/OIDC at gateway
- Rate limiting: Per-IP and per-user

**2. Penguin → LLM Providers**
- Direct outbound (OpenRouter, OpenAI, Anthropic)
- No proxy needed (unless using Link integration)
- Connection pooling via `ConnectionPoolManager`

**3. Penguin → External Services**
- GitHub API (webhook integration)
- MCP servers (optional)
- Browser tools (headless Chrome in future)

**4. Internal Services (Future)**
- Redis: Caching, session storage
- PostgreSQL: Persistent projects DB (vs SQLite)
- Message queue (RabbitMQ/Redis Streams): Background tasks

### Network Policies (K8s)
```yaml
# Allow only necessary traffic
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: penguin-netpol
  namespace: penguin
spec:
  podSelector:
    matchLabels:
      app: penguin
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
      - namespaceSelector:
          matchLabels:
            name: traefik
      ports:
        - protocol: TCP
          port: 8000
  egress:
    - to:
      - namespaceSelector: {}
      ports:
        - protocol: TCP
          port: 443  # HTTPS to LLM providers
        - protocol: TCP
          port: 53   # DNS
```

---

## Deployment Patterns

### 1. Single-Instance (Dev/Test)
- 1 replica
- SQLite for projects
- No external dependencies
- Use: `docker-compose up`

### 2. Production (Current)
- 3+ replicas (HPA)
- Shared PVC for workspace
- Traefik gateway
- OAuth2 auth
- Use: `kubectl apply -k deploy/k8s`

### 3. Multi-Tenant (Future)
- Namespace per tenant
- Resource quotas per tenant
- Istio service mesh for isolation
- Separate databases per tenant

### 4. Edge Deployment (Future)
- Single-node K3s cluster
- Local LLM (Ollama)
- Offline mode
- Reduced feature set

---

## TODO / Next Steps

### Immediate (This Week)
- [ ] Create `docker-compose.yml` in root
- [ ] Create `deploy/traefik/traefik.yml`
- [ ] Test local stack: `docker-compose up -d`
- [ ] Verify hot-reload with volume mount
- [ ] Add Redis to Penguin config (optional)

### Short-Term (Next Sprint)
- [ ] Create Traefik K8s manifests (`deploy/traefik/`)
- [ ] Add OAuth2-Proxy deployment
- [ ] Create NetworkPolicy resources
- [ ] Add HPA (Horizontal Pod Autoscaler) config
- [ ] Document production deployment runbook

### Medium-Term (This Quarter)
- [ ] Migrate SQLite → PostgreSQL (optional, for scale)
- [ ] Add Redis for caching/sessions
- [ ] Implement distributed tracing (OpenTelemetry)
- [ ] Add Prometheus metrics endpoint
- [ ] Create Grafana dashboards

### Long-Term (Future)
- [ ] Service mesh evaluation (Istio/Linkerd)
- [ ] Multi-tenant architecture
- [ ] Edge deployment support
- [ ] Canary deployment pipeline

---

## Configuration Checklist

### Environment Variables Required
```bash
# Core
PENGUIN_DEFAULT_MODEL=deepseek/deepseek-v3.2-exp
PENGUIN_DEFAULT_PROVIDER=openrouter
PENGUIN_CLIENT_PREFERENCE=openrouter
PENGUIN_WORKSPACE=/workspace
PENGUIN_DEBUG=1

# API Keys
OPENROUTER_API_KEY=sk-or-...
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# Gateway (Traefik)
GATEWAY_OAUTH2_CLIENT_ID=...
GATEWAY_OAUTH2_CLIENT_SECRET=...
GATEWAY_OAUTH2_ISSUER_URL=https://auth.example.com

# Database (optional, for PostgreSQL)
DATABASE_URL=postgresql://penguin:penguin@postgres:5432/penguin

# Redis (optional)
REDIS_URL=redis://redis:6379/0
```

### Secrets Management (K8s)
```bash
# Create secrets
kubectl create secret generic penguin-secrets \
  --from-literal=OPENROUTER_API_KEY=sk-or-... \
  --from-literal=OPENAI_API_KEY=sk-... \
  -n penguin

kubectl create secret generic gateway-secrets \
  --from-literal=OAUTH2_CLIENT_ID=... \
  --from-literal=OAUTH2_CLIENT_SECRET=... \
  -n penguin
```

---

## References
- Traefik docs: https://doc.traefik.io/traefik/
- K8s Network Policies: https://kubernetes.io/docs/concepts/services-networking/network-policies/
- OAuth2-Proxy: https://oauth2-proxy.github.io/oauth2-proxy/
- Docker Compose: https://docs.docker.com/compose/

---

**Last Updated:** 2026-02-06
**Status:** Design Phase - Implementation Pending