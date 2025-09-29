# Penguin Kubernetes Manifests

## Prereqs
- Kubernetes cluster + kubectl
- Docker image available (e.g., penguin:web or your-registry/penguin:web)

## Files
- namespace.yaml — creates `penguin` namespace
- configmap.yaml — basic env (CORS)
- secret.github-app.yaml — mount App PEM as file
- secret.example.yaml — example env secrets (use your secret manager)
- deployment.yaml — web API Deployment (port 8000)
- service.yaml — ClusterIP Service (port 80 -> 8000)
- ingress.example.yaml — optional ingress
- kustomization.yaml — assemble all resources

## Usage
```bash
# Apply all
kubectl apply -k deploy/k8s

# Override image
auth_image="your-registry/penguin:web@sha256:<digest>"
kubectl set image deployment/penguin-web -n penguin \
  penguin="$auth_image"

# Check health
kubectl -n penguin port-forward svc/penguin-web 8080:80 &
curl -s http://127.0.0.1:8080/api/v1/health
```

## Notes
- Liveness/readiness probe: /api/v1/health
- Choose either App PEM mount or operator-managed GITHUB_TOKEN.
- For production, prefer immutable :sha tags.
