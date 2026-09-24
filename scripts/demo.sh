#!/usr/bin/env bash
# Serve demo/index.html (Jodit PRO file browser) with this connector and
# open it in the browser (NO_BROWSER=1 to skip).
#
#   http://localhost:8080/demo/  page and uploaded files (./files)
#   http://localhost:8081/       connector (demo/config.json)
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p files
PAGE="http://localhost:8080/demo/"

# macOS strips DYLD_* when starting /bin/bash: set the WeasyPrint path here.
if [ "$(uname -s)" = Darwin ]; then
    export DYLD_FALLBACK_LIBRARY_PATH="/opt/homebrew/lib:/usr/local/lib"
fi

pids=()
cleanup() {
    for pid in ${pids[@]+"${pids[@]}"}; do
        kill "$pid" 2>/dev/null || true
    done
}
trap cleanup EXIT INT TERM

uv run python -m http.server 8080 --bind 127.0.0.1 >/dev/null 2>&1 &
pids+=($!)
CONFIG_FILE=demo/config.json HOST=127.0.0.1 PORT=8081 uv run jcpy &
pids+=($!)

# Open the page once the connector answers.
for _ in $(seq 1 100); do
    curl -s -o /dev/null http://127.0.0.1:8081/ping && break
    sleep 0.2
done
echo "Demo: $PAGE (Ctrl+C to stop)"
if [ -z "${NO_BROWSER:-}" ]; then
    if command -v open >/dev/null && [ "$(uname -s)" = Darwin ]; then
        open "$PAGE"
    elif command -v xdg-open >/dev/null; then
        xdg-open "$PAGE" >/dev/null 2>&1 || true
    fi
fi

wait
