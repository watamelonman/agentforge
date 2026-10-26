#!/usr/bin/env python3
"""Mock agent for dry runs (FORGE_MOCK=1). argv: vendor role out_file; prompt on stdin.

Env switches: FORGE_MOCK_LIMIT=<vendor> fails with that vendor's usage-limit message;
FORGE_MOCK_OVERAGE=<vendor> emits a rate_limit_event with isUsingOverage=true;
FORGE_MOCK_LIMIT_ONCE=<vendor> fails only that vendor's first run (cooldown/fallback tests).

Scripted behaviour for the e2e test on the `python` preset:
  plan  -> two independent cards (M1-T001 add, M1-T002 shout)
  work  -> M1-T001 attempt 1 CHEATS (stub, skipped test, no docs) so gates must reject it;
           later attempts and M1-T002 do it properly.
  review-> first review of M1-T002 FAILs (exercises reviewer loop), everything else PASSes.
"""
import json
import os
import re
import sys
from pathlib import Path

vendor, role, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
prompt = sys.stdin.read()
if os.environ.get("FORGE_MOCK_LIMIT") == vendor:
    if vendor == "glm":   # Z.ai-style error as Claude Code prints it (docs.z.ai api-code 1308)
        print('API Error: 429 {"error":{"code":"1308","message":"Usage limit reached for 5 hour. '
              'Your limit will reset at 2026-10-14 18:00:00"}}')
    else:
        print("You've hit your usage limit. Try again later.")
    sys.exit(1)
once = out.parent / f".mock-limit-once-{vendor}"
if os.environ.get("FORGE_MOCK_LIMIT_ONCE") == vendor and not once.exists():
    once.write_text("hit\n")   # only the first run of this vendor hits the limit
    print("You've hit your usage limit. Try again later.")
    sys.exit(1)
if os.environ.get("FORGE_MOCK_OVERAGE") == vendor:
    # Claude Code stream-json event seen when the subscription spills into paid overage.
    print(json.dumps({"type": "rate_limit_event", "rate_limit_info": {
        "status": "allowed_warning", "rateLimitType": "five_hour", "isUsingOverage": True}}))
task = os.environ.get("FORGE_TASK", "")
logs = out.parent


def w(path, text):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def card(i, title, owns, goal):
    return {"id": i, "title": title, "milestone": 1, "deps": [], "agent": "any", "owns": owns,
            "docs": ["CHANGELOG.md"], "tests_required": True, "may_edit_tests": False,
            "goal": goal, "acceptance": [f"{title} works and is unit tested"], "notes": ""}


if role == "plan":
    out.write_text(json.dumps({"tasks": [
        card("M1-T001", "Add function", ["src/app/mathx.py"], "add(a, b) returns the sum"),
        card("M1-T002", "Shout function", ["src/app/strs.py"], "shout(s) upper-cases and appends !"),
    ], "spec_issues": [] if os.environ.get("FORGE_MOCK_NO_ISSUES") else
        ["Mock: milestone 2 exit criteria are not testable as written."]}))
elif role == "review":
    n = len(list(logs.glob(f"{task}-review-*.out")))
    if task == "M1-T002" and n == 0:
        v = {"verdict": "FAIL", "summary": "edge case missing", "criteria": [],
             "issues": [{"severity": "blocker", "file": "src/app/strs.py",
                         "problem": "empty string not handled", "fix": "return '!' for ''"}]}
    else:
        v = {"verdict": "PASS", "summary": "meets criteria", "issues": [], "criteria": []}
    out.write_text(json.dumps(v))
elif role == "audit":
    out.write_text(json.dumps({"verdict": "HEALTHY", "findings": [], "new_tasks": []}))
elif role == "work":
    first = "first attempt" in prompt
    if task == "M1-T001" and first:
        w("src/app/mathx.py", "def add(a, b):\n    return 3  # TODO real impl\n")
        w("tests/test_mathx.py", "import unittest\n\n\nclass T(unittest.TestCase):\n"
          "    @unittest.skip('later')\n    def test_add(self):\n        self.assertEqual(1, 1)\n")
    elif task == "M1-T001":
        w("src/app/mathx.py", 'def add(a, b):\n    """Return a + b; ints only so sim stays exact."""\n    return a + b\n')
        w("tests/test_mathx.py", "import unittest\n\nfrom src.app.mathx import add\n\n\n"
          "class T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n"
          "        self.assertEqual(add(-1, 1), 0)\n")
        Path("CHANGELOG.md").write_text(Path("CHANGELOG.md").read_text() + "- add() in src/app/mathx.py\n")
    elif task == "M1-T002":
        w("src/app/strs.py", 'def shout(s):\n    """Upper-case s and append "!" (empty -> "!")."""\n'
          '    return s.upper() + "!"\n')
        w("tests/test_strs.py", "import unittest\n\nfrom src.app.strs import shout\n\n\n"
          "class T(unittest.TestCase):\n    def test_shout(self):\n        self.assertEqual(shout('hi'), 'HI!')\n"
          "        self.assertEqual(shout(''), '!')\n")
        cl = Path("CHANGELOG.md").read_text()
        if "shout" not in cl:
            Path("CHANGELOG.md").write_text(cl + "- shout() in src/app/strs.py\n")
    elif task.startswith("M3-"):
        # Generic multi-vendor probe cards (tests/e2e.sh): a correct, documented change in
        # src/app/<id>.py. FORGE_MOCK_BAD=<vendor> makes that vendor write an out-of-scope
        # file instead (name varies per attempt so gates never see an identical failure twice).
        n = int((re.search(r"\(attempt (\d+) of", prompt) or [0, 0])[1])
        mod = task.lower().replace("-", "_")
        if os.environ.get("FORGE_MOCK_BAD") == vendor:
            w(f"junk_{mod}_{n}.txt", "out of scope\n")
        else:
            for junk in Path(".").glob(f"junk_{mod}_*.txt"):   # undo earlier bad attempts
                junk.unlink()
            w(f"src/app/{mod}.py", f'def {mod}():\n    """Return the probe id {task} (mock)."""\n    return "{task}"\n')
            w(f"tests/test_{mod}.py", f"import unittest\n\nfrom src.app.{mod} import {mod}\n\n\n"
              f"class T(unittest.TestCase):\n    def test_id(self):\n        self.assertEqual({mod}(), '{task}')\n")
            Path("CHANGELOG.md").write_text(Path("CHANGELOG.md").read_text() + f"- {mod}() by {vendor}\n")
    out.write_text("DONE: mock\nCHANGED: see diff\nTESTS: unit\nINTERPRETATIONS: none\n"
                   "SPEC/INFRA ISSUES: none\nLEFT OUT: none\n")
print(json.dumps({"type": "mock", "vendor": vendor, "role": role, "task": task}))
