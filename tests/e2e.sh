#!/usr/bin/env bash
# End-to-end dry run with mock agents: init -> plan -> run (parallel) -> status -> audit.
# Asserts the cheating attempt was rejected, the reviewer loop happened, and both tasks merged.
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
forge="$here/bin/forge"
tmp=$(mktemp -d)
[ -n "${KEEP:-}" ] || trap 'rm -rf "$tmp"' EXIT; echo "workdir $tmp"
export GIT_AUTHOR_NAME=forge GIT_AUTHOR_EMAIL=forge@localhost GIT_COMMITTER_NAME=forge GIT_COMMITTER_EMAIL=forge@localhost
p="$tmp/demo"
"$forge" init "$p" --preset python
"$forge" -C "$p" --mock plan
git -C "$p" add -A && git -C "$p" commit -qm "plan"
"$forge" -C "$p" --mock run --parallel 2 --audit
st="$p/.forge/state.json"
fail() { echo "E2E FAIL: $*"; exit 1; }
[ "$(jq -r '.tasks["M1-T001"].status' "$st")" = "done" ] || fail "T001 not done"
[ "$(jq -r '.tasks["M1-T002"].status' "$st")" = "done" ] || fail "T002 not done"
jq -e '.tasks["M1-T001"].history[] | select(.msg=="gates failed") | .report | test("TAMPER|HOLLOW")' "$st" >/dev/null \
  || fail "cheating attempt was not caught"
jq -e '.tasks["M1-T002"].history[] | select(.msg=="review FAIL")' "$st" >/dev/null || fail "review loop not exercised"
grep -q "M1-T001" <<<"$(git -C "$p" log --oneline)" || fail "T001 not merged"
( cd "$p" && python3 -m unittest discover -s tests -t . -q ) || fail "tests fail on main"
[ -f "$p/docs/SPEC_ISSUES.md" ] || fail "spec issues not recorded"
[ "$(jq -r '.tasks["M1-T002"].attempts' "$st")" -le 2 ] || fail "T002 needed too many attempts"
# docs/SPEC_ISSUES.md must be rewritten on every plan run, even when there are no issues.
FORGE_MOCK_NO_ISSUES=1 "$forge" -C "$p" --mock plan >/dev/null
grep -q "No issues." "$p/docs/SPEC_ISSUES.md" || fail "SPEC_ISSUES.md not overwritten when empty"
grep -q "Mock: milestone 2" "$p/docs/SPEC_ISSUES.md" && fail "stale issue survived re-plan"
grep -q "TAMPER: skip/disable marker" "$p/.forge/logs/events.log" || fail "events.log lacks full gate report"

# --- regate: judge existing branch work without a worker (recovery path after a wrong gate failed good work) ---
card="$p/tasks/M2-T001-replace-sample.md"
mkcard() {  # $1 = may_edit_tests value
  printf '+++\nid = "M2-T001"\ntitle = "Replace sample"\nmilestone = 2\ndeps = []\nagent = "any"\nowns = ["src/app/**"]\ndocs = ["CHANGELOG.md"]\ntests_required = true\nmay_edit_tests = %s\n+++\n## Goal\nReplace strs tests.\n' "$1" > "$card"
  git -C "$p" add -A && git -C "$p" commit -qm "card may_edit_tests=$1"
}
mkcard false
git -C "$p" branch forge/M2-T001
wt="$tmp/wt"; git -C "$p" worktree add -q "$wt" forge/M2-T001
git -C "$wt" rm -q tests/test_strs.py
sed 's/test_shout/test_shout_v2/' "$p/tests/test_strs.py" > "$wt/tests/test_strs_v2.py"
printf -- '- replaced strs tests\n' >> "$wt/CHANGELOG.md"
git -C "$wt" add -A && git -C "$wt" commit -qm "M2-T001: attempt 1 by codex"
git -C "$p" worktree remove --force "$wt"
head_before=$(git -C "$p" rev-parse forge/M2-T001)
"$forge" -C "$p" --mock regate M2-T001 || true
[ "$(jq -r '.tasks["M2-T001"].status' "$st")" = "gates_failed" ] || fail "regate should fail without may_edit_tests"
grep -qE "TAMPER: (test file deleted|existing test file modified): tests/test_strs" "$p/.forge/logs/events.log" || fail "TAMPER not in events.log"
git -C "$p" merge-base --is-ancestor "$head_before" forge/M2-T001 || fail "regate discarded branch work"
compgen -G "$p/.forge/logs/M2-T001-work*" >/dev/null && fail "regate ran a worker"
mkcard true
jq '.tasks["M2-T001"].agent="claude"' "$st" > "$st.tmp" && mv "$st.tmp" "$st"   # stale state
"$forge" -C "$p" --mock regate M2-T001
[ "$(jq -r '.tasks["M2-T001"].status' "$st")" = "done" ] || fail "regate with may_edit_tests did not merge"
[ "$(jq -r '.tasks["M2-T001"].agent' "$st")" = "codex" ] || fail "regate did not record the branch's real vendor"
compgen -G "$p/.forge/logs/M2-T001-review-claude*" >/dev/null || fail "regate cross review not done by claude"
if [ ! -f "$p/tests/test_strs_v2.py" ] || [ -f "$p/tests/test_strs.py" ]; then fail "branch work not on main"; fi
compgen -G "$p/.forge/logs/M2-T001-work*" >/dev/null && fail "regate ran a worker"
( cd "$p" && python3 -m unittest discover -s tests -t . -q ) || fail "tests fail on main after regate"
# a pending edit to docs/SPEC_ISSUES.md must not block run; other tracked edits must
echo "- pending note" >> "$p/docs/SPEC_ISSUES.md"
"$forge" -C "$p" --mock run >/dev/null || fail "dirty SPEC_ISSUES.md blocked forge run"
echo "x" >> "$p/CHANGELOG.md"
"$forge" -C "$p" --mock run >/dev/null 2>&1 && fail "dirty CHANGELOG.md did not block forge run"
git -C "$p" checkout -q CHANGELOG.md docs/SPEC_ISSUES.md
# a vendor usage limit pauses that vendor without charging attempts or blocking the card
mkdir -p "$p/tasks"; sed -e 's/M2-T001/M2-T009/' -e 's/Replace sample/Limit probe/' -e 's#src/app/\*\*#src/app/limit.py#' "$card" > "$p/tasks/M2-T009-limit.md"
sed -i 's/agent = "any"/agent = "codex"/' "$p/tasks/M2-T009-limit.md"
git -C "$p" add -A && git -C "$p" commit -qm "limit probe card"
FORGE_MOCK_LIMIT=codex "$forge" -C "$p" --mock run --task M2-T009 >/dev/null 2>&1 || true
[ "$(jq -r '.tasks["M2-T009"].status' "$st")" = "todo" ] || fail "usage limit did not leave card todo"
[ "$(jq -r '.tasks["M2-T009"].attempts' "$st")" = "0" ] || fail "usage limit charged an attempt"
grep -q "USAGE LIMIT" "$p/.forge/logs/events.log" || fail "usage limit not logged"
grep -q "codex: cooling down until" "$p/.forge/logs/events.log" || fail "codex cooldown not logged"
jq -e '.cooldowns.codex.until > now' "$st" >/dev/null || fail "codex cooldown not persisted"
grep -q "codex .*cooling until" <<<"$("$forge" -C "$p" limits)" || fail "forge limits does not show codex cooling"
grep -q "wait for a vendor" <<<"$("$forge" -C "$p" --mock run --task M2-T009 2>&1)" || fail "pinned card on cooling vendor did not wait"
"$forge" -C "$p" limits --clear codex >/dev/null
jq -e '.cooldowns | has("codex") | not' "$st" >/dev/null || fail "limits --clear did not lift codex"

# --- three vendors: claude, codex, glm (mock) ---------------------------------------------
sed -i 's/^workers = .*/workers = ["claude", "codex", "glm"]/' "$p/forge.toml"
probe() {  # $1 = id, $2 = pinned agent
  printf '+++\nid = "%s"\ntitle = "Probe %s"\nmilestone = 3\ndeps = []\nagent = "%s"\nowns = ["src/app/%s.py"]\ndocs = ["CHANGELOG.md"]\ntests_required = true\nmay_edit_tests = false\n+++\n## Goal\nProbe.\n' \
    "$1" "$1" "$2" "$(tr 'A-Z-' 'a-z_' <<<"$1")" > "$p/tasks/$1-probe.md"
}
probe M3-T001 glm; probe M3-T002 codex; probe M3-T003 glm; probe M3-T004 claude; probe M3-T005 glm
git -C "$p" add -A && git -C "$p" commit -qm "three-vendor probes"
log="$p/.forge/logs"
# glm work is cross-reviewed by codex (different harness), codex work by claude
"$forge" -C "$p" --mock run --task M3-T001 M3-T002 >/dev/null
[ "$(jq -r '.tasks["M3-T001"].status' "$st")" = "done" ] || fail "glm card not merged"
compgen -G "$log/M3-T001-work-glm*" >/dev/null || fail "glm did not do M3-T001"
compgen -G "$log/M3-T001-review-codex*" >/dev/null || fail "glm work not reviewed by codex"
compgen -G "$log/M3-T001-review-glm*" >/dev/null && fail "glm reviewed its own work"
compgen -G "$log/M3-T002-review-claude*" >/dev/null || fail "codex work not reviewed by claude"
[ "$(jq -r '.vendor_runs.glm' "$st")" -ge 1 ] || fail "glm runs not counted"
jq -e 'has("glm_usd_nominal")' "$st" >/dev/null || fail "glm spend not tracked separately"
"$forge" -C "$p" status | grep -q "glm nominal cost" || fail "status lacks glm cost line"
# review_pool = ["glm"]: claude work reviewed by glm
sed -i 's/^workers = .*/workers = ["claude", "codex", "glm"]\nreview_pool = ["glm"]/' "$p/forge.toml"
git -C "$p" commit -qam "review_pool glm"
"$forge" -C "$p" --mock run --task M3-T004 >/dev/null
compgen -G "$log/M3-T004-review-glm*" >/dev/null || fail "review_pool glm not used"
sed -i '/^review_pool/d' "$p/forge.toml"; git -C "$p" commit -qam "drop review_pool"
# glm usage limit (Z.ai 429 / code 1308): run stops, attempt not charged
FORGE_MOCK_LIMIT=glm "$forge" -C "$p" --mock run --task M3-T003 >/dev/null 2>&1 || true
[ "$(jq -r '.tasks["M3-T003"].status' "$st")" = "todo" ] || fail "glm limit did not leave card todo"
[ "$(jq -r '.tasks["M3-T003"].attempts' "$st")" = "0" ] || fail "glm limit charged an attempt"
grep -q "glm USAGE LIMIT hit (Z.ai" "$log/events.log" || fail "glm limit not logged"
"$forge" -C "$p" limits --clear >/dev/null
# claude overage guard: isUsingOverage=true stops the run (allow_overage defaults to false)
probe M3-T006 claude; git -C "$p" add -A && git -C "$p" commit -qm "overage probe"
FORGE_MOCK_OVERAGE=claude "$forge" -C "$p" --mock run --task M3-T006 >/dev/null 2>&1 || true
[ "$(jq -r '.tasks["M3-T006"].status' "$st")" = "todo" ] || fail "overage did not leave card todo"
[ "$(jq -r '.tasks["M3-T006"].attempts' "$st")" = "0" ] || fail "overage charged an attempt"
grep -q "claude USAGE LIMIT hit (paid overage" "$log/events.log" || fail "overage not logged"
"$forge" -C "$p" limits --clear >/dev/null
# swap_on_retry rotation: glm fails twice, attempt 3 goes to claude (next vendor), reviewed by codex
FORGE_MOCK_BAD=glm "$forge" -C "$p" --mock run --task M3-T005 >/dev/null
[ "$(jq -r '.tasks["M3-T005"].status' "$st")" = "done" ] || fail "swap card not merged"
[ "$(jq -r '.tasks["M3-T005"].agent' "$st")" = "claude" ] || fail "attempt 3 did not rotate to claude"
[ "$(jq -r '.tasks["M3-T005"].attempts' "$st")" = "3" ] || fail "swap card attempt count wrong"
compgen -G "$log/M3-T005-review-codex*" >/dev/null || fail "rotated claude work not reviewed by codex"
( cd "$p" && python3 -m unittest discover -s tests -t . -q ) || fail "tests fail on main after 3-vendor run"

# --- usage-limit handover: the first worker hits a limit, another vendor finishes in the same run
sed -i 's/^\[budget\]$/[budget]\nlimit_cooldown_min = 0.05/' "$p/forge.toml"   # 3 s cooldowns for the test
probe M3-T007 any; git -C "$p" add -A && git -C "$p" commit -qm "handover probe"
FORGE_MOCK_LIMIT_ONCE=claude "$forge" -C "$p" --mock run --task M3-T007 >/dev/null
[ "$(jq -r '.tasks["M3-T007"].status' "$st")" = "done" ] || fail "handover card not merged in the same run"
[ "$(jq -r '.tasks["M3-T007"].attempts' "$st")" = "1" ] || fail "handover charged an attempt"
compgen -G "$log/M3-T007-work-claude*" >/dev/null || fail "claude did not start M3-T007"
compgen -G "$log/M3-T007-work-codex*" >/dev/null || compgen -G "$log/M3-T007-work-glm*" >/dev/null || fail "no other vendor took over M3-T007"
rm -f "$log"/.mock-limit-once-*
# --- review waits for the only allowed reviewer, then resumes without rerunning the worker (--wait)
sed -i 's/^workers = .*/workers = ["claude", "codex"]/' "$p/forge.toml"; git -C "$p" commit -qam "two vendors"
probe M3-T008 codex; git -C "$p" add -A && git -C "$p" commit -qm "review-wait probe"
FORGE_MOCK_LIMIT_ONCE=claude "$forge" -C "$p" --mock run --wait --task M3-T008 >/dev/null
[ "$(jq -r '.tasks["M3-T008"].status' "$st")" = "done" ] || fail "review-wait card not merged after --wait"
[ "$(jq -r '.tasks["M3-T008"].attempts' "$st")" = "1" ] || fail "review-wait reran the worker"
grep -q "M3-T008: gates passed, but every reviewer" "$log/events.log" || fail "review wait not logged"
grep -q "sleeping until" "$log/events.log" || fail "--wait did not sleep"
[ "$(compgen -G "$log/M3-T008-work-*.log" | wc -l)" = "1" ] || fail "worker ran more than once for M3-T008"
rm -f "$log"/.mock-limit-once-*
# --- an OpenCode vendor from forge.toml: pinned work, reviewed by another family on another CLI
printf '\n[agents.oc-kimi]\nharness = "opencode"\nmodel = "opencode-go/kimi-k3"\n' >> "$p/forge.toml"
probe M3-T010 oc-kimi; git -C "$p" add -A && git -C "$p" commit -qm "opencode probe"
"$forge" -C "$p" --mock run --task M3-T010 >/dev/null
[ "$(jq -r '.tasks["M3-T010"].status' "$st")" = "done" ] || fail "opencode card not merged"
compgen -G "$log/M3-T010-work-oc-kimi*" >/dev/null || fail "oc-kimi did not do M3-T010"
compgen -G "$log/M3-T010-review-claude*" >/dev/null || fail "oc-kimi work not reviewed by claude"
grep -q "oc-kimi .*opencode .*moonshot" <<<"$("$forge" -C "$p" limits)" || fail "limits lacks oc-kimi row"
( cd "$p" && python3 -m unittest discover -s tests -t . -q ) || fail "tests fail on main after limit/opencode runs"
echo "E2E PASS"
