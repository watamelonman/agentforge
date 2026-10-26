"""Claude Code (claude, glm) stream-json output: the result line and rate-limit events."""
from __future__ import annotations

import json

def rate_limit_events(raw):
    """Yield rate_limit_info dicts from Claude Code stream-json `rate_limit_event` lines."""
    for line in raw.splitlines():
        if '"rate_limit' not in line:
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        if isinstance(ev, dict) and ev.get("type") == "rate_limit_event":
            yield ev.get("rate_limit_info") or {}


def api_retry_stop(raw, min_attempt=3):
    """Reason to abort a Claude Code run that is stuck retrying a hopeless request, else None.

    Claude Code retries failed API calls itself (stream-json `system`/`api_retry` events, up
    to 10 times with growing backoff), so a bad key or an exhausted quota can burn minutes
    before the CLI exits. From the min_attempt-th retry: 401/403 -> "auth", 429 -> "limit"."""
    for line in reversed(raw.splitlines()[-200:]):
        if '"api_retry"' not in line:
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        if ev.get("subtype") != "api_retry" or int(ev.get("attempt") or 0) < min_attempt:
            return None
        code = ev.get("error_status")
        if code in (401, 403):
            return "auth"
        if code == 429:
            return "limit"
        return None
    return None


def overage_in_use(info):
    """True when a rate_limit_info says the account is drawing paid overage/extra usage."""
    return bool(info.get("isUsingOverage") or info.get("overageInUse"))


def parse_claude_result(raw):
    """(text, structured data or None, cost, is_error) from the newest `result` line of a
    Claude Code stream-json log; ("", None, 0.0, False) when the run never got that far."""
    for line in reversed(raw.splitlines()):
        try:
            ev = json.loads(line)
        except Exception:
            continue
        if ev.get("type") == "result":
            return (ev.get("result") or "", ev.get("structured_output"),
                    float(ev.get("total_cost_usd") or 0), bool(ev.get("is_error")))
    return "", None, 0.0, False
