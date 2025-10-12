# Phase 2.5 GitHub App Configuration Guide

## Overview
This guide covers the GitHub App configuration needed to implement Phase 2.5 (Bot Features: mentions, webhooks, and hooks).

**Current Status:** Phase 2 complete (basic PR/commit creation working)
**Goal:** Enable @Penguin mentions, webhook events, and status checks

---

## Part 1: GitHub App Settings (Manual Configuration)

### Step 1: Navigate to Your App Settings
```
https://github.com/settings/apps/penguin-agent
```
Or: Settings → Developer settings → GitHub Apps → Penguin Agent

### Step 2: Update Repository Permissions

**Currently configured (Phase 2):**
- ✅ Contents: Read & write
- ✅ Pull requests: Read & write
- ✅ Metadata: Read-only

**Add these permissions for Phase 2.5:**
- **Issues: Read & write** ← Enable @Penguin mentions in issues
- **Checks: Read & write** ← Enable status checks (penguin/review, penguin/tests)
- **Workflows: Read & write** ← (Optional) For GitHub Actions modifications

### Step 3: Subscribe to Webhook Events

Click "Subscribe to events" and enable:
- ✅ `push` (may already be enabled)
- **`issue_comment`** ← Required for @Penguin mentions in PR/issue comments
- **`pull_request`** ← Required for PR lifecycle events
- **`pull_request_review`** ← Required for review submissions
- **`pull_request_review_comment`** ← Required for review comments

### Step 4: Configure Webhook

**Generate webhook secret:**
```bash
openssl rand -hex 32
```
Save this value securely (e.g., password manager or `~/.penguin/secrets/webhook-secret.txt`)

**Set webhook URL:**
```
https://your-domain.com/api/v1/integrations/github/webhook
```

**For local testing with ngrok:**
```bash
ngrok http 8000
# Use the HTTPS URL: https://abc123.ngrok.io/api/v1/integrations/github/webhook
```

**Or leave blank** if you don't have a public endpoint yet (can add later)

---

## Part 2: Environment Variables

### Add to your environment (Docker/Kubernetes):

```bash
# Existing Phase 2 variables (already configured)
GITHUB_APP_ID=1622624
GITHUB_APP_INSTALLATION_ID=88065184
GITHUB_APP_PRIVATE_KEY_PATH=/secrets/github-app.pem
GITHUB_REPOSITORY=Maximooch/penguin

# New for Phase 2.5
GITHUB_WEBHOOK_SECRET=<your-generated-secret-from-step-4>
```

### Docker example:
```bash
docker run --rm -p 8000:8000 \
  --env-file .env \
  -e GITHUB_APP_ID=1622624 \
  -e GITHUB_APP_INSTALLATION_ID=88065184 \
  -e GITHUB_APP_PRIVATE_KEY_PATH=/secrets/github-app.pem \
  -e GITHUB_REPOSITORY=Maximooch/penguin \
  -e GITHUB_WEBHOOK_SECRET=<your-secret> \
  -v ~/.penguin/secrets/github-app.pem:/secrets/github-app.pem:ro \
  penguin:web-local
```

---

## Part 3: Configuration File Updates

### Add to `.penguin/config.yml`:

```yaml
github:
  webhook:
    enabled: true
    secret_env: "GITHUB_WEBHOOK_SECRET"
    # Allowed repositories (for security)
    allowed_repos:
      - "Maximooch/penguin"
      - "Maximooch/penguin-test-repo"
    # Optional: allowed organizations for org-wide installs
    # allowed_orgs:
    #   - "your-org-name"

  bot:
    # Trigger for bot commands
    mention_trigger: "@Penguin"

    # Enabled commands in PR/issue comments
    enabled_commands:
      - "review"        # @Penguin review
      - "fix tests"     # @Penguin fix tests
      - "plan"          # @Penguin plan
      - "summarize"     # @Penguin summarize

    # Require explicit opt-in label before taking write actions
    require_label: "penguin:auto"

    # Optional: restrict to specific users/teams
    # allowed_users:
    #   - "Maximooch"
    # allowed_teams:
    #   - "core-devs"

  checks:
    # Enable GitHub Checks API integration
    enabled: true

    # Check names to publish
    check_names:
      - "penguin/review"
      - "penguin/tests"
      - "penguin/plan"
      - "penguin/validate"

  labels:
    # Auto-apply labels based on outcomes
    enabled: true
    label_map:
      needs_input: "penguin:needs-input"
      automated: "penguin:auto"
      reviewed: "penguin:reviewed"
```

---

## Part 4: Code Implementation Status

### ✅ Already Implemented
- GitHub App authentication
- Installation token generation
- PR creation
- Branch/commit operations

### 🚧 To Be Implemented
- [ ] Webhook endpoint (`POST /api/v1/integrations/github/webhook`)
- [ ] Signature verification (`X-Hub-Signature-256`)
- [ ] Event routing (issue_comment, pull_request, etc.)
- [ ] @Penguin mention detection
- [ ] Command parser (review, fix tests, plan)
- [ ] Checks API integration
- [ ] Hooks system (pre/post actions)
- [ ] Label automation

---

## Part 5: Verification Checklist

### GitHub App Configuration
- [ ] Issues permission: Read & write
- [ ] Checks permission: Read & write
- [ ] Event subscription: `issue_comment`
- [ ] Event subscription: `pull_request`
- [ ] Event subscription: `pull_request_review`
- [ ] Event subscription: `pull_request_review_comment`
- [ ] Webhook secret generated and saved
- [ ] Webhook URL configured (or ready for ngrok)

### Environment Setup
- [ ] `GITHUB_WEBHOOK_SECRET` added to environment
- [ ] All Phase 2 variables still present
- [ ] Config.yml updated with webhook/bot settings

### Testing Plan
1. **Webhook delivery test:**
   - Create a PR in test repo
   - Check webhook deliveries in GitHub App settings
   - Verify signature validation passes

2. **@Penguin mention test:**
   - Comment `@Penguin review` on a PR
   - Verify webhook received and processed
   - Check response comment posted

3. **Checks API test:**
   - Trigger a review command
   - Verify check run created (penguin/review)
   - Check status updates appear in PR

---

## Part 6: Security Considerations

### Webhook Security
- ✅ Always verify `X-Hub-Signature-256` header
- ✅ Use constant-time comparison for signature validation
- ✅ Validate webhook payloads against schema
- ✅ Check event is from allowed repos/orgs
- ✅ Implement rate limiting on webhook endpoint

### Permission Model
- ✅ Require `penguin:auto` label for write operations
- ✅ Limit commands based on user permissions in repo
- ✅ Never execute arbitrary code from comments
- ✅ Sandbox tool execution (align with existing parity model)

### Token Handling
- ✅ Installation tokens auto-expire (1 hour)
- ✅ Refresh tokens as needed
- ✅ Never log tokens or PEM contents
- ✅ Use read-only volume mounts for secrets

---

## Quick Reference

### Current App Details
- **App ID:** 1622624
- **Installation ID:** 88065184 (Maximooch account)
- **Installed repos:** Maximooch/penguin
- **PEM location:** `~/.penguin/secrets/github-app.pem`

### Webhook Event Payloads
```json
// issue_comment event
{
  "action": "created",
  "issue": { "number": 1, "pull_request": {} },
  "comment": {
    "body": "@Penguin review this PR",
    "user": { "login": "Maximooch" }
  },
  "repository": { "full_name": "Maximooch/penguin" }
}

// pull_request event
{
  "action": "opened",
  "pull_request": { "number": 1, "title": "..." },
  "repository": { "full_name": "Maximooch/penguin" }
}
```

### Useful GitHub API Endpoints
```python
# Create check run
POST /repos/{owner}/{repo}/check-runs
{
  "name": "penguin/review",
  "head_sha": "abc123",
  "status": "in_progress"
}

# Create issue comment
POST /repos/{owner}/{repo}/issues/{number}/comments
{
  "body": "Review complete! ✅"
}

# Add labels
POST /repos/{owner}/{repo}/issues/{number}/labels
{
  "labels": ["penguin:reviewed"]
}
```

---

## Next Steps

1. **Configure GitHub App** (manual steps in Part 1)
2. **Set environment variables** (Part 2)
3. **Update config.yml** (Part 3)
4. **Implement webhook endpoint** (code implementation)
5. **Test with ngrok** (local verification)
6. **Deploy to production** (with proper webhook URL)

---

## Troubleshooting

**Webhook not receiving events:**
- Check webhook deliveries in GitHub App settings
- Verify URL is publicly accessible
- Check webhook secret matches environment variable

**Signature validation failing:**
- Ensure webhook secret exactly matches
- Check you're reading raw request body (not parsed JSON)
- Verify HMAC algorithm is SHA-256

**Permission denied errors:**
- Review app permissions in GitHub settings
- Check installation has access to the repo
- Verify app is installed on the correct account/org

**@Penguin not responding:**
- Check webhook event was delivered
- Verify mention detection regex
- Check logs for errors in command parsing

---

## References

- [GitHub Apps Documentation](https://docs.github.com/en/apps)
- [Webhook Events](https://docs.github.com/en/webhooks/webhook-events-and-payloads)
- [Checks API](https://docs.github.com/en/rest/checks)
- [Phase 2 Setup Guide](./GITHUB_APP_SETUP.md)
- [Penguin Containers TODO](../context/penguin_todo_container.md)
