#!/bin/bash
# Test script for GitHub webhook locally

WEBHOOK_SECRET="${GITHUB_WEBHOOK_SECRET}"
if [ -z "$WEBHOOK_SECRET" ]; then
    echo "Error: GITHUB_WEBHOOK_SECRET not set"
    exit 1
fi

# Test payload (issue_comment event with @Penguin mention)
PAYLOAD='{
  "action": "created",
  "issue": {
    "number": 1,
    "title": "Test Issue",
    "pull_request": {}
  },
  "comment": {
    "body": "@Penguin review this is just a test issue comment. Just acknowledge it.",
    "user": {
      "login": "testuser"
    }
  },
  "repository": {
    "full_name": "Maximooch/penguin"
  },
  "sender": {
    "login": "testuser"
  }
}'

# Calculate signature
SIGNATURE=$(echo -n "$PAYLOAD" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" | sed 's/^.* //')

# Send webhook
echo "Sending test webhook..."
curl -X POST http://localhost:8000/api/v1/integrations/github/webhook \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: issue_comment" \
  -H "X-Hub-Signature-256: sha256=$SIGNATURE" \
  -d "$PAYLOAD"

echo ""
echo "Check Docker logs: docker logs -f penguin-web"
