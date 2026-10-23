#!/usr/bin/env bash
# Download the pretrained model bundle (built by the Data bundle workflow) into ./models
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -f models/whisper/model.bin ]; then echo "models already present"; exit 0; fi
url="https://github.com/rthawani1209/Lecturelens/releases/download/models-v1/models.tar.gz"
curl -fL --retry 3 "$url" | tar -xz
rm -rf models/*/.cache
du -sh models/*
