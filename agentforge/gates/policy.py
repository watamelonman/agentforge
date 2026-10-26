"""The `policy` gate: anti-cheat, scope, size and docs rules from [policy] (docs/GATES.md)."""
from __future__ import annotations

import re

from ..util import glob_match
from .diff import added_lines, changed_files, removed_lines, sample_paths
from .doccheck import doc_coverage


class PolicyRules:
    """[policy] settings with their defaults, regexes compiled once per gate run."""
    def __init__(self, proj):
        P = proj.c("policy", default={})
        self.tests = P.get("test_globs", ["tests/**"])
        self.protected = P.get("protected", [])
        self.common = P.get("always_allowed", ["docs/**", "CHANGELOG.md"])
        self.src_globs = P.get("source_globs", ["src/**"])
        self.forbid = [re.compile(x) for x in P.get("forbid_added", [])]
        self.skips = [re.compile(x) for x in P.get("skip_markers", [])]
        self.assert_re = re.compile(P.get("assert_regex", r"\bassert|EXPECT_|ASSERT_|CHECK\("))
        self.test_detect = [re.compile(x) for x in P.get("test_detection", [])]
        self.max_lines = P.get("max_file_lines", 600)
        self.max_diff = P.get("max_diff_lines", 1500)
        self.scene_globs = P.get("scene_globs", [])
        self.max_scene = P.get("max_scene_diff_lines", 40)

    def count_asserts(self, lines):
        return sum(1 for l in lines if self.assert_re.search(l))


def gate_policy(proj, wt, base, card):
    """Anti-cheat + scope + size + docs. Returns list of failure strings."""
    rules = PolicyRules(proj)
    files = changed_files(wt, base)
    if not files:
        return ["No changes were committed. Implement the task."]
    check = _PolicyCheck(rules, wt, base, card, sample_paths(wt, base))
    for status, path, before in files:
        check.changed_file(status, path, before)
    fails = check.fails + check.branch_totals()
    paths = {p for _, p, _ in files}
    for d in card.get("docs", []):
        if not any(glob_match(p, [d]) for p in paths):
            fails.append(f"DOCS: task requires updating {d} but it was not changed.")
    fails += doc_coverage(proj, wt, [p for s, p, _ in files if s != "D"])
    return fails


class _PolicyCheck:
    """Per-file policy checks over one branch diff; collects failures in diff order."""
    def __init__(self, rules, wt, base, card, samples):
        self.r, self.wt, self.base, self.card, self.samples = rules, wt, base, card, samples
        self.may_edit = bool(card.get("may_edit_tests"))
        self.fails = []
        self.total = 0                 # lines added over the whole diff
        self.added_asserts = self.removed_asserts = 0

    def changed_file(self, status, path, before):
        r = self.r
        is_test = glob_match(path, r.tests) or glob_match(before, r.tests)
        is_sample = before in self.samples
        self._protected(path, before)
        self._tamper(status, path, is_test, is_sample)
        self._scope(status, path, is_test, is_sample)
        if status == "D":
            # Assertions in a deleted non-sample test still count as removed (no net drop);
            # a deleted sample's assertions never protected real behaviour, so they are free.
            if is_test and not is_sample:
                self.removed_asserts += r.count_asserts(self._removed(path))
            return
        add = added_lines(self.wt, self.base, path)
        self.total += len(add)
        self._scene(path, add)
        if is_test:
            self._test_lines(path, add)
        elif glob_match(path, r.src_globs):
            self._source_lines(path, add)
        self._file_size(path)

    def branch_totals(self):
        """Failures that need the whole diff: net assertions, required tests, diff size."""
        fails = []
        if self.removed_asserts > self.added_asserts and self.removed_asserts:
            fails.append(f"TAMPER: net assertions in tests decreased ({self.removed_asserts} removed, "
                         f"{self.added_asserts} added).")
        if self.card.get("tests_required") and self.added_asserts == 0:
            fails.append("TESTS: task requires tests but no new assertions were added under test paths.")
        if self.total > self.r.max_diff:
            fails.append(f"SIZE: diff adds {self.total} lines (> {self.r.max_diff}). Task is too big or code is bloated.")
        return fails

    def _removed(self, path):
        return removed_lines(self.wt, self.base, path)

    def _protected(self, path, before):
        if ".forge-samples" in (path, before):
            self.fails.append("PROTECTED: .forge-samples is human-owned; workers may not change it.")
        if glob_match(path, self.r.protected) or glob_match(before, self.r.protected):
            self.fails.append(f"PROTECTED: {path} may not be modified by workers (protected path).")

    def _tamper(self, status, path, is_test, is_sample):
        # Existing tests: deleting or editing needs may_edit_tests=true on the card. Disposable
        # sample files (.forge-samples on main) count as permitted too, but only for deletion.
        if not is_test:
            return
        if status == "D" and not (self.may_edit or is_sample):
            self.fails.append(f"TAMPER: test file deleted: {path} (task card has may_edit_tests=false "
                              "and the file is not listed in .forge-samples)")
        if status in "MR" and not self.may_edit:
            self.fails.append(f"TAMPER: existing test file modified: {path} "
                              "(task card has may_edit_tests=false; add new tests instead)")

    def _scope(self, status, path, is_test, is_sample):
        test_ok = is_test and (status == "A" or self.may_edit or (status == "D" and is_sample))
        sample_del = status == "D" and is_sample
        owns = self.card["owns"]
        if glob_match(path, owns) or glob_match(path, self.r.common) or test_ok or sample_del:
            return
        self.fails.append(f"SCOPE: {path} is outside this task's `owns` list {owns}")

    def _scene(self, path, add):
        if not glob_match(path, self.r.scene_globs):
            return
        if not self.card.get("scene_edits"):
            self.fails.append(f"SCENE: {path} is a scene/resource file; this card has scene_edits=false. "
                              "Build node trees in code or ask for a scene card (see docs/ENGINE.md).")
        elif len(add) + len(self._removed(path)) > self.r.max_scene:
            self.fails.append(f"SCENE: {path} diff exceeds {self.r.max_scene} lines; bulk hand-editing scene files "
                              "is forbidden. Generate it with a tool script or leave it to the human editor.")

    def _test_lines(self, path, add):
        self.added_asserts += self.r.count_asserts(add)
        self.removed_asserts += self.r.count_asserts(self._removed(path))
        for l in add:
            for s in self.r.skips:
                if s.search(l):
                    self.fails.append(f"TAMPER: skip/disable marker added in {path}: {l.strip()[:120]}")

    def _source_lines(self, path, add):
        for l in add:
            for rx in self.r.forbid:
                if rx.search(l):
                    self.fails.append(f"HOLLOW: forbidden pattern /{rx.pattern}/ in {path}: {l.strip()[:120]}")
            for rx in self.r.test_detect:
                if rx.search(l):
                    self.fails.append(f"CHEAT: production code appears to detect test mode in {path}: {l.strip()[:120]}")

    def _file_size(self, path):
        fp = self.wt / path
        if not (fp.is_file() and glob_match(path, self.r.src_globs + self.r.tests)):
            return
        with fp.open(errors="replace") as fh:
            n = sum(1 for _ in fh)
        if n > self.r.max_lines:
            self.fails.append(f"SIZE: {path} has {n} lines (> {self.r.max_lines}); split it into cohesive units.")
