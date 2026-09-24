#!/usr/bin/env bash
# Serve demo/index.html (real Jodit editor) with this connector.
#
#   http://localhost:8080/demo/  page and uploaded files (./files)
#   http://localhost:8081/       connector (demo/config.json)
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p files

# macOS strips DYLD_* when starting /bin/bash: set the WeasyPrint path here.
if [ "$(uname -s)" = Darwin ]; then
    export DYLD_FALLBACK_LIBRARY_PATH="/opt/homebrew/lib:/usr/local/lib"
fi

uv run python -m http.server 8080 --bind 127.0.0.1 >/dev/null 2>&1 &
STATIC=$!
trap 'kill $STATIC 2>/dev/null' EXIT

echo "Open http://localhost:8080/demo/ (Ctrl+C to stop)"
CONFIG_FILE=demo/config.json HOST=127.0.0.1 PORT=8081 uv run jcpy
