# Penguin Agent GitHub App Setup Guide

This guide shows how to set up the Penguin Agent GitHub App for secure, containerized deployments without exposing secrets.

## Prerequisites
- GitHub organization or personal account
- Kubernetes cluster (for production) or Docker (for local testing)
- `kubectl` and `docker` CLI tools

---

## Part 1: Create the GitHub App

### 1. Register the App
1. Go to GitHub Settings → Developer settings → GitHub Apps → New GitHub App
2. Fill in:
   - **App name:** `Penguin Agent` (or `Penguin Agent - Dev` for testing)
   - **Homepage URL:** Your deployment URL or repo URL
   - **Webhook URL:** `https://your-domain.com/api/v1/integrations/github/webhook` (or leave blank for now)
   - **Webhook secret:** Generate a random secret (save for later): `openssl rand -hex 32`

### 2. Configure Permissions
Set these **Repository permissions**:
- **Contents:** Read & write (for commits/branches)
- **Issues:** Read & write (for @Penguin mentions)
- **Pull requests:** Read & write (for creating/updating PRs)
- **Metadata:** Read-only (required)
- **Checks:** Read & write (for status checks)
- **Workflows:** Read & write (optional, for modifying GitHub Actions)

Set these **Org permissions** (if installing org-wide):
- **Members:** Read-only (to identify users)

### 3. Subscribe to Events
Enable these webhook events:
- `issue_comment` - for @Penguin mentions in issues/PRs
- `pull_request` - PR open/update/close
- `pull_request_review` - review submitted
- `pull_request_review_comment` - review comment added
- `push` - commits pushed (optional)

### 4. Download Private Key
1. Scroll to "Private keys" section
2. Click "Generate a private key"
3. Save the downloaded `.pem` file securely (e.g., `penguin-agent-private-key.pem`)
4. **NEVER commit this file to git**

### 5. Note Your App Credentials
Save these values (you'll need them for deployment):
- **App ID:** Found at the top of your App's settings page
- **Client ID:** Found in the "About" section
- **Installation ID:** Install the app on a repo, then get the ID from the URL (e.g., `settings/installations/123456`)

---

## Part 2: Secure Key Management (Production)

### Option A: Kubernetes Secrets (Recommended)

**1. Create Secret from PEM file**
```bash
kubectl create secret generic penguin-github-app \
  --from-file=github-app.pem=./penguin-agent-private-key.pem \
  --namespace=penguin
```

**2. Create env var Secret**
```bash
kubectl create secret generic penguin-secrets \
  --from-literal=GITHUB_APP_ID=1622624 \
  --from-literal=GITHUB_APP_INSTALLATION_ID=<your-installation-id> \
  --from-literal=GITHUB_REPOSITORY=owner/repo \
  --from-literal=OPENROUTER_API_KEY=<your-key> \
  --namespace=penguin
```

**3. Verify secrets**
```bash
kubectl get secrets -n penguin
kubectl describe secret penguin-github-app -n penguin
```

### Option B: External Secret Manager (AWS/GCP/Azure)

**AWS Secrets Manager:**
```bash
# Store PEM
aws secretsmanager create-secret \
  --name penguin/github-app-key \
  --secret-string file://penguin-agent-private-key.pem

# Store env vars
aws secretsmanager create-secret \
  --name penguin/config \
  --secret-string '{
    "GITHUB_APP_ID": "1622624",
    "GITHUB_APP_INSTALLATION_ID": "...",
    "GITHUB_REPOSITORY": "owner/repo"
  }'
```

Then use [External Secrets Operator](https://external-secrets.io/) to sync to K8s:
```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: penguin-github-app
  namespace: penguin
spec:
  secretStoreRef:
    name: aws-secretsmanager
    kind: SecretStore
  target:
    name: penguin-github-app
  data:
    - secretKey: github-app.pem
      remoteRef:
        key: penguin/github-app-key
```

### Option C: GitHub Token Manager Operator (Automatic Rotation)

1. Install [GitHub Token Manager](https://github.com/isometry/github-token-manager):
```bash
kubectl apply -f https://github.com/isometry/github-token-manager/releases/latest/download/install.yaml
```

2. Create AppCredential (stores App key):
```yaml
apiVersion: github-token-manager.io/v1
kind: AppCredential
metadata:
  name: penguin-agent
  namespace: penguin
spec:
  appId: "1622624"
  privateKey:
    secretRef:
      name: penguin-github-app
      key: github-app.pem
```

3. Create AppInstallationToken (auto-refreshes):
```yaml
apiVersion: github-token-manager.io/v1
kind: AppInstallationToken
metadata:
  name: penguin-installation-token
  namespace: penguin
spec:
  appCredentialRef:
    name: penguin-agent
  installationId: "<your-installation-id>"
```

This creates a Secret `penguin-installation-token` with auto-refreshed `token` key.

---

## Part 3: Local/Dev Setup (Docker)

### For local testing (NOT for production):

**1. Store PEM securely outside repo:**
```bash
mkdir -p ~/.penguin/secrets
cp penguin-agent-private-key.pem ~/.penguin/secrets/
chmod 600 ~/.penguin/secrets/penguin-agent-private-key.pem
```

**2. Mount as read-only volume:**
```bash
docker run --rm -p 8000:8000 \
  --env-file .env \
  -e GITHUB_APP_ID=1622624 \
  -e GITHUB_APP_INSTALLATION_ID=<your-id> \
  -e GITHUB_APP_PRIVATE_KEY_PATH=/secrets/github-app.pem \
  -e GITHUB_REPOSITORY=Maximooch/penguin \
  -v ~/.penguin/secrets/penguin-agent-private-key.pem:/secrets/github-app.pem:ro \
  penguin:web-local
```

**3. Or use environment variable (less secure, but acceptable for local dev):**
```bash
# Export PEM as env var (base64 to avoid newline issues)
export GITHUB_APP_PRIVATE_KEY=$(cat penguin-agent-private-key.pem | base64)

docker run --rm -p 8000:8000 \
  --env-file .env \
  -e GITHUB_APP_PRIVATE_KEY \
  penguin:web-local
```

**Note:** Modify `git_manager.py` to support base64-encoded keys if using env var approach.

---

## Part 4: Verification Checklist

After setup, verify:

```bash
# 1. Check secret exists
kubectl get secret penguin-github-app -n penguin

# 2. Test secret mount in pod
kubectl run -it --rm debug --image=alpine --restart=Never -n penguin \
  --overrides='{"spec":{"volumes":[{"name":"gh-key","secret":{"secretName":"penguin-github-app"}}],"containers":[{"name":"debug","image":"alpine","command":["sh"],"volumeMounts":[{"name":"gh-key","mountPath":"/secrets","readOnly":true}]}]}}'

# Inside pod:
ls -la /secrets/
cat /secrets/github-app.pem | head -5
exit

# 3. Test App auth works
kubectl logs -n penguin deployment/penguin-web | grep -i "github.*auth\|installation.*token"
```

---

## Part 5: Security Best Practices

### DO:
- ✅ Use Kubernetes Secrets or external secret managers
- ✅ Mount PEM files read-only
- ✅ Rotate webhook secrets periodically
- ✅ Use operator-managed tokens with auto-refresh
- ✅ Limit App permissions to minimum required
- ✅ Enable webhook signature verification (`X-Hub-Signature-256`)
- ✅ Set up RBAC for Secret access

### DON'T:
- ❌ Commit PEM files to git
- ❌ Hardcode secrets in Dockerfiles/manifests
- ❌ Use overly broad GitHub App permissions
- ❌ Skip webhook signature validation
- ❌ Store secrets in ConfigMaps (use Secrets)
- ❌ Share App credentials across environments (dev vs prod)

---

## Part 6: GitHub App Installation URLs

After creating the App, get the installation URL:
```
https://github.com/apps/penguin-agent/installations/new
```

Or for orgs:
```
https://github.com/organizations/YOUR_ORG/settings/installations
```

---

## Quick Reference

### Environment Variables
```bash
GITHUB_APP_ID=1622624
GITHUB_APP_INSTALLATION_ID=<from installation URL>
GITHUB_APP_PRIVATE_KEY_PATH=/secrets/github-app.pem
GITHUB_REPOSITORY=owner/repo
GITHUB_WEBHOOK_SECRET=<your-webhook-secret>
```

### Get Installation ID

**Method 1: Use the test script (recommended)**
```bash
# This will list all installations and their IDs
python tests/api/test_github_app_auth.py
```

**Method 2: Via gh CLI**
```bash
# Install app, then:
curl -H "Authorization: Bearer $(gh auth token)" \
  https://api.github.com/app/installations
```

**Method 3: Check URL**
- Settings → Installations → <App> → URL (e.g., `/installations/123456`)

**Example output:**
```
✓ Found 1 installation(s)
  - Installation ID: 88065184, Account: Maximooch
```

Use the Installation ID shown above in your configuration.

---

## Troubleshooting

**"Bad credentials" error:**
- Check App ID and Installation ID match
- Verify PEM file is correctly mounted
- Ensure PEM hasn't been corrupted (check BEGIN/END lines)

**"Not installed" error:**
- Install the App on the target repo/org
- Verify Installation ID is correct

**"Permission denied":**
- Review App permissions in GitHub settings
- Ensure repo is accessible by the installation

**Secret mount issues:**
- Check Secret exists: `kubectl get secret <name> -n penguin`
- Verify volume mount in deployment.yaml
- Check pod logs for mount errors
