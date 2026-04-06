#!/usr/bin/env bash
# Run from Terminal.app (not required to be in this repo). Waits for Docker, then prunes cache + dangling images.
set -euo pipefail

open -a Docker 2>/dev/null || true

SOCK="${HOME}/.docker/run/docker.sock"
echo "Waiting for Docker socket: $SOCK (up to 5 minutes)..."
for i in $(seq 1 150); do
  if [[ -S "$SOCK" ]]; then
    echo "Socket ready (${i}x2s)."
    break
  fi
  sleep 2
done

if [[ ! -S "$SOCK" ]]; then
  echo "ERROR: Docker never exposed a socket. Open Docker Desktop, finish startup, then retry."
  echo "If it stays broken: Docker Desktop → Troubleshoot → Restart, or check disk space."
  exit 1
fi

docker context use desktop-linux 2>/dev/null || true
docker info >/dev/null

echo "=== docker builder prune -af ==="
docker builder prune -af

echo "=== docker buildx prune -af ==="
docker buildx prune -af 2>/dev/null || true

echo "=== docker image prune -f (dangling) ==="
docker image prune -f

echo "=== docker system df ==="
docker system df

echo "Done."
