#!/usr/bin/env bash
# Runs before ComfyUI starts; output goes to container stdout (visible in RunPod worker logs).
set -u
echo "runpod-worker-comfy: === custom_nodes directories (pre-Comfy) ==="
if [ ! -d /comfyui/custom_nodes ]; then
  echo "runpod-worker-comfy: ERROR: /comfyui/custom_nodes does not exist"
  exit 0
fi
find /comfyui/custom_nodes -maxdepth 1 -mindepth 1 -type d 2>/dev/null | sort | while read -r p; do
  echo "runpod-worker-comfy:   $(basename "$p")"
done
for name in ComfyUI-MVAdapter ComfyUI-Impact-Pack ComfyUI-Impact-Subpack; do
  if [ -d "/comfyui/custom_nodes/$name" ]; then
    echo "runpod-worker-comfy: OK directory: $name"
  else
    echo "runpod-worker-comfy: MISSING directory: $name"
  fi
done
echo "runpod-worker-comfy: === pip versions (MVAdapter-related) ==="
for pkg in diffusers transformers torch huggingface-hub; do
  if pip show "$pkg" >/dev/null 2>&1; then
    ver=$(pip show "$pkg" | awk -F': ' '/^Version:/{print $2; exit}')
    echo "runpod-worker-comfy:   $pkg==$ver"
  else
    echo "runpod-worker-comfy:   $pkg (not installed)"
  fi
done
echo "runpod-worker-comfy: === end custom_nodes diagnostics ==="
