#!/usr/bin/env bash
# Tests `forge init` sample handling: the default keeps the .forge-samples files, and --no-sample removes them.
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
export GIT_AUTHOR_NAME=forge GIT_AUTHOR_EMAIL=forge@localhost GIT_COMMITTER_NAME=forge GIT_COMMITTER_EMAIL=forge@localhost
fail() { echo "INIT TEST FAIL: $*"; exit 1; }
for preset in godot-csharp godot; do
  "$here/bin/forge" init "$tmp/$preset-keep" --preset "$preset" >/dev/null
  "$here/bin/forge" init "$tmp/$preset-clean" --preset "$preset" --no-sample >/dev/null
  [ -f "$tmp/$preset-keep/.forge-samples" ] || fail "$preset: manifest missing by default"
  [ ! -e "$tmp/$preset-clean/.forge-samples" ] || fail "$preset: manifest kept with --no-sample"
  while read -r rel; do
    case $rel in ''|'#'*) continue ;; esac
    [ -f "$tmp/$preset-keep/$rel" ] || fail "$preset: sample $rel missing by default"
    [ ! -e "$tmp/$preset-clean/$rel" ] || fail "$preset: sample $rel kept with --no-sample"
  done < "$here/template/presets/$preset/.forge-samples"
  [ -z "$(git -C "$tmp/$preset-clean" status --porcelain)" ] || fail "$preset: --no-sample left uncommitted changes"
done
echo "INIT TEST PASS"
