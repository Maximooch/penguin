# Traefik Gateway for Penguin (Kubernetes)

## Overview
Production-ready gateway configuration using Traefik v3 for Penguin API deployment.

## Components

### 1. IngressRoute
Routes external traffic to Penguin API with TLS termination.

### 2. Middleware Stack
- **penguin-auth**: OAuth2/OIDC authentication via oauth2-proxy
- **penguin-ratelimit**: Rate limiting (100 req/min avg, 50 burst)
- **penguin-headers**: Security headers (CORS, HSTS, XSS protection)

### 3. NetworkPolicy
Restricts traffic to/from Penguin pods:
- Ingress: Only from Traefik namespace on port 8000
- Egress: HTTPS (443), DNS (53), Redis (6379), PostgreSQL (5432)

### 4. OAuth2-Proxy
OIDC authentication layer. Requires secrets:
- `OAUTH2_CLIENT_ID`
- `OAUTH2_CLIENT_SECRET`
- `OAUTH2_ISSUER_URL`
- `COOKIE_SECRET`

### 5. HPA (Horizontal Pod Autoscaler)
Auto-scales Penguin deployment:
- Min: 2 replicas
- Max: 10 replicas
- Triggers: CPU > 70%, Memory > 80%

## Prerequisites

### 1. Traefik Installed
```bash
# Install Traefik Helm chart
helm repo add traefik https://traefik.github.io/charts
helm repo update
helm install traefik traefik/traefik -n traefik --create-namespace
```

### 2. Cert-Manager (for Let's Encrypt)
```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.0/cert-manager.yaml
```

### 3. Create Secrets
```bash
# OAuth2 secrets
kubectl create secret generic gateway-secrets \
  --from-literal=OAUTH2_CLIENT_ID=your-client-id \
  --from-literal=OAUTH2_CLIENT_SECRET=your-client-secret \
  --from-literal=OAUTH2_ISSUER_URL=https://your-oidc-provider.com \
  --from-literal=COOKIE_SECRET=$(openssl rand -base64 32) \
  -n penguin
```

## Deployment

### Apply All Resources
```bash
# From project root
kubectl apply -k deploy/k8s
```

### Verify Deployment
```bash
# Check pods
kubectl get pods -n penguin

# Check services
kubectl get svc -n penguin

# Check ingress routes
kubectl get ingressroute -n penguin

# Check HPA
kubectl get hpa -n penguin
```

## DNS Configuration

### Configure DNS Record
Point your domain to the Traefik LoadBalancer IP:
```bash
# Get Traefik external IP
kubectl get svc -n traefik traefik

# Add A record: api.penguin.example.com -> <EXTERNAL-IP>
```

## Testing

### Health Check
```bash
curl https://api.penguin.example.com/api/v1/health
```

### Auth Test
```bash
# Should redirect to OIDC provider
curl -v https://api.penguin.example.com/api/v1/chat/message
```

### Rate Limit Test
```bash
# Should return 429 after 100 requests
for i in {1..110}; do
  curl https://api.penguin.example.com/api/v1/health
done
```

## Troubleshooting

### Traefik Dashboard
```bash
kubectl port-forward -n traefik svc/traefik 9000:9000
# Open http://localhost:9000/dashboard/
```

### OAuth2-Proxy Logs
```bash
kubectl logs -n penguin -l app=oauth2-proxy -f
```

### Network Policy Debug
```bash
# Check if policy is applied
kubectl get networkpolicy -n penguin

# Test connectivity
kubectl run -it --rm debug --image=nicolaka/netshoot --restart=Never -n penguin
# Inside pod:
curl http://penguin-web:8000/api/v1/health
```

## Configuration

### Update Domain
Edit `ingressroute.yaml`:
```yaml
- match: Host(`api.your-domain.com`)
```

### Adjust Rate Limits
Edit `middleware-ratelimit.yaml`:
```yaml
rateLimit:
  average: 100  # Requests per minute
  burst: 50    # Burst capacity
```

### Modify HPA Thresholds
Edit `hpa.yaml`:
```yaml
metrics:
  - resource:
      name: cpu
      target:
        averageUtilization: 70  # Adjust as needed
```

## Security Notes

1. **TLS Only**: IngressRoute uses `websecure` entry point
2. **Let's Encrypt**: Cert-manager handles automatic cert renewal
3. **Network Isolation**: NetworkPolicy restricts egress to necessary ports only
4. **Auth Required**: All requests must pass OAuth2-Proxy
5. **Secrets**: Never commit secrets to git; use sealed-secrets or external secret manager

## Scaling

### Manual Scaling
```bash
kubectl scale deployment penguin-web -n penguin --replicas=5
```

### HPA Status
```bash
kubectl describe hpa penguin-hpa -n penguin
```

## Monitoring

### Traefik Metrics
Traefik exposes Prometheus metrics on port 9100:
```bash
kubectl port-forward -n traefik svc/traefik 9100:9100
curl http://localhost:9100/metrics
```

### Penguin Metrics
Add Prometheus scraping to Penguin deployment (future):
```yaml
ports:
  - containerPort: 9090
    name: metrics
```

## References
- [Traefik Documentation](https://doc.traefik.io/traefik/)
- [OAuth2-Proxy](https://oauth2-proxy.github.io/oauth2-proxy/)
- [Kubernetes Network Policies](https://kubernetes.io/docs/concepts/services-networking/network-policies/)
- [HPA Documentation](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/)