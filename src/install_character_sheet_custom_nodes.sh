#!/usr/bin/env bash
# ComfyUI nodes required by Anifusion character sheets (workflow.json):
# - ComfyUI-MVAdapter: LdmPipelineLoader, Diffusers*, multi-view sampling
# - ComfyUI-Impact-Pack: FaceDetailer, UltralyticsDetectorProvider
#
# Impact Pack `Main` (e.g. 8.28+) uses comfy.samplers.SCHEDULER_HANDLERS, which does not exist on
# ComfyUI 0.2.7 (comfy-cli --version 0.2.7) — import fails with AttributeError and FaceDetailer
# never registers. Pin COMFYUI_IMPACT_PACK_REF to tag 8.9 (or similar) for 0.2.7; bump ComfyUI
# before tracking Impact Main again.
#
# Install order: Impact Pack *before* MVAdapter pip deps, then MVAdapter requirements *last*.
# Impact Pack lists unpinned "transformers" etc.; installing it after MVAdapter can override
# MVAdapter's pins (transformers==4.46.3, diffusers==0.31.0) and break imports — see
# https://github.com/huanngzh/ComfyUI-MVAdapter/issues/49 (wrong diffusers → missing diffusers.callbacks).
set -euo pipefail

PY="python3 -m pip"
mkdir -p /comfyui/custom_nodes
cd /comfyui/custom_nodes

# Optional: set COMFYUI_MV_ADAPTER_REF at build time (e.g. v1.0.2) for reproducible builds vs ComfyUI 0.2.7.
# Default: shallow clone of default branch (currently main).
MV_REF="${COMFYUI_MV_ADAPTER_REF:-}"
if [[ ! -d ComfyUI-MVAdapter ]]; then
  if [[ -n "$MV_REF" ]]; then
    git clone --depth 1 --branch "$MV_REF" --single-branch \
      https://github.com/huanngzh/ComfyUI-MVAdapter.git
  else
    git clone --depth 1 https://github.com/huanngzh/ComfyUI-MVAdapter.git
  fi
fi

# Default 8.9 via Dockerfile ARG; use Main only with a newer ComfyUI than 0.2.7.
IMPACT_REF="${COMFYUI_IMPACT_PACK_REF:-8.9}"
if [[ ! -d ComfyUI-Impact-Pack ]]; then
  git clone --depth 1 --branch "$IMPACT_REF" --single-branch \
    https://github.com/ltdrdata/ComfyUI-Impact-Pack.git
fi

$PY install --no-cache-dir ultralytics

# Impact Pack first — may upgrade transformers; MVAdapter reinstalls pins next.
$PY install --no-cache-dir -r /comfyui/custom_nodes/ComfyUI-Impact-Pack/requirements.txt

# MVAdapter last so diffusers==0.31.0, transformers==4.46.3, huggingface_hub==0.24.6 win.
$PY install --no-cache-dir -r /comfyui/custom_nodes/ComfyUI-MVAdapter/requirements.txt

# Fail the image build if MVAdapter's diffusers stack is broken (common silent runtime failure).
python3 - <<'PY'
import diffusers
import transformers
from diffusers.callbacks import PipelineCallback, MultiPipelineCallbacks  # noqa: F401

print(
    "runpod-worker-comfy: MVAdapter stack OK — diffusers",
    diffusers.__version__,
    "transformers",
    transformers.__version__,
)
PY

echo "runpod-worker-comfy: character sheet custom nodes installed"
