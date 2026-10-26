#!/usr/bin/env python3
"""Every preset's regex config keys compile as Python regexes, and the love2d policy gate runs.

Covers policy.forbid_added, policy.skip_markers, policy.test_detection, policy.assert_regex,
layers.forbid_patterns and pools.*.plan_limit_re in every template/presets/*/forge.toml, and
gate_policy on a scratch love2d project (a commented-out busted `it(` is a TAMPER)."""
import importlib.machinery, importlib.util, os, re, subprocess, sys, tempfile, tomllib, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader("forge", str(ROOT / "bin" / "forge"))
spec = importlib.util.spec_from_loader("forge", loader)
forge = importlib.util.module_from_spec(spec)
loader.exec_module(forge)
ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@x")
PRESETS = sorted(p for p in (ROOT / "template" / "presets").iterdir() if (p / "forge.toml").exists())


def preset_regexes(cfg):
    """Yield (key, pattern) for every regex-valued key in one parsed forge.toml."""
    pol = cfg.get("policy", {})
    for key in ("forbid_added", "skip_markers", "test_detection"):
        for pat in pol.get(key, []):
            yield f"policy.{key}", pat
    if "assert_regex" in pol:
        yield "policy.assert_regex", pol["assert_regex"]
    for layer, pats in cfg.get("layers", {}).get("forbid_patterns", {}).items():
        for pat in pats:
            yield f"layers.forbid_patterns.{layer}", pat
    for name, pool in cfg.get("pools", {}).items():
        if isinstance(pool, dict) and "plan_limit_re" in pool:
            yield f"pools.{name}.plan_limit_re", pool["plan_limit_re"]


def run(*a, cwd):
    subprocess.run(a, cwd=cwd, env=ENV, check=True, capture_output=True)


class PresetRegexTests(unittest.TestCase):
    def test_every_preset_regex_compiles(self):
        self.assertTrue(PRESETS)
        for preset in PRESETS:
            cfg = tomllib.loads((preset / "forge.toml").read_text())
            for key, pat in preset_regexes(cfg):
                with self.subTest(preset=preset.name, key=key, pattern=pat):
                    re.compile(pat)

    def test_love2d_skip_markers_match_busted(self):
        cfg = tomllib.loads((ROOT / "template" / "presets" / "love2d" / "forge.toml").read_text())
        skips = [re.compile(p) for p in cfg["policy"]["skip_markers"]]
        hit = lambda line: any(s.search(line) for s in skips)
        for line in ("  -- it('moves', function()", "--it(\"x\"", "pending('later')"):
            self.assertTrue(hit(line), line)
        for line in ("  it('moves', function()", "-- a comment", "local item = split(x)"):
            self.assertFalse(hit(line), line)


class Love2dGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "p"
        subprocess.run([sys.executable, str(ROOT / "bin" / "forge"), "init", "--preset", "love2d",
                        str(self.root)], check=True, capture_output=True, env=ENV)
        self.base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.root, capture_output=True,
                                   text=True).stdout.strip()
        self.proj = forge.Project(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def gate(self, spec_body):
        (self.root / "src" / "sim").mkdir(parents=True, exist_ok=True)
        (self.root / "src" / "sim" / "move.lua").write_text("local M = {}\nfunction M.step(x) return x + 1 end\nreturn M\n")
        (self.root / "spec_tests").mkdir(exist_ok=True)
        (self.root / "spec_tests" / "move_spec.lua").write_text(spec_body)
        run("git", "add", "-A", cwd=self.root); run("git", "commit", "-qm", "work", cwd=self.root)
        card = {"id": "T", "owns": ["src/**"], "docs": [], "tests_required": True, "may_edit_tests": False}
        fails = forge.gate_policy(self.proj, self.root, self.base, card)
        return [f for f in fails if f.startswith("TAMPER")]

    def test_plain_spec_passes(self):
        body = "describe('move', function()\n  it('steps', function()\n    assert.are.equal(2, 1 + 1)\n  end)\nend)\n"
        self.assertEqual(self.gate(body), [])

    def test_commented_out_it_is_tamper(self):
        body = ("describe('move', function()\n  it('steps', function()\n    assert.are.equal(2, 1 + 1)\n  end)\n"
                "  -- it('skipped', function() end)\nend)\n")
        self.assertTrue(self.gate(body))


if __name__ == "__main__":
    unittest.main()
