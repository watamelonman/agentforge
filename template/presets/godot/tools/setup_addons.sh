#!/usr/bin/env bash
# Vendor GdUnit4 into addons/ (run once by a human, then commit). Pin the tag that matches your Godot.
set -euo pipefail
cd "$(dirname "$0")/.."
TAG=${GDUNIT_TAG:-v6.2.2}   # v6.2.2 verified with Godot 4.5-stable; check https://github.com/godot-gdunit-labs/gdUnit4/releases for your Godot version
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
git clone -q --depth 1 --branch "$TAG" https://github.com/godot-gdunit-labs/gdUnit4.git "$tmp/g"
mkdir -p addons && rm -rf addons/gdUnit4 && cp -r "$tmp/g/addons/gdUnit4" addons/
echo "GdUnit4 $TAG installed in addons/gdUnit4 - open the editor once, then commit addons/."
