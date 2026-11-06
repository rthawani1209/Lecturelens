#!/usr/bin/env bash
# Download the models into ./models from this repo's releases:
#   models-v1    whisper, MiniLM, CLIP (built by the Data bundle workflow)
#   tagger-v1    the frame tagger trained in ml/tagger, for TF Serving
#   reranker-v1  the re-ranker, built from the committed weights (Publish re-ranker workflow)
# TF Serving only starts once both of its models are here.
set -euo pipefail
cd "$(dirname "$0")/.."
releases="https://github.com/rthawani1209/Lecturelens/releases/download"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# whole file first, then unpack, so a dropped connection never leaves half a model
fetch() {
  curl -fsSL --retry 3 -o "$tmp/$2" "$releases/$1/$2" && tar -xzf "$tmp/$2" && rm "$tmp/$2"
}

if [ -f models/whisper/model.bin ]; then
  echo "pretrained models already present"
else
  fetch models-v1 models.tar.gz
  rm -rf models/*/.cache
fi

if ls models/tagger/*/saved_model.pb >/dev/null 2>&1; then
  echo "tagger already present"
else
  fetch tagger-v1 tagger.tar.gz
fi

if ls models/reranker/*/saved_model.pb >/dev/null 2>&1; then
  echo "re-ranker already present"
else
  fetch reranker-v1 reranker.tar.gz
fi
du -sh models/*
