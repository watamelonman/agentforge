#!/usr/bin/env bash
# PreToolUse guard: block edits that weaken tests. Exit 2 = block, stderr goes to Claude.
# Reads the hook JSON on stdin. Requires jq; if jq is missing, allow (gates still catch it).
set -euo pipefail
command -v jq >/dev/null || exit 0
input=$(cat)
file=$(jq -r '.tool_input.file_path // empty' <<<"$input")
new=$(jq -r '(.tool_input.new_string // .tool_input.content // "")' <<<"$input")
case "$file" in
  */tests/*|*/test/*|*_test.*|*test_*)
    if grep -Eq '(@unittest\.skip|pytest\.mark\.skip|GTEST_SKIP|DISABLED_|#if 0)' <<<"$new"; then
      echo "Blocked: adding skip/disable markers to tests is forbidden (AGENTS.md section 3)." >&2
      exit 2
    fi
    ;;
esac
exit 0
