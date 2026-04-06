# Optional ComfyUI Manager snapshots

Place `*_snapshot*.json` files here if you use [ComfyUI Manager snapshot restore](https://github.com/ltdrdata/ComfyUI-Manager#snapshot-manager) during the Docker build. At most one file matching `*snapshot*.json` is copied to `/` and applied by `restore_snapshot.sh`.

If this directory has no snapshot JSON, the build skips restoration (exit 0).

Character sheets (Anifusion) rely on `install_character_sheet_custom_nodes.sh` plus the `character-sheet` bake target, not on a snapshot.
