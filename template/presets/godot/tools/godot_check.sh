#!/usr/bin/env bash
# Headless Godot gates. Usage: tools/godot_check.sh import|test
# import: (re)import the project, then compile every script under src/ and test/ so parse errors
#         and typing warnings-as-errors (project.godot [debug]) fail even for unreferenced scripts.
# test:   run GdUnit4 suites under res://test/ headless.
set -euo pipefail
cd "$(dirname "$0")/.."
GODOT=${GODOT_BIN:-$(python3 -c 'import tomllib;print(tomllib.load(open("forge.toml","rb"))["engine"].get("godot_bin","godot"))')}
read -ra G <<<"$GODOT"   # array so "flatpak run org.godotengine.Godot" works
log=$(mktemp)
trap 'rm -f "$log"' EXIT
case "${1:-}" in
  import)
    # --import exits after importing (Godot 4.2+). Errors are printed, not always reflected in rc.
    timeout 300 "${G[@]}" --headless --path . --import >"$log" 2>&1 || { tail -n 60 "$log"; exit 1; }
    if grep -Eq 'SCRIPT ERROR|Parse Error|Failed to load script|ERROR: ' "$log"; then
      grep -E -A3 'SCRIPT ERROR|Parse Error|Failed to load script|ERROR: ' "$log" | head -n 60
      exit 1
    fi
    if [ -f tools/check_scripts.gd ]; then
      timeout 300 "${G[@]}" --headless --path . -s res://tools/check_scripts.gd >"$log" 2>&1 \
        || { grep -E -A1 'SCRIPT ERROR|FAILED' "$log" | head -n 60; exit 1; }
    fi
    echo "import + script check OK" ;;
  test)
    rc=0
    [ -d addons/gdUnit4 ] || { echo "addons/gdUnit4 missing: run tools/setup_addons.sh"; exit 1; }
    timeout 600 "${G[@]}" --headless --path . -s res://addons/gdUnit4/bin/GdUnitCmdTool.gd \
      --ignoreHeadlessMode --continue --add res://test/ >"$log" 2>&1 || rc=$?
    if [ $rc -ne 0 ] || grep -Eq 'SCRIPT ERROR|Parse Error' "$log"; then
      # Only the failing assertions, without ANSI colour codes: less output to feed back.
      sed 's/\x1b\[[0-9;]*m//g' "$log" | grep -E -B2 -A6 'FAILED|Expecting|SCRIPT ERROR|Parse Error' | head -n 60
      exit 1
    fi
    grep -E 'Overall Summary|Statistics' "$log" | tail -n 3 || true
    echo "tests OK" ;;
  *) echo "usage: $0 import|test" >&2; exit 2 ;;
esac
