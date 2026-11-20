#!/usr/bin/env bash
# Download the Kokoro v1.0 ONNX voice files into .models/kokoro/ for the optional local
# neural narration voice (REPOVOX_TTS_PROVIDER=kokoro_onnx). Idempotent: verified files are
# kept, anything else is downloaded again. Nothing here runs in CI, and nothing is committed:
# .models/ is git-ignored.
#
# Source: the official thewh1teagle/kokoro-onnx release "model-files-v1.0" (2025-01-28).
# Licences: kokoro-onnx is MIT; the Kokoro-82M model weights are Apache-2.0 (hexgrad).
# Integrity: the release publishes each file's exact size, which is checked. The SHA-256
# values below were recorded from that release on 2026-11-20 (the release publishes no
# digests), so a later download must match the reviewed bytes exactly.
#
# Usage: bash scripts/setup_kokoro_voice.sh [--check]
#   --check  verify the files already present; download nothing.
set -euo pipefail

RELEASE="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${REPOVOX_KOKORO_DIR:-$ROOT/.models/kokoro}"
# name|exact bytes|sha256
FILES=(
  "kokoro-v1.0.onnx|325532387|7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5"
  "voices-v1.0.bin|28214398|bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d"
)
CHECK_ONLY=false
if [[ "${1:-}" == "--check" ]]; then
  CHECK_ONLY=true
elif [[ $# -gt 0 ]]; then
  echo "usage: bash scripts/setup_kokoro_voice.sh [--check]" >&2
  exit 2
fi

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  else
    shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

size_of() {
  wc -c <"$1" | tr -d ' '
}

# Prints nothing and succeeds only when the file has the exact size, digest and format.
verified() {
  local path="$1" bytes="$2" digest="$3"
  [[ -f "$path" && ! -L "$path" ]] || return 1
  [[ "$(size_of "$path")" == "$bytes" ]] || return 1
  [[ "$(sha256 "$path")" == "$digest" ]] || return 1
  if [[ "$path" == *.bin ]]; then
    # The voices file is a NumPy .npz archive: a ZIP local-file header.
    [[ "$(head -c 4 "$path" | od -An -tx1 | tr -d ' \n')" == "504b0304" ]] || return 1
  fi
}

mkdir -p "$TARGET"
status=0
for entry in "${FILES[@]}"; do
  IFS='|' read -r name bytes digest <<<"$entry"
  path="$TARGET/$name"
  if verified "$path" "$bytes" "$digest"; then
    echo "ok        $name ($bytes bytes, sha256 ${digest:0:12}...)"
    continue
  fi
  if [[ "$CHECK_ONLY" == true ]]; then
    echo "missing   $name (absent or not the reviewed bytes)" >&2
    status=1
    continue
  fi
  echo "download  $name"
  part="$path.part"
  rm -f "$part"
  curl --fail --location --proto '=https' --tlsv1.2 --retry 3 --retry-delay 2 \
    --max-filesize $((bytes + 1)) --silent --show-error --output "$part" "$RELEASE/$name"
  if ! verified "$part" "$bytes" "$digest"; then
    echo "rejected  $name: size $(size_of "$part"), sha256 $(sha256 "$part")" >&2
    rm -f "$part"
    exit 1
  fi
  mv -f "$part" "$path"
  echo "ok        $name ($bytes bytes, sha256 ${digest:0:12}...)"
done
if [[ "$status" -ne 0 ]]; then
  exit "$status"
fi

cat <<EOF
Kokoro v1.0 voice ready in $TARGET
Enable it in the self-hosted stack with the neural voice overlay:
  docker compose -f docker-compose.yml -f infrastructure/local/docker-compose.prod.yml \\
    -f infrastructure/local/docker-compose.neural-tts.yml up -d --build --wait
EOF
