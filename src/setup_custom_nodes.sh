#!/usr/bin/env bash

set -e

#echo "runpod-worker-comfy: updating"
#comfy --workspace /comfyui node update all

echo "runpod-worker-comfy: installing ComfyUI-Impact-Pack"
#comfy --workspace /comfyui node install ComfyUI-Impact-Pack
git clone https://github.com/ltdrdata/ComfyUI-Impact-Pack /comfyui/custom_nodes/ComfyUI-Impact-Pack
pip install -r /comfyui/custom_nodes/ComfyUI-Impact-Pack/requirements.txt

echo "runpod-worker-comfy: installing ComfyUI-Impact-Subpack"
#comfy --workspace /comfyui node install ComfyUI-Impact-Subpack
git clone https://github.com/ltdrdata/ComfyUI-Impact-Subpack /comfyui/custom_nodes/ComfyUI-Impact-Subpack
pip install -r /comfyui/custom_nodes/ComfyUI-Impact-Subpack/requirements.txt


echo "runpod-worker-comfy: installing ComfyUI-Impact-MVAdapter"
git clone https://github.com/huanngzh/ComfyUI-MVAdapter /comfyui/custom_nodes/ComfyUI-MVAdapter
pip install -r /comfyui/custom_nodes/ComfyUI-MVAdapter/requirements.txt
#comfy --workspace /comfyui node install ComfyUI-MVAdapter

echo "runpod-worker-comfy: done installing additional nodes"
