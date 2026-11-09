# Runpod GitHub build

Runpod can build from a connected GitHub repository automatically after a push. The Docker Hub publishing workflows described in the main README are another option.

**Manual action after each push:** Open the endpoint's build history in Runpod. Confirm that the build for the pushed commit is marked `Completed` and the endpoint uses that image before running jobs.

- **Dockerfile:** `Dockerfile` at repository root (default).
- **Target:** omit or set `final` (the last stage; that is what a plain `docker build` uses).

**Build arguments** (set in the Runpod template / build settings when not using pre-pushed Hub tags):

| Build argument | Default in Dockerfile | When to change |
| -------------- | --------------------- | ---------------- |
| `MODEL_TYPE` | `character-sheet` | Bundles animagine-xl-3.1, sdxl-vae-fp16-fix, 4x-UltraSharp, face_yolov8m. Use `sdxl`, `sd3`, `flux1-schnell`, or `flux1-dev` for other stacks. |
| `WITH_CHARACTER_SHEET_NODES` | `true` | Installs ComfyUI-MVAdapter + Impact Pack (required for character-sheet workflows). Set to `false` only if you want a slimmer image and will not run those nodes. |

For `MODEL_TYPE=sd3` or `flux1-dev`, supply `HUGGINGFACE_ACCESS_TOKEN` as a BuildKit secret. See `.env.example` for the variable name. Do not pass it as a build argument because build arguments can appear in image metadata.

A plain **`docker build`** (no args) targets the **character-sheet** model bundle plus MV-Adapter nodes. Allow enough **container build disk** (on the order of tens of GB). For **stock SDXL** weights only, pass **`--build-arg MODEL_TYPE=sdxl`**.
