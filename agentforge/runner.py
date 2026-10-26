"""run_agent: one headless agent run, from refusal checks to spend accounting and limits.

The steps, each a helper below: refuse (budget / run cap) -> environment + argv -> launch
and supervise (process.py) -> parse the CLI's output (parsers/) -> record spend in state ->
classify a usage limit or setup problem (detect.py) and cool the vendor down.
"""
from __future__ import annotations

import json
import os
import time

from .detect import AUTH_PREFIX, detect_limit
from .glm import glm_env, redact
from .harness import build_cmd
from .harness.opencode import opencode_permissions
from .limits import (COOL_LOCK, DISABLED, default_cooldown_min, disable_vendor, record_spend,
                     set_cooldown)
from .parsers.claude import parse_claude_result
from .parsers.codex import read_out_file
from .parsers.grok import parse_grok_output
from .parsers.jsonblob import parse_json_blob
from .parsers.opencode import parse_opencode_output
from .pools import pool_wide_limit, record_pool_spend, set_pool_cooldown
from .process import run_supervised
from .project import STOP
from .resettime import limit_reset_time
from .util import fmt_time
from .vendors import CLAUDE_CODE_VENDORS, agent_cfg, harness_of

GROK_FLUSH_RETRIES = 6      # Grok can exit before its final JSON is on disk: re-read this often
GROK_FLUSH_WAIT = 0.5       # ...this many seconds apart


class AgentResult:
    """Outcome of one agent run: ok (rc==0), final text, parsed JSON data, cost, log path."""
    def __init__(self, ok, text="", data=None, cost=0.0, log=None, rc=0):
        self.ok, self.text, self.data, self.cost, self.log, self.rc = ok, text, data, cost, log, rc
        self.limited = False   # vendor reported a usage/rate limit; the run was not real work


class _SetupProblem(Exception):
    """Configuration, not the card: the vendor sits out the rest of this run."""


def run_agent(proj, vendor, role, prompt, cwd, tag, schema=None):
    """Run one agent headless with timeout, log everything, return AgentResult.

    A usage limit no longer stops the whole run: the vendor is put in a cooldown (until the
    reset time the CLI reported, else limit_cooldown_min) and res.limited tells the caller to
    try another vendor. Login/key/sandbox problems disable the vendor for this process."""
    refused = _refuse_run(proj, vendor, proj.load_state())
    if refused:
        return refused
    stem = f"{tag}-{role}-{vendor}-{time.strftime('%Y%m%d-%H%M%S')}"
    log, out_file = proj.logs / f"{stem}.log", proj.logs / f"{stem}.out"
    schema_path = proj.root / "schemas" / f"{schema}.json" if schema else None
    is_oc = harness_of(proj, vendor) == "opencode" and not proj.mock
    if is_oc and schema_path:
        prompt += _schema_instructions(schema_path)
    timeout = 60 * proj.c("agents", vendor, "timeout_min", default=45)
    try:
        env, secret = _agent_env(proj, vendor, role, tag, schema_path, is_oc)
        (proj.logs / f"{stem}.prompt.md").write_text(prompt)
        cmd = _agent_cmd(proj, vendor, role, prompt, cwd, out_file, schema_path)
    except _SetupProblem as e:
        return _setup_problem(proj, vendor, str(e))
    proj.event(f"{tag}: {role} -> {vendor} (log {log.name})")
    t0 = time.time()
    stdin_text = prompt if _prompt_on_stdin(proj, vendor, is_oc) else None
    rc, retry_stop = run_supervised(proj, vendor, tag, cmd, cwd, env, stdin_text, log, timeout)
    raw = _read_log(log, secret)
    raw, text, data, cost, tokens, result_is_error = _parse_output(proj, vendor, raw, log, out_file, is_oc)
    if data is None and schema:
        data = parse_json_blob(text)
    dt = int(time.time() - t0)
    record_spend(vendor, cost)
    record_pool_spend(proj, vendor, cost)
    proj.update_state(lambda s: _account_run(s, vendor, cost, tokens))
    proj.event(f"{tag}: {vendor} {role} finished rc={rc} {dt}s ${cost:.2f}"
               + (" (nominal, not billed by Anthropic)" if vendor == "glm" else ""))
    res = AgentResult(rc == 0 and not (is_oc and result_is_error), text, data, cost, log, rc)
    why = _limit_reason(proj, vendor, raw, rc, result_is_error, retry_stop)
    if not why:
        return res
    if why.startswith(AUTH_PREFIX):
        return _setup_problem(proj, vendor, why[len(AUTH_PREFIX):])
    _cool_down(proj, vendor, tag, why, raw)
    res.limited = True
    return res


def _limited(why):
    res = AgentResult(False, why)
    res.limited = True
    return res


def _setup_problem(proj, vendor, why):
    # Not the card's fault: no attempt is charged, the vendor sits out the rest of this run.
    disable_vendor(proj, vendor, why)
    return _limited(why)


def _refuse_run(proj, vendor, st):
    """AgentResult when this run must not start (Claude budget spent, global run cap), else None."""
    max_usd = proj.c("budget", "max_total_usd", default=0)
    if max_usd and vendor == "claude" and st.get("total_usd", 0) >= max_usd:
        # budget.max_total_usd counts only Claude's spend, so it refuses only Claude: Claude
        # sits out the rest of this run (no attempt charged; cards fall back to other vendors).
        why = f"claude budget ${max_usd} exhausted; claude disabled"
        with COOL_LOCK:
            first = vendor not in DISABLED
            DISABLED[vendor] = why
        if first:
            proj.event(f"run: {why}")
        return _limited(why)
    max_runs = proj.c("budget", "max_agent_runs", default=0)
    if max_runs and st.get("agent_runs", 0) >= max_runs:
        STOP.set()
        return AgentResult(False, f"global run cap {max_runs} reached")
    return None


def _schema_instructions(schema_path):
    # opencode run has no schema flag: put the schema in the prompt; parse_json_blob reads the reply.
    return ("\n\n## Required JSON schema for your final message\n```json\n"
            + schema_path.read_text().strip() + "\n```\nYour final message must be only that JSON object.\n")


def _agent_env(proj, vendor, role, tag, schema_path, is_oc):
    """(environment, secret to redact from the log or None) for this run."""
    env = dict(os.environ, FORGE_ROLE=role, FORGE_TASK=tag, FORGE_SCHEMA=str(schema_path or ""))
    secret = None
    if vendor == "glm" and not proj.mock:
        try:
            env = glm_env(proj.c("agents", "glm", default={}), env)
        except RuntimeError as e:
            raise _SetupProblem(f"{e} (see docs/VENDORS.md)") from e
        secret = env["ANTHROPIC_AUTH_TOKEN"]
    if is_oc:
        env["OPENCODE_PERMISSION"] = json.dumps(opencode_permissions(proj, agent_cfg(proj, vendor), role))
    return env, secret


def _agent_cmd(proj, vendor, role, prompt, cwd, out_file, schema_path):
    try:
        return build_cmd(proj, vendor, role, prompt, cwd, out_file, schema_path)
    except RuntimeError as e:   # missing model / bwrap: configuration, fix and rerun
        raise _SetupProblem(str(e)) from e


def _prompt_on_stdin(proj, vendor, is_oc):
    # claude/glm/opencode get the prompt as argv, grok as --prompt-file; codex/mock read stdin.
    return proj.mock or not (vendor in CLAUDE_CODE_VENDORS or vendor == "grok" or is_oc)


def _read_log(log, secret):
    raw = log.read_text(errors="replace")
    if secret and secret in raw:   # never keep the key on disk, even if a CLI echoed it
        raw = redact(raw, secret)
        log.write_text(raw)
    return raw


def _parse_output(proj, vendor, raw, log, out_file, is_oc):
    """(raw, text, data, cost, tokens, result_is_error) from whatever this CLI wrote.
    raw is returned because Grok's log may be re-read while it finishes flushing."""
    tokens = None
    if vendor in CLAUDE_CODE_VENDORS and not proj.mock:
        text, data, cost, result_is_error = parse_claude_result(raw)
    elif vendor == "grok" and not proj.mock:
        raw, (text, data, cost, result_is_error) = _parse_grok_log(raw, log)
    elif is_oc:
        text, cost, tokens, errors = parse_opencode_output(raw)
        data, result_is_error = None, bool(errors)
        if not text and errors:
            text = errors[-1][1]
    else:
        text, data, cost, result_is_error = read_out_file(out_file), None, 0.0, False
    return raw, text, data, cost, tokens, result_is_error


def _parse_grok_log(raw, log):
    # Grok Build can exit before the final pretty JSON lands on disk; retry briefly.
    parsed = parse_grok_output(raw)
    for _ in range(GROK_FLUSH_RETRIES):
        text, data, _cost, is_error = parsed
        if data is not None or text or is_error:
            break
        time.sleep(GROK_FLUSH_WAIT)
        raw = log.read_text(errors="replace")
        parsed = parse_grok_output(raw)
    return raw, parsed


def _account_run(s, vendor, cost, tokens):
    """state.json update for one finished run (called under STATE_LOCK by update_state).

    Only real Claude counts toward total_usd (= budget.max_total_usd). glm's cost is
    Claude Code's estimate at Anthropic prices, which means nothing on a Z.ai plan; it is
    kept separately as glm_usd_nominal. Codex reports no cost; grok's reported cost (often
    absent on subscription logins) is kept as grok_usd_reported. OpenCode vendors' cost
    (API-price figures, which is what OpenCode Go's allowances are counted in) goes to
    vendor_usd. spend_log feeds the monthly_usd allowance windows."""
    if vendor == "claude":
        s["total_usd"] = s.get("total_usd", 0) + cost
    elif vendor == "glm":
        s["glm_usd_nominal"] = s.get("glm_usd_nominal", 0) + cost
    elif vendor == "grok":   # xAI subscription/API spend; never counted in budget.max_total_usd
        s["grok_usd_reported"] = s.get("grok_usd_reported", 0) + cost
    else:
        vu = s.setdefault("vendor_usd", {})
        vu[vendor] = round(vu.get(vendor, 0) + cost, 6)
    if cost > 0:
        cutoff = time.time() - 31 * 86400
        sl = s.setdefault("spend_log", {})
        sl[vendor] = [e for e in sl.get(vendor, []) if e[0] > cutoff] + [[time.time(), round(cost, 6)]]
    if tokens:
        vt = s.setdefault("vendor_tokens", {}).setdefault(vendor, {})
        for k, v in tokens.items():
            vt[k] = vt.get(k, 0) + v
    s["agent_runs"] = s.get("agent_runs", 0) + 1
    runs = s.setdefault("vendor_runs", {})
    runs[vendor] = runs.get(vendor, 0) + 1


def _limit_reason(proj, vendor, raw, rc, result_is_error, retry_stop):
    why = detect_limit(proj, vendor, raw, rc, result_is_error)
    if retry_stop == "limit":
        return why or "HTTP 429 on repeated retries"
    if retry_stop == "auth":
        return f"{AUTH_PREFIX}API authentication failed (HTTP 401/403); fix the key/login, then rerun"
    return why


def _cool_down(proj, vendor, tag, why, raw):
    """Pause `vendor` (and its pool, for plan-wide limits) until the limit resets."""
    until = limit_reset_time(raw)
    src = "reported reset" if until else f"no reset time given; {default_cooldown_min(proj, vendor):g} min default"
    until = (until + 60) if until else time.time() + 60 * default_cooldown_min(proj, vendor)
    proj.event(f"{tag}: {vendor} USAGE LIMIT hit ({why}) - attempt not charged; "
               f"{vendor} pauses until {fmt_time(until)} ({src})")
    set_cooldown(proj, vendor, until, why)
    if pool_wide_limit(proj, vendor, why, raw):
        set_pool_cooldown(proj, vendor, until, why)
