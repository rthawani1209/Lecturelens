#!/usr/bin/env bash
# Download the models into ./models from this repo's releases:
#   models-v1  whisper, MiniLM, CLIP (built by the Data bundle workflow)
#   tagger-v1  the frame tagger trained in ml/tagger, for TF Serving
set -euo pipefail
cd "$(dirname "$0")/.."
releases="https://github.com/rthawani1209/Lecturelens/releases/download"

if [ -f models/whisper/model.bin ]; then
  echo "pretrained models already present"
else
  curl -fL --retry 3 "$releases/models-v1/models.tar.gz" | tar -xz
  rm -rf models/*/.cache
fi

if ls models/tagger/*/saved_model.pb >/dev/null 2>&1; then
  echo "tagger already present"
elif curl -fsL --retry 3 -o /tmp/tagger.tar.gz "$releases/tagger-v1/tagger.tar.gz"; then
  tar -xzf /tmp/tagger.tar.gz && rm /tmp/tagger.tar.gz
else
  # the worker falls back to the CLIP probe, so this isn't fatal
  echo "warning: couldn't download the tagger; frames will be tagged with the CLIP probe"
fi
du -sh models/*
