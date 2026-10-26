#!/usr/bin/env python3
"""Unit tests for multi-vendor logic in bin/forge: cross review, swap rotation, glm env,
grok argv/output parsing, usage-limit / overage detection, per-vendor cooldowns and allowance
windows, opencode vendors (argv, sandbox, permissions, output). No network, no real CLIs, no keys."""
import json
import os
import time
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
forge = SourceFileLoader("forge", str(ROOT / "bin" / "forge")).load_module()


class P:
    """Minimal stand-in for forge.Project: only .c(), .mock and .root are used by the code under test."""
    def __init__(self, cfg, root="/nonexistent-project"):
        self.cfg, self.mock, self.root = cfg, False, Path(root)
    c = forge.Project.c


def reset_limits():
    """Cooldown state is module-global in forge; every test starts with all vendors free."""
    forge.COOLDOWNS.clear(); forge.DISABLED.clear(); forge.SPEND.clear()


def proj(**agents):
    return P({"agents": agents})


class CrossReview(unittest.TestCase):
    def test_legacy_two_vendor(self):
        p = proj(workers=["claude", "codex"])
        self.assertEqual(forge.pick_reviewer(p, "claude"), "codex")
        self.assertEqual(forge.pick_reviewer(p, "codex"), "claude")

    def test_legacy_single_worker_still_cross(self):
        p = proj(workers=["claude"])
        self.assertEqual(forge.pick_reviewer(p, "claude"), "codex")
        self.assertEqual(forge.pick_reviewer(proj(workers=["codex"]), "codex"), "claude")

    def test_three_vendors_prefers_other_harness(self):
        p = proj(workers=["claude", "codex", "glm"])
        self.assertEqual(forge.pick_reviewer(p, "claude"), "codex")
        self.assertEqual(forge.pick_reviewer(p, "glm"), "codex")
        self.assertEqual(forge.pick_reviewer(p, "codex"), "claude")
        p = proj(workers=["glm", "codex", "claude"])
        self.assertEqual(forge.pick_reviewer(p, "codex"), "glm")

    def test_same_harness_fallback_and_never_author(self):
        p = proj(workers=["claude", "glm"])           # codex limited / not in pool
        self.assertEqual(forge.pick_reviewer(p, "claude"), "glm")
        self.assertEqual(forge.pick_reviewer(p, "glm"), "claude")
        for pool in (["claude"], ["glm"], ["codex"], ["claude", "codex", "glm"]):
            for a in forge.VENDORS:
                self.assertNotEqual(forge.pick_reviewer(proj(workers=pool), a), a)

    def test_review_pool_overrides_workers(self):
        p = proj(workers=["claude", "codex"], review_pool=["glm"])
        self.assertEqual(forge.pick_reviewer(p, "claude"), "glm")
        self.assertEqual(forge.pick_reviewer(p, "codex"), "glm")
        self.assertEqual(forge.pick_reviewer(p, "glm"), "codex")   # author excluded -> legacy partner

    def test_explicit_and_none(self):
        self.assertIsNone(forge.pick_reviewer(proj(reviewer="none"), "claude"))
        self.assertEqual(forge.pick_reviewer(proj(reviewer="glm"), "codex"), "glm")


class Swap(unittest.TestCase):
    card = {"agent": "claude"}

    def test_two_vendor_swap_unchanged(self):
        p = proj(workers=["claude", "codex"])
        self.assertEqual([forge.pick_worker(p, self.card, a) for a in (1, 2, 3, 4)],
                         ["claude", "claude", "codex", "codex"])

    def test_three_vendor_rotation(self):
        p = proj(workers=["claude", "codex", "glm"])
        self.assertEqual([forge.pick_worker(p, self.card, a) for a in (1, 2, 3, 4, 5)],
                         ["claude", "claude", "codex", "glm", "codex"])

    def test_swap_off_and_single(self):
        self.assertEqual(forge.pick_worker(proj(workers=["claude", "glm"], swap_on_retry=False), self.card, 4), "claude")
        self.assertEqual(forge.pick_worker(proj(workers=["claude"]), self.card, 4), "claude")


class GlmEnv(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.keyfile = Path(self.td.name) / "zai.env"
        self.keyfile.write_text("# comment\nexport ZAI_API_KEY='file-key-123'\nOTHER=1\n")
        self.a = {"key_file": str(self.keyfile), "config_dir": str(Path(self.td.name) / "cfg")}
        self.saved = os.environ.pop("ZAI_API_KEY", None)

    def tearDown(self):
        if self.saved is not None:
            os.environ["ZAI_API_KEY"] = self.saved
        self.td.cleanup()

    def test_key_from_file_then_env(self):
        self.assertEqual(forge.glm_key(self.a)[0], "file-key-123")
        os.environ["ZAI_API_KEY"] = "env-key"
        try:
            self.assertEqual(forge.glm_key(self.a)[0], "env-key")
        finally:
            del os.environ["ZAI_API_KEY"]
        self.assertIsNone(forge.glm_key({"key_file": "/nonexistent"})[0])
        self.assertNotIn("file-key", forge.glm_key(self.a)[1])   # source text never contains the key

    def test_env_overrides_and_isolation(self):
        base = {"PATH": "/bin", "ANTHROPIC_API_KEY": "real", "CLAUDE_CODE_OAUTH_TOKEN": "x", "ZAI_API_KEY": "z"}
        before = dict(os.environ)
        env = forge.glm_env(self.a, base)
        self.assertEqual(dict(os.environ), before)                     # global env untouched
        self.assertEqual(base["ANTHROPIC_API_KEY"], "real")            # caller's dict untouched
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://api.z.ai/api/anthropic")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "file-key-123")
        for k in ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL"):
            self.assertEqual(env[k], "glm-5.3")
        self.assertEqual(env["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "glm-5.3-flash")
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", env)
        self.assertNotIn("ZAI_API_KEY", env)
        self.assertTrue(Path(env["CLAUDE_CONFIG_DIR"]).is_dir())
        self.assertNotEqual(Path(env["CLAUDE_CONFIG_DIR"]), Path.home() / ".claude")
        env2 = forge.glm_env(dict(self.a, model="glm-x", haiku_model="glm-y"), base)
        self.assertEqual((env2["ANTHROPIC_MODEL"], env2["ANTHROPIC_DEFAULT_HAIKU_MODEL"]), ("glm-x", "glm-y"))

    def test_missing_key_raises(self):
        with self.assertRaises(RuntimeError):
            forge.glm_env({"key_file": "/nonexistent"}, {})


class Limits(unittest.TestCase):
    p = proj()

    def test_zai_codes(self):
        raw = 'API Error: 429 {"error":{"code":"1308","message":"Usage limit reached for 5 hour"}}'
        self.assertTrue(forge.detect_limit(self.p, "glm", raw, 1))
        self.assertTrue(forge.detect_limit(self.p, "glm", '{"error":{"code":"1310","message":"x"}}', 1))
        self.assertTrue(forge.detect_limit(self.p, "glm", '{"error":{"code":"1302"}}', 0, result_is_error=True))
        self.assertIsNone(forge.detect_limit(self.p, "glm", '{"error":{"code":"1211","message":"Unknown Model"}}', 1))
        self.assertIsNone(forge.detect_limit(self.p, "glm", 'test 1308 passed; line 429', 0))

    def test_rejected_event(self):
        raw = '{"type":"rate_limit_event","rate_limit_info":{"status":"rejected"}}\n'
        self.assertTrue(forge.detect_limit(self.p, "glm", raw, 0))
        self.assertTrue(forge.detect_limit(self.p, "claude", raw, 0))

    def test_claude_overage_guard(self):
        raw = '{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","isUsingOverage":true}}\n'
        self.assertTrue(forge.detect_limit(self.p, "claude", raw, 0))
        self.assertTrue(forge.detect_limit(self.p, "claude", raw.replace("isUsingOverage", "overageInUse"), 0))
        self.assertIsNone(forge.detect_limit(proj(claude={"allow_overage": True}), "claude", raw, 0))
        self.assertIsNone(forge.detect_limit(self.p, "glm", raw, 0))   # guard is claude-only
        ok = '{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","isUsingOverage":false}}\n'
        self.assertIsNone(forge.detect_limit(self.p, "claude", ok, 0))

    def test_api_retry_stop(self):
        ev = lambda n, c: '{"type":"system","subtype":"api_retry","attempt":%d,"error_status":%d}' % (n, c)
        self.assertIsNone(forge.api_retry_stop(ev(2, 401)))
        self.assertEqual(forge.api_retry_stop(ev(1, 401) + "\n" + ev(3, 401)), "auth")
        self.assertEqual(forge.api_retry_stop(ev(3, 429)), "limit")
        self.assertIsNone(forge.api_retry_stop(ev(5, 529)))      # overload: let Claude Code keep retrying
        self.assertIsNone(forge.api_retry_stop("no events"))

    def test_legacy_message(self):
        self.assertTrue(forge.detect_limit(self.p, "codex", "You've hit your usage limit.", 1))
        self.assertIsNone(forge.detect_limit(self.p, "codex", "You've hit your usage limit.", 0))


class Grok(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.out = Path(self.td.name) / "M1-T001-work-grok-20261015-120000.out"
        self.schema = Path(self.td.name) / "review.json"
        self.schema.write_text('{"type":"object"}')

    def tearDown(self):
        self.td.cleanup()

    def test_cross_review_with_grok(self):
        p = proj(workers=["claude", "grok"])
        self.assertEqual(forge.pick_reviewer(p, "claude"), "grok")
        self.assertEqual(forge.pick_reviewer(p, "grok"), "claude")
        p = proj(workers=["claude", "codex"], review_pool=["grok"])
        self.assertEqual(forge.pick_reviewer(p, "claude"), "grok")
        self.assertEqual(forge.pick_reviewer(proj(workers=["grok"]), "grok"), "codex")   # legacy partner
        # existing configs without grok are unaffected
        self.assertEqual(forge.pick_reviewer(proj(workers=["claude", "codex"]), "claude"), "codex")

    def test_work_argv(self):
        p = proj(grok={"model": "grok-4.6", "max_turns": 40})
        cmd = forge.build_cmd(p, "grok", "work", "PROMPT", "/wt", self.out, None)
        self.assertEqual(cmd[0], "grok")
        self.assertNotIn("PROMPT", cmd)                         # prompt goes via file, not argv
        i = cmd.index("--prompt-file")
        self.assertTrue(cmd[i + 1].endswith("M1-T001-work-grok-20261015-120000.prompt.md"))
        for flag, val in (("--cwd", "/wt"), ("--sandbox", "workspace"), ("-m", "grok-4.6"),
                          ("--max-turns", "40"), ("--output-format", "streaming-messages-json")):
            self.assertEqual(cmd[cmd.index(flag) + 1], val)
        self.assertIn("--always-approve", cmd)
        self.assertIn("--disable-web-search", cmd)

    def test_review_argv_readonly(self):
        cmd = forge.build_cmd(proj(), "grok", "review", "P", "/wt", self.out, self.schema)
        self.assertEqual(cmd[cmd.index("--sandbox") + 1], "read-only")
        self.assertEqual(cmd[cmd.index("--tools") + 1], forge.GROK_DEFAULT_TOOLS_RO)
        self.assertEqual(cmd[cmd.index("--json-schema") + 1], '{"type":"object"}')
        self.assertNotIn("--always-approve", cmd)
        self.assertNotIn("--output-format", cmd)                # --json-schema implies json
        cmd = forge.build_cmd(proj(), "grok", "plan", "P", "/r", self.out, None)
        self.assertEqual(cmd[cmd.index("--output-format") + 1], "streaming-messages-json")

    def test_parse_outputs(self):
        res = '{"type":"assistant","message":{}}\n{"type":"result","is_error":false,"result":"done","total_cost_usd":0.5}'
        self.assertEqual(forge.parse_grok_output(res), ("done", None, 0.5, False))
        # streaming result with snake_case structured_output
        res_so = '{"type":"result","is_error":false,"result":"ok","structured_output":{"verdict":"PASS"},"total_cost_usd":0.1}'
        text, data, cost, err = forge.parse_grok_output(res_so)
        self.assertEqual((text, data, cost, err), ("ok", {"verdict": "PASS"}, 0.1, False))
        # streaming result with camelCase aliases (structuredOutput / isError / totalCostUsd)
        res_cam = '{"type":"result","isError":false,"result":"ok","structuredOutput":{"verdict":"PASS"},"totalCostUsd":0.2}'
        text, data, cost, err = forge.parse_grok_output(res_cam)
        self.assertEqual((text, data, cost, err), ("ok", {"verdict": "PASS"}, 0.2, False))
        # compact --json-schema object: verdict only in camelCase structuredOutput
        js = '{"text":"narrative","stopReason":"end_turn","sessionId":"s","structuredOutput":{"verdict":"PASS","summary":"ok","issues":[]}}'
        text, data, cost, err = forge.parse_grok_output(js)
        self.assertEqual(text, "narrative")
        self.assertEqual(data["verdict"], "PASS")
        self.assertFalse(err)
        # pretty-printed --json-schema blob (real Grok CLI shape; line-by-line alone misses it)
        pretty = (
            '{\n'
            '  "text": "thinking... {\\"verdict\\": \\"FAIL\\"}",\n'
            '  "stopReason": "end_turn",\n'
            '  "sessionId": "abc",\n'
            '  "total_cost_usd": 0.5,\n'
            '  "structuredOutput": {\n'
            '    "verdict": "PASS",\n'
            '    "summary": "real verdict",\n'
            '    "issues": [{"severity": "nit", "problem": "x"}]\n'
            '  }\n'
            '}\n'
        )
        text, data, cost, err = forge.parse_grok_output(pretty)
        self.assertEqual(data["verdict"], "PASS")
        self.assertEqual(data["summary"], "real verdict")
        self.assertEqual(cost, 0.5)
        self.assertFalse(err)
        # snake_case structured_output on the json-format object still works
        js_snake = '{"text":"t","stop_reason":"end_turn","session_id":"s","structured_output":{"verdict":"PASS"}}'
        _, data, _, err = forge.parse_grok_output(js_snake)
        self.assertEqual(data["verdict"], "PASS")
        self.assertFalse(err)
        # text-only fallback still used by callers via parse_json_blob when no structuredOutput
        js_text = '{"text":"{\\"verdict\\":\\"PASS\\"}","stopReason":"end_turn","sessionId":"s"}'
        text, data, cost, err = forge.parse_grok_output(js_text)
        self.assertIsNone(data)
        self.assertEqual(forge.parse_json_blob(text), {"verdict": "PASS"})
        self.assertFalse(err)
        t, _, _, err = forge.parse_grok_output('{"type":"error","message":"Not signed in."}\nError: Not signed in.')
        self.assertTrue(err)
        self.assertEqual(t, "Not signed in.")
        self.assertEqual(forge.parse_grok_output("garbage"), ("", None, 0.0, False))


    def test_limits_and_auth(self):
        p = proj()
        self.assertIn("login", forge.detect_limit(p, "grok", '{"type":"error","message":"Not signed in. run grok login"}', 1))
        self.assertTrue(forge.detect_limit(p, "grok", "Error: 429 Too Many Requests", 1))
        self.assertTrue(forge.detect_limit(p, "grok", '{"type":"error","message":"rate limit exceeded"}', 0, result_is_error=True))
        self.assertIsNone(forge.detect_limit(p, "grok", "test 429 passed, quota module ok", 0))
        self.assertIsNone(forge.detect_limit(p, "grok", "assertion failed in test_foo", 1))


OC = {"harness": "opencode", "model": "opencode-go/kimi-k3"}


class Families(unittest.TestCase):
    def setUp(self):
        reset_limits()

    def test_registry_and_families(self):
        p = proj(**{"oc-kimi": OC, "oc-glm": {"harness": "opencode", "model": "opencode-go/glm-5.3"},
                    "oc-x": {"harness": "opencode", "model": "p/odd", "family": "acme"}, "junk": {"model": "x"}})
        self.assertEqual(forge.vendor_names(p), ["claude", "codex", "glm", "grok", "oc-kimi", "oc-glm", "oc-x"])
        self.assertEqual([forge.family_of(p, v) for v in ("claude", "glm", "oc-kimi", "oc-glm", "oc-x")],
                         ["anthropic", "zhipu", "moonshot", "zhipu", "acme"])
        self.assertEqual(forge.harness_of(p, "oc-kimi"), "opencode")
        self.assertIsNone(forge.harness_of(p, "junk"))       # no harness = not a vendor

    def test_review_prefers_other_family_and_cli(self):
        oc_glm = {"harness": "opencode", "model": "opencode-go/glm-5.3"}
        p = proj(workers=["oc-kimi", "oc-glm", "claude"], **{"oc-kimi": OC, "oc-glm": oc_glm})
        self.assertEqual(forge.pick_reviewer(p, "oc-kimi"), "claude")     # other family + other CLI
        p = proj(workers=["oc-kimi", "oc-glm"], **{"oc-kimi": OC, "oc-glm": oc_glm})
        self.assertEqual(forge.pick_reviewer(p, "oc-kimi"), "oc-glm")     # other family, same CLI
        p = proj(workers=["oc-glm", "oc-kimi"], **{"oc-kimi": OC, "oc-glm": oc_glm})
        self.assertEqual(forge.pick_reviewer(p, "glm"), "oc-kimi")        # same-family oc-glm ranks last
        self.assertEqual(forge.review_candidates(p, "glm"), ["oc-kimi", "oc-glm"])


class Cooldowns(unittest.TestCase):
    def setUp(self):
        reset_limits()

    def tearDown(self):
        reset_limits()

    def cool(self, v, secs=600):
        forge.COOLDOWNS[v] = {"until": time.time() + secs, "why": "test"}

    def test_worker_skips_cooling_vendor(self):
        p = proj(workers=["claude", "codex"])
        self.cool("claude")
        self.assertEqual({forge.pick_worker(p, {"agent": "any"}, 1) for _ in range(4)}, {"codex"})
        self.assertIsNone(forge.pick_worker(p, {"agent": "claude"}, 1))   # pinned, no rotation yet
        self.assertEqual(forge.pick_worker(p, {"agent": "claude"}, 3), "codex")   # swap rotation
        self.cool("codex")
        self.assertIsNone(forge.pick_worker(p, {"agent": "any"}, 1))
        forge.COOLDOWNS["codex"]["until"] = time.time() - 1                 # expired = free again
        self.assertEqual(forge.pick_worker(p, {"agent": "any"}, 1), "codex")

    def test_peek_does_not_advance(self):
        p = proj(workers=["claude", "codex"])
        first = forge.pick_worker(p, {"agent": "any"}, 1, advance=False)
        self.assertEqual(forge.pick_worker(p, {"agent": "any"}, 1, advance=False), first)

    def test_reviewer_falls_back_then_waits(self):
        p = proj(workers=["claude", "codex", "glm"])
        self.cool("codex")
        self.assertEqual(forge.pick_reviewer(p, "claude"), "glm")      # next best is free
        self.cool("glm")
        self.assertEqual(forge.pick_reviewer(p, "claude"), forge.WAIT)
        self.assertEqual(forge.pick_reviewer(proj(reviewer="codex"), "claude"), forge.WAIT)
        self.assertIsNone(forge.pick_reviewer(proj(reviewer="none"), "claude"))

    def test_disabled_vendor(self):
        forge.DISABLED["codex"] = "not logged in"
        self.assertFalse(forge.available(proj(), "codex"))
        self.assertEqual(forge.pick_reviewer(proj(workers=["claude", "codex"]), "claude"), forge.WAIT)

    def test_allowance_windows(self):
        p = proj(**{"oc-kimi": dict(OC, monthly_usd=100, allowance_margin=1.0)})
        t0 = time.time()
        forge.SPEND["oc-kimi"] = [[t0 - 3600, 12.0], [t0 - 60, 9.0]]   # $21 in 5 h > 20% of $100
        until = forge.allowance_until(p, "oc-kimi", at=t0)
        self.assertAlmostEqual(until, t0 - 3600 + 5 * 3600, delta=1)   # frees when the $12 run ages out
        self.assertFalse(forge.available(p, "oc-kimi"))
        forge.SPEND["oc-kimi"] = [[t0 - 60, 19.0]]
        self.assertTrue(forge.available(p, "oc-kimi"))
        self.assertEqual(forge.allowance_until(proj(), "claude"), 0)   # no monthly_usd = no tracking
        forge.record_spend("oc-kimi", 2.5)
        self.assertEqual(len(forge.SPEND["oc-kimi"]), 2)


class ResetTimes(unittest.TestCase):
    def test_claude_resets_at(self):
        t = int(time.time()) + 7200
        raw = ('{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":%d}}\n'
               '{"type":"rate_limit_event","rate_limit_info":{"status":"rejected","resetsAt":%d}}\n') % (t + 86400, t)
        self.assertEqual(forge.limit_reset_time(raw), t)               # rejected event wins
        self.assertEqual(forge.limit_reset_time(raw.replace(str(t), str(t * 1000))), t)   # ms epochs

    def test_text_forms(self):
        got = forge.limit_reset_time("You've hit your usage limit. Try again in 2 hours 13 minutes.")
        self.assertAlmostEqual(got, time.time() + 2 * 3600 + 13 * 60, delta=5)
        iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 1800))
        self.assertAlmostEqual(forge.limit_reset_time(f"limit reached; resets at {iso}"), time.time() + 1800, delta=5)
        self.assertIsNone(forge.limit_reset_time("Your limit will reset at 2099-10-14 18:00:00"))  # no zone
        self.assertIsNone(forge.limit_reset_time("Try again later."))
        self.assertEqual(forge.duration_secs("1h30m"), 5400)


class OpenCode(unittest.TestCase):
    def setUp(self):
        reset_limits()
        self.td = tempfile.TemporaryDirectory()
        root = Path(self.td.name) / "proj"
        (root / ".forge" / "logs").mkdir(parents=True)
        (root / ".git").mkdir()
        (root / ".claude").mkdir()
        (root / ".claude" / "settings.json").write_text(json.dumps({"permissions": {"deny": [
            "Bash(git push*)", "Bash(curl *)", "Edit(forge.toml)"]}}))
        self.root, self.wt = root, root / ".forge" / "worktrees" / "M1-T001"
        self.wt.mkdir(parents=True)
        self.out = root / ".forge" / "logs" / "M1-T001-work-oc-kimi-1.out"
        home = Path(self.td.name) / "home"
        self.oc = dict(OC, sandbox="none")
        self.saved_home = os.environ.get("HOME")
        os.environ["HOME"] = str(home)   # sandbox_wrap creates OpenCode state dirs under ~

    def tearDown(self):
        os.environ["HOME"] = self.saved_home or ""
        self.td.cleanup()

    def p(self, **a):
        return P({"agents": {"oc-kimi": dict(self.oc, **a)}}, root=self.root)

    def test_argv_unsandboxed(self):
        cmd = forge.build_cmd(self.p(variant="high"), "oc-kimi", "work", "PROMPT", self.wt, self.out, None)
        self.assertEqual(cmd[:5], ["opencode", "run", "--standalone", "--format", "json"])
        # OpenCode 2.x: no --dir/--variant; cwd comes from Popen/bwrap, variant rides on -m.
        self.assertEqual(cmd[cmd.index("-m") + 1], "opencode-go/kimi-k3#high")
        self.assertNotIn("--dir", cmd)
        self.assertNotIn("--variant", cmd)
        self.assertIn("--auto", cmd)
        self.assertEqual(cmd[-1], "PROMPT")
        review = forge.build_cmd(self.p(), "oc-kimi", "review", "P", self.wt, self.out, None)
        self.assertNotIn("--auto", review)

    def test_long_prompt_goes_via_file(self):
        cmd = forge.build_cmd(self.p(), "oc-kimi", "work", "x" * 200_000, self.wt, self.out, None)
        self.assertTrue(cmd[cmd.index("--file") + 1].endswith(".prompt.md"))
        self.assertLess(len(cmd[-1]), 500)

    def test_model_required(self):
        with self.assertRaises(RuntimeError):
            forge.build_cmd(self.p(model=""), "oc-kimi", "work", "P", self.wt, self.out, None)

    def test_bwrap_sandbox(self):
        p = self.p(sandbox="bwrap", bwrap="/bin/sh")       # any existing binary stands in for bwrap
        cmd = forge.build_cmd(p, "oc-kimi", "work", "P", self.wt, self.out, None)
        self.assertEqual(cmd[0], "/bin/sh")
        pairs = [(cmd[i], cmd[i + 1]) for i in range(len(cmd) - 1)]
        self.assertIn(("--ro-bind", "/"), pairs)
        self.assertIn(("--tmpfs", str(self.root / ".forge")), pairs)          # state.json/logs hidden
        i_hide = cmd.index(str(self.root / ".forge"))
        i_wt = max(i for i, x in enumerate(cmd) if x == str(self.wt) and cmd[i - 1] == "--bind")
        self.assertLess(i_hide, i_wt)                                          # worktree re-mounted on top
        self.assertEqual(cmd[cmd.index("--chdir") + 1], str(self.wt))
        self.assertIn("opencode", cmd)
        rv = forge.build_cmd(p, "oc-kimi", "review", "P", self.wt, self.out, None)
        self.assertEqual(rv[rv.index(str(self.wt)) - 1], "--ro-bind")         # reviewers can't write
        with self.assertRaises(RuntimeError):
            forge.build_cmd(self.p(sandbox="bwrap", bwrap="/no/such/bwrap"), "oc-kimi", "work", "P", self.wt, self.out, None)

    def test_permissions(self):
        work = forge.opencode_permissions(self.p(), self.oc, "work")
        self.assertEqual(work["edit"], "allow")
        self.assertEqual(list(work["bash"].items()), [("*", "allow"), ("git push*", "deny"), ("curl *", "deny")])
        self.assertEqual(work["webfetch"], "deny")
        self.assertEqual(forge.opencode_permissions(self.p(), self.oc, "review"),
                         {"edit": "deny", "bash": "deny", "webfetch": "deny"})

    def test_parse_output(self):
        ev = lambda **k: json.dumps(k)
        raw = "\n".join([
            ev(type="step_start", part={"messageID": "m1"}),
            ev(type="text", part={"messageID": "m1", "text": "Let me look."}),
            ev(type="tool_use", part={"messageID": "m1", "tool": "read"}),
            ev(type="step_finish", part={"reason": "tool-calls", "cost": 0.01,
                                         "tokens": {"input": 100, "output": 10, "cache": {"read": 50}}}),
            ev(type="text", part={"messageID": "m2", "text": '{"verdict":"PASS"}'}),
            ev(type="step_finish", part={"reason": "stop", "cost": 0.02, "tokens": {"input": 200, "output": 20}}),
            "some stray stderr line"])
        text, cost, tokens, errors = forge.parse_opencode_output(raw)
        self.assertEqual(forge.parse_json_blob(text), {"verdict": "PASS"})    # last message only
        self.assertAlmostEqual(cost, 0.03)
        self.assertEqual((tokens["input"], tokens["output"], tokens["cache_read"]), (300, 30, 50))
        self.assertEqual(errors, [])
        err = ev(type="error", error={"name": "APIError", "data": {"message": "Rate limit exceeded", "statusCode": 429}})
        self.assertEqual(forge.parse_opencode_output(err)[3], [(429, "Rate limit exceeded")])

    def test_limit_and_auth_detection(self):
        p = self.p()
        ev = lambda st, msg: json.dumps({"type": "error", "error": {"name": "APIError", "data": {"message": msg, "statusCode": st}}})
        self.assertIn("usage/rate limit", forge.detect_limit(p, "oc-kimi", ev(429, "slow down"), 0, True))
        self.assertIn("monthly", forge.detect_limit(p, "oc-kimi", ev(None, "monthly usage limit reached"), 1, True))
        why = forge.detect_limit(p, "oc-kimi", ev(401, "Unauthorized"), 1, True)
        self.assertTrue(why.startswith(forge.AUTH_PREFIX))
        self.assertIsNone(forge.detect_limit(p, "oc-kimi", ev(500, "internal error"), 1, True))
        self.assertIsNone(forge.detect_limit(p, "oc-kimi", '{"type":"text","part":{"text":"429 tests ok"}}', 0))

    def test_usage_text_is_setup_problem(self):
        p = self.p()
        usage = "DESCRIPTION\n  Run OpenCode with a message\n\nUSAGE\n  opencode run [flags] [<message...>]\n"
        self.assertTrue(forge.detect_limit(p, "oc-kimi", usage, 1).startswith(forge.AUTH_PREFIX))
        self.assertIsNone(forge.detect_limit(p, "oc-kimi", usage, 0))

    def test_opencode2_error_shape(self):
        # OpenCode 2.1 (seen 2026-10-21): {"type":"error","error":{"type":...,"message":...,"status":N}}
        p = self.p()
        ev = lambda st, msg: json.dumps({"type": "error", "error": {"type": "provider.invalid-request",
                                                                    "message": msg, "status": st}})
        self.assertEqual(forge.parse_opencode_output(ev(429, "slow down"))[3], [(429, "slow down")])
        self.assertIn("usage/rate limit", forge.detect_limit(p, "oc-kimi", ev(429, "slow down"), 1, True))
        self.assertTrue(forge.detect_limit(p, "oc-kimi", ev(401, "nope"), 1, True).startswith(forge.AUTH_PREFIX))
        region = ("Upstream request failed: This Go model requires Global regions. "
                  "Select Global in your workspace's Privacy settings to use it.")
        self.assertTrue(forge.detect_limit(p, "oc-kimi", ev(400, region), 1, True).startswith(forge.AUTH_PREFIX))
        self.assertIsNone(forge.detect_limit(p, "oc-kimi", ev(500, "internal error"), 1, True))


class PoolP(P):
    """P with an event sink (set_pool_cooldown logs an event)."""
    def __init__(self, cfg, root="/nonexistent-project"):
        super().__init__(cfg, root)
        self.events = []

    def event(self, msg):
        self.events.append(msg)


def _pool_writer(path_dir, n):
    forge.POOL_DIR = Path(path_dir)
    for i in range(n):
        forge.pool_append("go", {"kind": "spend", "usd": 0.01, "vendor": "w", "project": str(i)})


class Pools(unittest.TestCase):
    """Shared plan-wide pools: one flock'd JSONL ledger per pool, shared across projects."""
    def setUp(self):
        reset_limits()
        self.td = tempfile.TemporaryDirectory()
        self.old_dir = forge.POOL_DIR
        forge.POOL_DIR = Path(self.td.name)
        forge.POOL_CACHE.clear()

    def tearDown(self):
        forge.POOL_DIR = self.old_dir
        forge.POOL_CACHE.clear()
        self.td.cleanup()

    def cfg(self, root="/proj-a", **caps):
        caps = caps or dict(usd_5h=2.0, usd_7d=5.0, usd_30d=10.0)
        return PoolP({"agents": {"workers": ["claude", "oc-glm", "oc-kimi"],
                                 "oc-glm": dict(OC, model="opencode-go/glm-5.3", pool="go"),
                                 "oc-kimi": dict(OC, pool="go"),
                                 "oc-free": dict(OC, model="opencode/x-free")},
                      "pools": {"go": caps}}, root)

    def test_not_pooled_is_unaffected(self):
        p = self.cfg()
        self.assertIsNone(forge.pool_of(p, "oc-free"))
        self.assertIsNone(forge.pool_of(p, "claude"))
        self.assertEqual(forge.pool_until(p, "oc-free"), 0)
        forge.record_pool_spend(p, "oc-free", 99.0)
        self.assertFalse((forge.POOL_DIR / "go.jsonl").exists())
        self.assertTrue(forge.available(p, "oc-free"))

    def test_spend_shared_across_vendors_and_projects(self):
        a, b = self.cfg("/proj-a"), self.cfg("/proj-b")
        forge.record_pool_spend(a, "oc-glm", 1.2)
        self.assertTrue(forge.available(b, "oc-kimi"))
        forge.record_pool_spend(b, "oc-kimi", 0.9)          # $2.10 in 5 h >= $2 cap
        for proj_, v in ((a, "oc-glm"), (a, "oc-kimi"), (b, "oc-glm"), (b, "oc-kimi")):
            self.assertFalse(forge.available(proj_, v), (proj_.root, v))
        self.assertTrue(forge.available(a, "oc-free"))
        self.assertTrue(forge.available(a, "claude"))
        until = forge.pool_until(a, "oc-glm")
        self.assertAlmostEqual(until, time.time() + 5 * 3600, delta=5)   # frees when the $1.20 run ages out
        self.assertEqual([(l, round(s, 2), c) for l, s, c in forge.pool_use(a, "go")],
                         [("5h", 2.1, 2.0), ("7d", 2.1, 5.0), ("30d", 2.1, 10.0)])
        self.assertAlmostEqual(forge.next_wakeup(a), until, delta=1)   # --wait sleeps until then

    def test_windows_age_out(self):
        p = self.cfg()
        t0 = time.time()
        forge.pool_append("go", {"kind": "spend", "usd": 1.5, "vendor": "oc-glm", "t": t0 - 6 * 3600})
        forge.pool_append("go", {"kind": "spend", "usd": 1.0, "vendor": "oc-glm", "t": t0 - 60})
        self.assertTrue(forge.available(p, "oc-glm"))        # 5 h window holds only $1.00
        forge.pool_append("go", {"kind": "spend", "usd": 3.0, "vendor": "oc-kimi", "t": t0 - 2 * 86400})
        until = forge.pool_until(p, "oc-glm", at=t0)
        self.assertGreater(until, 0)
        self.assertFalse(forge.available(p, "oc-glm"))      # 7 d: $5.50 >= $5 cap
        self.assertAlmostEqual(until, t0 - 2 * 86400 + 7 * 86400, delta=2)   # frees when the oldest ($3.00) run ages out

    def test_no_caps_means_ledger_only(self):
        p = PoolP({"agents": {"oc-glm": dict(OC, pool="go")}})
        forge.record_pool_spend(p, "oc-glm", 50.0)
        self.assertTrue(forge.available(p, "oc-glm"))
        self.assertEqual(forge.pool_use(p, "go"), [])

    def test_plan_limit_cools_whole_pool_everywhere(self):
        a, b = self.cfg("/proj-a"), self.cfg("/proj-b")
        why = "OpenCode usage/rate limit (Go usage limit exceeded)"
        self.assertTrue(forge.is_plan_limit(a, "oc-glm", why))
        self.assertFalse(forge.is_plan_limit(a, "oc-glm", "OpenCode usage/rate limit (slow down)"))
        self.assertFalse(forge.is_plan_limit(a, "oc-free", why))   # not pooled
        until = time.time() + 3600
        forge.set_pool_cooldown(a, "oc-glm", until, why)
        self.assertIn("pool go", a.events[-1])
        for v in ("oc-glm", "oc-kimi"):
            self.assertAlmostEqual(forge.cooldown_until(b, v), until, delta=1)
        self.assertTrue(forge.available(b, "oc-free"))
        self.assertEqual(forge.pick_reviewer(b, "claude"), forge.WAIT)   # every non-claude candidate is pooled
        forge.pool_append("go", {"kind": "clear", "project": "/proj-b"})
        self.assertTrue(forge.available(a, "oc-kimi"))

    def test_429_from_any_pooled_vendor_cools_pool(self):
        p = self.cfg()
        self.assertTrue(forge.pool_wide_limit(p, "oc-kimi", "OpenCode usage/rate limit (HTTP 429)"))
        self.assertTrue(forge.pool_wide_limit(p, "oc-glm", "HTTP 429 on repeated retries"))
        self.assertTrue(forge.pool_wide_limit(p, "oc-glm", "usage limit message", "x Go usage limit exceeded"))
        self.assertFalse(forge.pool_wide_limit(p, "oc-free", "OpenCode usage/rate limit (HTTP 429)"))
        self.assertFalse(forge.pool_wide_limit(p, "oc-glm", "paid overage in use"))

    def test_custom_plan_limit_re(self):
        p = self.cfg()
        p.cfg["pools"]["go"]["plan_limit_re"] = r"account quota"
        self.assertTrue(forge.is_plan_limit(p, "oc-glm", "Account quota exhausted"))
        self.assertFalse(forge.is_plan_limit(p, "oc-glm", "Go usage limit exceeded"))

    def test_monthly_usd_still_per_vendor(self):
        p = self.cfg(usd_5h=100.0)
        p.cfg["agents"]["oc-kimi"].update(monthly_usd=10, allowance_margin=1.0)
        forge.SPEND["oc-kimi"] = [[time.time() - 60, 2.5]]   # > 20% of $10 in 5 h
        self.assertFalse(forge.available(p, "oc-kimi"))
        self.assertTrue(forge.available(p, "oc-glm"))         # pool itself is far under its cap

    def test_torn_lines_skipped_and_concurrent_appends(self):
        import multiprocessing as mp
        procs = [mp.Process(target=_pool_writer, args=(self.td.name, 50)) for _ in range(4)]
        for pr in procs:
            pr.start()
        for pr in procs:
            pr.join()
        with open(forge.POOL_DIR / "go.jsonl", "a") as fh:
            fh.write('{"kind": "spend", "usd": 9\n')          # torn line from a crash
        self.assertEqual(len(forge.pool_spend("go")), 200)
        self.assertAlmostEqual(sum(c for _, c in forge.pool_spend("go")), 2.0, places=6)

    def test_bad_pool_name(self):
        with self.assertRaises(SystemExit):
            forge.pool_path("../../etc")


if __name__ == "__main__":
    unittest.main()
