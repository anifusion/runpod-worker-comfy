variable "DOCKERHUB_REPO" {
  default = "timpietruskyblibla"
}

variable "DOCKERHUB_IMG" {
  default = "runpod-worker-comfy"
}

variable "RELEASE_VERSION" {
  default = "latest"
}

group "default" {
  targets = ["base", "sdxl", "sd3", "flux1-schnell", "flux1-dev", "character-sheet"]
}

target "base" {
  context = "."
  dockerfile = "Dockerfile"
  target = "base"
  platforms = ["linux/amd64"]
  tags = ["${DOCKERHUB_REPO}/${DOCKERHUB_IMG}:${RELEASE_VERSION}-base"]
}

target "sdxl" {
  context = "."
  dockerfile = "Dockerfile"
  target = "final"
  args = {
    MODEL_TYPE = "sdxl"
  }
  tags = ["${DOCKERHUB_REPO}/${DOCKERHUB_IMG}:${RELEASE_VERSION}-sdxl"]
  inherits = ["base"]
}

target "sd3" {
  context = "."
  dockerfile = "Dockerfile"
  target = "final"
  args = {
    MODEL_TYPE = "sd3"
  }
  secret = ["id=HUGGINGFACE_ACCESS_TOKEN,env=HUGGINGFACE_ACCESS_TOKEN"]
  tags = ["${DOCKERHUB_REPO}/${DOCKERHUB_IMG}:${RELEASE_VERSION}-sd3"]
  inherits = ["base"]
}

target "flux1-schnell" {
  context = "."
  dockerfile = "Dockerfile"
  target = "final"
  args = {
    MODEL_TYPE = "flux1-schnell"
  }
  tags = ["${DOCKERHUB_REPO}/${DOCKERHUB_IMG}:${RELEASE_VERSION}-flux1-schnell"]
  inherits = ["base"]
}

target "flux1-dev" {
  context = "."
  dockerfile = "Dockerfile"
  target = "final"
  args = {
    MODEL_TYPE = "flux1-dev"
  }
  secret = ["id=HUGGINGFACE_ACCESS_TOKEN,env=HUGGINGFACE_ACCESS_TOKEN"]
  tags = ["${DOCKERHUB_REPO}/${DOCKERHUB_IMG}:${RELEASE_VERSION}-flux1-dev"]
  inherits = ["base"]
}

# Character sheets: MV-Adapter + Impact Pack + animagine-xl / upscaler / face detector (~7GB+ checkpoint)
# WITH_CHARACTER_SHEET_NODES defaults to true in Dockerfile; kept explicit for clarity.
target "character-sheet" {
  context = "."
  dockerfile = "Dockerfile"
  target = "final"
  args = {
    MODEL_TYPE                 = "character-sheet"
    WITH_CHARACTER_SHEET_NODES   = "true"
  }
  tags = ["${DOCKERHUB_REPO}/${DOCKERHUB_IMG}:${RELEASE_VERSION}-character-sheet"]
  inherits = ["base"]
}
