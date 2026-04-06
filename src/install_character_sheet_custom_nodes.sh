#!/usr/bin/env bash
# ComfyUI nodes required by Anifusion character sheets (workflow.json):
# - ComfyUI-MVAdapter: LdmPipelineLoader, Diffusers*, multi-view sampling
# - ComfyUI-Impact-Pack: FaceDetailer, UltralyticsDetectorProvider
set -euo pipefail

mkdir -p /comfyui/custom_nodes
cd /comfyui/custom_nodes

if [[ ! -d ComfyUI-MVAdapter ]]; then
  git clone --depth 1 https://github.com/huanngzh/ComfyUI-MVAdapter.git
fi

if [[ ! -d ComfyUI-Impact-Pack ]]; then
  git clone --depth 1 --branch Main --single-branch \
    https://github.com/ltdrdata/ComfyUI-Impact-Pack.git
fi

pip install --no-cache-dir ultralytics

pip install --no-cache-dir -r /comfyui/custom_nodes/ComfyUI-MVAdapter/requirements.txt
pip install --no-cache-dir -r /comfyui/custom_nodes/ComfyUI-Impact-Pack/requirements.txt

echo "runpod-worker-comfy: character sheet custom nodes installed"
