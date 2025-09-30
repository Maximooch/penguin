#!/usr/bin/env bash
set -euo pipefail

MODEL=${1:-openai/gpt-5}
PROVIDER=${2:-openrouter}

echo "Starting container with $PROVIDER/$MODEL..."
docker rm -f penguin-test 2>/dev/null || true

docker run --rm -d -p 8000:8000 \
  --env-file .env \
  -e PENGUIN_DEFAULT_MODEL="$MODEL" \
  -e PENGUIN_DEFAULT_PROVIDER="$PROVIDER" \
  -e PENGUIN_CLIENT_PREFERENCE="$PROVIDER" \
  -e PENGUIN_DEBUG="1" \
  -e PENGUIN_WORKSPACE="/home/penguinuser/penguin_workspace" \
  --name penguin-test \
  penguin:web-local

echo "Waiting for health..."
for i in {1..30}; do
  if curl -fsS http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1; then
    echo "Server ready"
    break
  fi
  sleep 1
done

echo -e "\n=== Sending chat request ==="
curl -X POST http://localhost:8000/api/v1/chat/message \
  -H "Content-Type: application/json" \
  -d '{"text":"What is 2+2? Reply with just the number."}' \
  2>/dev/null | jq -r '.response // .assistant_response // .error // .'

echo -e "\n=== Container logs (looking for LLM calls) ==="
docker logs penguin-test 2>&1 | grep -i "litellm\|api.*call\|completion\|request.*model" || echo "No LLM call logs found"

echo -e "\n=== Full logs (last 50 lines) ==="
docker logs penguin-test 2>&1 | tail -50

echo -e "\nCleaning up..."
docker rm -f penguin-test