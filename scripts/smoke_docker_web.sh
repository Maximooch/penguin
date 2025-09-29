#!/usr/bin/env bash
set -euo pipefail

IMAGE=${1:-penguin:web}
ENV_FILE=${2:-.env}
env_args=()
if [[ -f "$ENV_FILE" ]]; then
  echo "Loading env from $ENV_FILE"
  env_args=(--env-file "$ENV_FILE")
fi

cid=""
cleanup() {
  if [[ -n "$cid" ]]; then
    docker rm -f "$cid" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo "Starting $IMAGE ..."
cid=$(docker run -d -p 18000:8000 "${env_args[@]}" "$IMAGE")

echo "Waiting for health..."
for i in {1..30}; do
  if curl -fsS http://127.0.0.1:18000/api/v1/health >/dev/null; then
    echo "Healthy"
    curl -s http://127.0.0.1:18000/api/v1/health | jq . || true
    exit 0
  fi
  sleep 1
done

echo "Health check failed"
docker logs "$cid" || true
exit 1


