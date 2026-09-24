#!/usr/bin/env bash
# Open the jodit-nodejs demo in headless Chrome against both connectors
# and record what the page asks and gets. Needs `make parity` first
# (for .cache/parity with node_modules) and Google Chrome.
#
# Usage: scripts/parity/run-demo.sh
set -euo pipefail

cd "$(dirname "$0")/../.."
REPO="$PWD"
WORK="$REPO/.cache/parity"
OUT="$WORK/demo-run"
mkdir -p "$OUT"
# ESM resolves puppeteer-core next to the script: run it from the checkout.
cp scripts/parity/demo.mjs "$WORK/demo.mjs"

if [ "$(uname -s)" = Darwin ]; then
    export DYLD_FALLBACK_LIBRARY_PATH="/opt/homebrew/lib:/usr/local/lib"
fi

pids=()
cleanup() {
    for pid in ${pids[@]+"${pids[@]}"}; do
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    done
}
trap cleanup EXIT

wait_for() {
    for _ in $(seq 1 100); do
        curl -s -o /dev/null "$1" && return 0
        sleep 0.2
    done
    echo "timeout waiting for $1" >&2
    return 1
}

run() {
    local name=$1
    local site="$OUT/site-$name"
    rm -rf "$site"
    mkdir -p "$site"
    cp -R "$WORK/demo" "$site/demo"
    cp -R "$WORK/files" "$site/files"
    (cd "$site" && exec python3 -m http.server 8080 --bind 127.0.0.1 \
        >/dev/null 2>&1) &
    pids+=($!)
    if [ "$name" = nodejs ]; then
        (cd "$site" && CONFIG_FILE="$WORK/demo.config.json" PORT=8081 \
            exec "$WORK/node_modules/.bin/tsx" "$WORK/src/run.ts" \
            >"$OUT/$name.log" 2>&1) &
    else
        (cd "$site" && CONFIG_FILE="$WORK/demo.config.json" PORT=8081 \
            HOST=127.0.0.1 exec uv run --project "$REPO" jcpy \
            >"$OUT/$name.log" 2>&1) &
    fi
    pids+=($!)
    wait_for http://127.0.0.1:8080/demo/index.html
    wait_for http://127.0.0.1:8081/ping
    (cd "$WORK" && UPLOAD_FILE="$WORK/files/regina.png" node demo.mjs \
        http://localhost:8080/demo/index.html http://localhost:8081 \
        "$OUT/$name")
    cleanup
    pids=()
    sleep 1
}

run nodejs
run python
echo "results in $OUT (nodejs.json, python.json, *.png)"
