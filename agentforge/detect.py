"""Did an agent run hit a usage limit, or a login/key/setup problem? (docs/LIMITS.md)"""
from __future__ import annotations

import re

from .parsers.claude import overage_in_use, rate_limit_events
from .parsers.opencode import parse_opencode_output
from .vendors import CLAUDE_CODE_VENDORS, harness_of

# Grok Build errors meaning "out of quota/rate limited, try later". Matched only on a failed run
# or an error result, like LIMIT_RE.
GROK_LIMIT_RE = re.compile(r"\b429\b|rate[ _-]?limit|usage limit|quota|too many requests|"
                           r"out of credits|insufficient credits|limit (?:reached|exceeded)", re.I)
# Grok Build errors meaning "not logged in / bad key": a setup problem, never the card's fault.
GROK_AUTH_RE = re.compile(r"not signed in|not authenticated|grok login|invalid api key|"
                          r"\b401\b|\b403\b|unauthori[sz]ed", re.I)
# OpenCode (`opencode run`) errors meaning "bad login / key": a setup problem, never the card's fault.
OPENCODE_AUTH_RE = re.compile(r"\b401\b|\b403\b|unauthori[sz]ed|invalid api key|no credentials|"
                              r"not logged in|auth login|authentication", re.I)
# OpenCode/provider account settings that block a model (e.g. OpenCode Go's "This Go model
# requires Global regions. Select Global in your workspace's Privacy settings"): a setup problem
# for the user to fix, never the card's fault, so the vendor is disabled like an auth failure.
OPENCODE_USAGE_RE = re.compile(r"^USAGE\s*\n\s*opencode run", re.M)
OPENCODE_SETUP_RE = re.compile(r"requires global region|privacy settings", re.I)

# Vendor CLI messages meaning "out of quota, try later". Matched only on a failed run.
LIMIT_RE = re.compile(r"usage limit|rate limit|hit your limit|quota exceeded|limit reached", re.I)
# Z.ai business error codes that mean "quota/rate limit, try later" (docs.z.ai/api-reference/api-code):
# 1113 no balance, 1302 request rate, 1305 overloaded, 1308 usage limit, 1309 plan expired,
# 1310 weekly/monthly limit, 1313 fair-use throttle, 1316-1321 5-hour/7-day limits.
ZAI_LIMIT_CODES = ("1113", "1302", "1305", "1308", "1309", "1310", "1313",
                   "1316", "1317", "1318", "1319", "1320", "1321")
# Z.ai answers a limit with HTTP 429 or a JSON error code from the list above, e.g.
#   'API Error: 429 {"error":{"code":"1308","message":"Usage limit reached"}}'
ZAI_LIMIT_RE = re.compile(r"""
    (?:API\ Error|HTTP|status) [^0-9\n]{0,12} 429\b     # "API Error: 429", "HTTP/1.1 429", "status 429"
  | ["']?code["']? \s*[:=]\s* ["']?                     # "code": "1308" / code=1308 / 'code': 1308
    (?:""" + "|".join(ZAI_LIMIT_CODES) + r""")\b
""", re.I | re.X)


AUTH_PREFIX = "auth: "   # detect_limit reasons starting with this are login/key problems, not limits


def detect_limit(proj, vendor, raw, rc, result_is_error=False):
    """Return a short reason string when this run hit a usage limit, else None.
    Reasons starting with AUTH_PREFIX mean a login/key problem instead (run_agent disables
    the vendor for this process rather than cooling it down).

    - any vendor, failed run: LIMIT_RE on the last 4000 chars of the log (original behaviour);
    - claude/glm: a stream-json rate_limit_event with status "rejected";
    - glm, failed run or is_error result: HTTP 429 or a Z.ai limit code (ZAI_LIMIT_CODES);
    - claude only: rate_limit_info.isUsingOverage / overageInUse true, unless
      [agents.claude] allow_overage = true (paid extra usage is refused by default);
    - opencode vendors: `error` events with statusCode 401/403 (auth) or 429 / limit wording."""
    failed = rc != 0 or result_is_error
    why = None
    if vendor in CLAUDE_CODE_VENDORS:
        why = _claude_stream_limit(proj, vendor, raw)
    if why is None and harness_of(proj, vendor) == "opencode" and not proj.mock:
        why = _opencode_limit(raw, failed)
    if why is None and vendor == "grok" and failed:
        why = _grok_limit(raw)
    if why is not None:
        return why
    if vendor == "glm" and failed and ZAI_LIMIT_RE.search(raw[-4000:]):
        return "Z.ai quota/rate limit (HTTP 429 / code 13xx)"
    if failed and LIMIT_RE.search(raw[-4000:]):
        return "usage limit message"
    return None


def _claude_stream_limit(proj, vendor, raw):
    """claude/glm: a rejected rate_limit_event, or (claude) paid overage that isn't allowed."""
    allow_overage = proj.c("agents", "claude", "allow_overage", default=False)
    for info in rate_limit_events(raw):
        if info.get("status") == "rejected":
            return "rate_limit_event rejected"
        if vendor == "claude" and overage_in_use(info) and not allow_overage:
            return "paid overage in use (allow_overage = false)"
    return None


def _opencode_limit(raw, failed):
    """OpenCode: auth/setup errors (AUTH_PREFIX), limit errors, or argv the CLI rejected."""
    for status, msg in parse_opencode_output(raw)[3]:
        if status in (401, 403) or OPENCODE_AUTH_RE.search(msg):
            return (f"{AUTH_PREFIX}OpenCode provider rejected the login/key ({msg[:120]}); "
                    "run `opencode auth login`, then rerun")
        if OPENCODE_SETUP_RE.search(msg):
            return (f"{AUTH_PREFIX}OpenCode account setting blocks this model ({msg[:160]}); "
                    "fix it in the OpenCode console, then rerun")
        if status == 429 or GROK_LIMIT_RE.search(msg):
            return f"OpenCode usage/rate limit ({msg[:120]})"
    if failed and OPENCODE_USAGE_RE.search(raw[:4000]) and not parse_opencode_output(raw)[0]:
        # The CLI printed its help/usage text instead of running: forge's argv doesn't match
        # this OpenCode version. Never the card's fault; don't charge attempts for it.
        # (The message text is kept as it always was; opencode_cmd now lives in
        # agentforge/harness/opencode.py.)
        return (f"{AUTH_PREFIX}`opencode run` rejected forge's arguments (printed its usage text); "
                "check `opencode run --help` against opencode_cmd in bin/forge")
    return None


def _grok_limit(raw):
    """Grok, failed run: not signed in (AUTH_PREFIX) or a quota/rate limit."""
    tail_ = raw[-4000:]
    if GROK_AUTH_RE.search(tail_):
        return f"{AUTH_PREFIX}grok not signed in / key rejected; run `grok login` (or set XAI_API_KEY), then rerun"
    if GROK_LIMIT_RE.search(tail_):
        return "Grok usage/rate limit"
    return None
