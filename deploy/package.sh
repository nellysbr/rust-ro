#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
revision=${1:-$(git rev-parse HEAD)}
[[ $revision =~ ^[a-f0-9]{40}$ ]] || { echo 'SHA invalido' >&2; exit 1; }
[[ -x target/release/server ]]
mkdir -p dist
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
install -m 755 target/release/server "$stage/server"
cp -a config "$stage/config"
cp native_functions_list.txt "$stage/"
printf '%s\n' "$revision" > "$stage/REVISION"
tar -czf "dist/ragzin-$revision.tar.gz" -C "$stage" server config native_functions_list.txt REVISION
