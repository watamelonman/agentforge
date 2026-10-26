#!/usr/bin/env python3
"""Unit tests for the context pack (bin/forge build_context / with_context). No agents run."""
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
forge = SourceFileLoader("forge", str(ROOT / "bin" / "forge")).load_module()

SPEC = """# Spec
## 1. Mission
Build it.
## 2. Non-negotiable architecture
No globals.
```
## 3. not a heading inside a fence
```
### 2.1 Determinism
Seeded RNG.
## 7. Milestones
### M7 — Combat core
Fight.
### M17 — Later
Not this.
## 9. Decisions
### 9.8 M7 decisions
Use speed.
"""
DEC = """# Decision log
## DEC-001 — Digest
Bytes.
## DEC-M7-T017 — Script grammar
Words.
"""


class P:
    def __init__(self, root, cfg):
        self.root, self.cfg, self.mock = Path(root), cfg, True
    c = forge.Project.c


def make(cfg=None):
    td = tempfile.mkdtemp()
    (Path(td) / "spec").mkdir()
    (Path(td) / "docs").mkdir()
    (Path(td) / "spec" / "SPEC.md").write_text(SPEC)
    (Path(td) / "docs" / "DECISIONS.md").write_text(DEC)
    base = {"gates": {"cmd": {"build": "make -s"}}}
    base.update(cfg or {})
    return P(td, base)


CARD = {"id": "M7-T017", "milestone": 7, "raw": "Goal (spec §1). Grammar in DEC-M7-T017."}


class Sections(unittest.TestCase):
    def test_fenced_heading_ignored_and_children_nested(self):
        titles = [t for _, t, _ in forge.md_sections(SPEC)]
        self.assertNotIn("3. not a heading inside a fence", titles)
        two = [b for _, t, b in forge.md_sections(SPEC) if t.startswith("2.")][0]
        self.assertIn("Seeded RNG.", two)

    def test_milestone_word_match_not_prefix(self):
        secs = "".join(forge.select_spec_sections(SPEC, set(), 7))
        self.assertIn("Fight.", secs)
        self.assertIn("Use speed.", secs)
        self.assertNotIn("Not this.", secs)

    def test_parent_not_duplicated_with_child(self):
        secs = forge.select_spec_sections(SPEC, {"2", "2.1"}, None)
        self.assertEqual(sum(s.count("Seeded RNG.") for s in secs), 1)


class Pack(unittest.TestCase):
    def test_default_pack(self):
        text = forge.build_context(make(), CARD, "work")
        self.assertIn("Build it.", text)            # §1 cited
        self.assertNotIn("No globals.", text)       # §2 not cited, always_spec empty by default
        self.assertIn("Words.", text)               # named decision
        self.assertNotIn("Bytes.", text)            # unnamed decision
        self.assertNotIn("Index of", text)          # index off by default
        self.assertIn("make -s", text)              # gate commands for workers

    def test_review_pack_has_no_gate_commands(self):
        self.assertNotIn("make -s", forge.build_context(make(), CARD, "review"))

    def test_options(self):
        p = make({"context": {"always_spec": ["2"], "decision_index": True}})
        text = forge.build_context(p, CARD, "work")
        self.assertIn("No globals.", text)
        self.assertIn("- DEC-001 — Digest", text)

    def test_disabled_and_cap(self):
        self.assertEqual(forge.build_context(make({"context": {"enabled": False}}), CARD), "")
        text = forge.build_context(make({"context": {"max_chars": 50}}), CARD)
        self.assertIn("truncated", text)

    def test_missing_files_give_empty_pack(self):
        p = P(tempfile.mkdtemp(), {})
        self.assertEqual(forge.build_context(p, CARD), "")

    def test_with_context_placeholder_or_append(self):
        self.assertEqual(forge.with_context("a {{CONTEXT}} b", ""), "a  b")
        self.assertIn("Context pack", forge.with_context("a {{CONTEXT}} b", "x"))
        self.assertTrue(forge.with_context("old prompt", "x").startswith("old prompt\n\n## Context pack"))
        self.assertEqual(forge.with_context("old prompt", ""), "old prompt")


if __name__ == "__main__":
    unittest.main()
