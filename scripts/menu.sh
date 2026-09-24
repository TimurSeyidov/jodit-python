#!/usr/bin/env bash
# Interactive menu built from the "## description" comments in Makefile.
set -euo pipefail

cd "$(dirname "$0")/.."

targets=()
descriptions=()
while IFS=$'\t' read -r target description; do
    [[ "$target" == "menu" ]] && continue
    targets+=("$target")
    descriptions+=("$description")
done < <(
    grep -E '^[a-zA-Z_-]+:[^#]*## .*$' Makefile \
        | sed -E 's/^([a-zA-Z_-]+):[^#]*## (.*)$/\1\t\2/'
)

echo "jodit-python - choose a command (q to quit)"
echo
for i in "${!targets[@]}"; do
    printf "  \033[36m%2d)\033[0m %-14s %s\n" \
        "$((i + 1))" "${targets[$i]}" "${descriptions[$i]}"
done
echo

read -r -p "> " choice
[[ "$choice" == "q" || -z "$choice" ]] && exit 0

if [[ "$choice" =~ ^[0-9]+$ ]] \
    && ((choice >= 1 && choice <= ${#targets[@]})); then
    exec make "${targets[$((choice - 1))]}"
fi

echo "Unknown choice: $choice" >&2
exit 1
