#!/usr/bin/env bash
# Run the jodit-nodejs test suite against jodit-python.
#
# Usage: scripts/parity/run.sh [path/to/jodit-nodejs] [jest args...]
# The nodejs checkout is copied to .cache/parity; it is not modified.
set -euo pipefail

cd "$(dirname "$0")/../.."
NODEJS=$(cd "${1:-../jodit-nodejs}" && pwd)
shift || true
WORK="$PWD/.cache/parity"
PORT="${PARITY_PORT:-8099}"

# macOS strips DYLD_* when starting /bin/bash: set the WeasyPrint path here.
if [ "$(uname -s)" = Darwin ]; then
    export DYLD_FALLBACK_LIBRARY_PATH="/opt/homebrew/lib:/usr/local/lib"
fi

mkdir -p "$WORK"
rsync -a --delete --exclude node_modules --exclude dist --exclude .git \
    "$NODEJS/" "$WORK/"
cp scripts/parity/test-server.ts "$WORK/src/tests/test-server.ts"

if [ ! -d "$WORK/node_modules" ] \
    || [ "$WORK/package.json" -nt "$WORK/node_modules" ]; then
    (cd "$WORK" && PUPPETEER_SKIP_DOWNLOAD=1 npm install --ignore-scripts \
        --no-audit --no-fund --silent)
fi

# Relative source roots in the tests resolve against the test checkout.
(cd "$WORK" && exec uv run --project "$OLDPWD" python \
    "$OLDPWD/scripts/parity/server.py" "$PORT") &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT
for _ in $(seq 1 50); do
    curl -s -o /dev/null "http://127.0.0.1:$PORT/" && break
    kill -0 $SERVER 2>/dev/null || { echo "control server died" >&2; exit 1; }
    sleep 0.2
done

cd "$WORK"
PARITY_SERVER="http://127.0.0.1:$PORT" \
NODE_OPTIONS='--experimental-vm-modules' \
    npx jest --runInBand --json --outputFile="$WORK/results.json" "$@" \
    >"$WORK/jest.log" 2>&1 || true
echo "results: $WORK/results.json (log: $WORK/jest.log)"
