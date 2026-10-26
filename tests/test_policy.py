#!/usr/bin/env python3
"""Unit tests for the policy gate's test-file rules (TAMPER/SCOPE) on a real godot-csharp init.

Covers: sample deletion with may_edit_tests, sample deletion via .forge-samples alone,
denial without either, denial for non-sample tests, assertion accounting, and that a
worker cannot whitelist files by editing .forge-samples."""
import importlib.machinery, importlib.util, os, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader("forge", str(ROOT / "bin" / "forge"))
spec = importlib.util.spec_from_loader("forge", loader)
forge = importlib.util.module_from_spec(spec)
loader.exec_module(forge)
ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@x")
SAMPLE_TEST = "Game.Core.Tests/DiceTests.cs"
REAL_TEST = "Game.Core.Tests/RealTests.cs"
NEW_TEST = "Game.Core.Tests/NewTests.cs"


def run(*a, cwd):
    subprocess.run(a, cwd=cwd, env=ENV, check=True, capture_output=True)


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "p"
        subprocess.run([sys.executable, str(ROOT / "bin" / "forge"), "init", "--preset", "godot-csharp",
                        str(self.root)], check=True, capture_output=True, env=ENV)
        (self.root / REAL_TEST).write_text("public class R { [Fact] public void A() { Assert.True(true); } }\n")
        run("git", "add", "-A", cwd=self.root); run("git", "commit", "-qm", "real test", cwd=self.root)
        self.base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.root, capture_output=True,
                                   text=True).stdout.strip()
        self.proj = forge.Project(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def gate(self, may_edit, *, rm=(), add_asserts=1, extra=None):
        for p in rm:
            run("git", "rm", "-q", p, cwd=self.root)
        if add_asserts:
            (self.root / NEW_TEST).write_text("public class N {\n" + "".join(
                f"  [Fact] public void T{i}() {{ Assert.Equal({i}, {i}); }}\n" for i in range(add_asserts)) + "}\n")
        if extra:
            extra(self.root)
        run("git", "add", "-A", cwd=self.root); run("git", "commit", "-qm", "work", cwd=self.root)
        card = {"id": "T", "owns": ["Game.Core/**"], "docs": [], "tests_required": True, "may_edit_tests": may_edit}
        return forge.gate_policy(self.proj, self.root, self.base, card)

    def tamper(self, fails):
        return [f for f in fails if f.startswith(("TAMPER", "SCOPE", "PROTECTED"))]

    def test_sample_deletion_allowed_with_may_edit_tests(self):
        self.assertEqual(self.tamper(self.gate(True, rm=[SAMPLE_TEST])), [])

    def test_sample_deletion_allowed_by_manifest_without_may_edit(self):
        self.assertEqual(self.tamper(self.gate(False, rm=[SAMPLE_TEST])), [])

    def test_sample_deletion_denied_without_manifest_or_permission(self):
        run("git", "rm", "-q", ".forge-samples", cwd=self.root)
        run("git", "commit", "-qm", "old project: no manifest", cwd=self.root)
        self.base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.root, capture_output=True,
                                   text=True).stdout.strip()
        fails = self.tamper(self.gate(False, rm=[SAMPLE_TEST]))
        self.assertTrue(any("TAMPER: test file deleted" in f for f in fails), fails)

    def test_sample_deletion_allowed_without_manifest_with_may_edit(self):
        # Case: project predates .forge-samples, card has may_edit_tests=true and adds tests.
        run("git", "rm", "-q", ".forge-samples", cwd=self.root)
        run("git", "commit", "-qm", "old project", cwd=self.root)
        self.base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.root, capture_output=True,
                                   text=True).stdout.strip()
        n = sum("Assert" in l for l in (self.root / SAMPLE_TEST).read_text().splitlines())
        self.assertEqual(self.tamper(self.gate(True, rm=[SAMPLE_TEST], add_asserts=n)), [])

    def test_non_sample_deletion_denied_without_permission(self):
        fails = self.tamper(self.gate(False, rm=[REAL_TEST]))
        self.assertTrue(any("TAMPER: test file deleted: " + REAL_TEST in f for f in fails), fails)

    def test_non_sample_deletion_with_permission_still_counts_assertions(self):
        fails = self.tamper(self.gate(True, rm=[REAL_TEST], add_asserts=0))
        self.assertTrue(any("net assertions" in f for f in fails), fails)
        self.assertEqual(self.tamper(self.gate(True, add_asserts=1)), [])

    def test_modify_existing_test_denied_without_permission(self):
        def edit(r):
            (r / REAL_TEST).write_text((r / REAL_TEST).read_text() + "// more\n")
        fails = self.tamper(self.gate(False, extra=edit))
        self.assertTrue(any("existing test file modified" in f for f in fails), fails)

    def test_worker_cannot_whitelist_via_manifest(self):
        def wl(r):
            (r / ".forge-samples").write_text((r / ".forge-samples").read_text() + REAL_TEST + "\n")
        fails = self.tamper(self.gate(False, rm=[REAL_TEST], extra=wl))
        self.assertTrue(any("PROTECTED: .forge-samples" in f for f in fails), fails)
        self.assertTrue(any("TAMPER: test file deleted" in f for f in fails), fails)


if __name__ == "__main__":
    unittest.main()
