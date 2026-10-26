#!/usr/bin/env python3
"""Unit tests for the parsing helpers that were hardest to read: the reset-time regexes,
duration_secs, next_wakeup, the Z.ai limit regex and the Grok JSON event scanner. Also runs
the examples in their docstrings (doctest), so the documentation cannot drift."""
import doctest
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import agentforge.limits as limits          # noqa: E402
import agentforge.parsers.grok as grok      # noqa: E402
import agentforge.resettime as resettime    # noqa: E402
import agentforge.util as util              # noqa: E402
from agentforge.detect import ZAI_LIMIT_RE  # noqa: E402
from agentforge.project import Project      # noqa: E402


class FakeProject:
    """Only what cooldown_until/next_wakeup touch: .c(), .mock, .root, state and events."""
    def __init__(self, agents):
        self.cfg, self.mock, self.root, self.events = {"agents": agents}, False, Path("/nonexistent-project"), []
    c = Project.c

    def update_state(self, fn):
        fn({})

    def event(self, msg):
        self.events.append(msg)


def groups(rx, text):
    return [m.groups() for m in rx.finditer(text)]


class Durations(unittest.TestCase):
    def test_duration_re_pieces(self):
        self.assertEqual(groups(resettime.DURATION_RE, "2 hours"), [("2", "hours")])
        self.assertEqual(groups(resettime.DURATION_RE, "1h30m"), [("1", "h"), ("30", "m")])
        self.assertEqual(groups(resettime.DURATION_RE, "1.5 DAYS"), [("1.5", "DAYS")])

    def test_duration_re_unit_must_end_the_word(self):
        self.assertEqual(groups(resettime.DURATION_RE, "5 hoursly 3 mo"), [])

    def test_duration_secs(self):
        self.assertEqual(resettime.duration_secs("2 hours 13 minutes"), 7980)
        self.assertEqual(resettime.duration_secs("1h30m"), 5400)
        self.assertEqual(resettime.duration_secs("45 secs"), 45)
        self.assertEqual(resettime.duration_secs("1 day, 2 hrs and 5 min"), 86400 + 7200 + 300)
        self.assertEqual(resettime.duration_secs("soon"), 0)


class ResetText(unittest.TestCase):
    def test_reset_in(self):
        self.assertEqual(groups(resettime.RESET_IN_RE, "Try again in 2 hours 13 minutes."),
                         [("2 hours 13 minutes",)])
        self.assertEqual(groups(resettime.RESET_IN_RE, "retry after 45s"), [("45s",)])
        self.assertEqual(groups(resettime.RESET_IN_RE, "resets in 1h30m, sorry"), [("1h30m, ",)])
        self.assertEqual(groups(resettime.RESET_IN_RE, "try again later"), [])

    def test_reset_at_needs_a_zone(self):
        self.assertEqual(groups(resettime.RESET_AT_RE, "limit reached; resets at 2026-10-21T18:00:00Z"),
                         [("2026-10-21T18:00:00Z",)])
        self.assertEqual(groups(resettime.RESET_AT_RE, "try again at 2026-10-21 18:00+02:00"),
                         [("2026-10-21 18:00+02:00",)])
        self.assertEqual(groups(resettime.RESET_AT_RE, "reset at 2026-10-21 18:00:00"), [])

    def test_limit_reset_time_uses_the_text(self):
        got = resettime.limit_reset_time("usage limit. Try again in 1h30m.")
        self.assertAlmostEqual(got, time.time() + 5400, delta=5)


class ZaiLimit(unittest.TestCase):
    def test_matches(self):
        for text in ("API Error: 429 {...}", "HTTP 429", "status=429", '{"code": "1302"}', "code=1308"):
            self.assertTrue(ZAI_LIMIT_RE.search(text), text)

    def test_ignores(self):
        for text in ("4290 tokens", "API Error: 500", '"code": "1000"', "line 429 of foo.py"):
            self.assertIsNone(ZAI_LIMIT_RE.search(text), text)


class NextWakeup(unittest.TestCase):
    def setUp(self):
        limits.COOLDOWNS.clear(); limits.DISABLED.clear(); limits.SPEND.clear()

    tearDown = setUp

    def test_none_when_nobody_cools_down(self):
        self.assertIsNone(limits.next_wakeup(FakeProject({})))

    def test_earliest_cooldown(self):
        p = FakeProject({})
        soon, later = time.time() + 600, time.time() + 7200
        limits.set_cooldown(p, "claude", later, "test")
        limits.set_cooldown(p, "codex", soon, "test")
        self.assertAlmostEqual(limits.next_wakeup(p), soon, delta=1)


class GrokEvents(unittest.TestCase):
    def test_ndjson_newest_first(self):
        raw = '{"type":"text"}\nnoise\n{"type":"result","result":"ok"}'
        types = [e.get("type") for e in grok._iter_grok_json_events(raw)]
        self.assertEqual(types[:2], ["result", "text"])

    def test_pretty_printed_trailing_object(self):
        raw = 'log line\n{\n  "text": "done",\n  "stopReason": "end"\n}'
        self.assertEqual(list(grok._iter_grok_json_events(raw)), [{"text": "done", "stopReason": "end"}])

    def test_non_dict_and_empty(self):
        self.assertEqual(list(grok._iter_grok_json_events("[1, 2]\n\"x\"")), [])
        self.assertEqual(list(grok._iter_grok_json_events("")), [])
        self.assertEqual(list(grok._iter_grok_json_events(None)), [])


def load_tests(loader, tests, ignore):
    for mod in (resettime, grok, limits, util):
        tests.addTests(doctest.DocTestSuite(mod))
    return tests


if __name__ == "__main__":
    unittest.main()
