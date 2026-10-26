#!/usr/bin/env bash
# Self-test suite for AgentForge: lint shell scripts, docs drift check, mock end-to-end run.
set -euo pipefail
cd "$(dirname "$0")/.."
if command -v shellcheck >/dev/null; then
  shellcheck install.sh tests/*.sh template/common/.claude/hooks/*.sh template/presets/*/tools/*.sh
  echo "shellcheck OK"
else
  echo "shellcheck not installed - skipped"
fi
python3 -m py_compile bin/forge tests/mock_agent.py tests/check_docs.py tests/test_policy.py tests/test_vendors.py tests/test_context.py tests/test_parsers.py tests/test_presets.py \
  && python3 -m compileall -q agentforge && echo "py_compile OK"
python3 tests/check_docs.py
tests/test_init.sh
python3 tests/test_policy.py 2>&1 | tail -n 1
python3 tests/test_vendors.py 2>&1 | tail -n 1
python3 tests/test_context.py 2>&1 | tail -n 1
python3 tests/test_parsers.py 2>&1 | tail -n 1
python3 tests/test_presets.py 2>&1 | tail -n 1
tests/e2e.sh | tail -n 1
