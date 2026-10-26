"""When does a usage limit lift? Parse reset times out of CLI output (docs/LIMITS.md)."""
from __future__ import annotations

import datetime
import re
import time

from .limits import MAX_COOLDOWN_DAYS
from .parsers.claude import overage_in_use, rate_limit_events

# One "<number><unit>" piece of a duration.
#   "2 hours" -> ("2", "hours")   "1h30m" -> ("1", "h"), ("30", "m")   "1.5 days" -> ("1.5", "days")
# The unit must not run into more letters, so "5 hoursly" and "3 mo" don't match; digits may
# follow ("1h30m").
DURATION_RE = re.compile(r"""
    (\d+(?:\.\d+)?)                 # amount: 2, 30, 1.5
    \s*
    (days?|d|hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)   # unit, long or short
    (?![a-z])                       # ...not the start of a longer word
""", re.I | re.X)

# "Try again in 2 hours 13 minutes." / "retry after 45s" / "resets in 1h30m": group 1 is the
# duration text ("2 hours 13 minutes."-> "2 hours 13 minutes"), to be fed to duration_secs().
RESET_IN_RE = re.compile(r"""
    (?:try\ again|retry|resets?|available\ again)   # the verb
    \s+ (?:in|after) \s+
    (                                               # group 1: up to four "<n><unit>" pieces
      (?:\d+(?:\.\d+)?\s*[a-z]+                     #   "2 hours", "13minutes"
         [\s,]* (?:and\s+)?                         #   separated by spaces, commas or "and"
      ){1,4}
    )
""", re.I | re.X)

# "limit reached; resets at 2026-10-21T18:00:00Z" / "try again at 2026-10-21 18:00+02:00":
# group 1 is an ISO time. A zone (Z or +hh:mm) is required: forge can't guess whose clock a
# zoneless time means, so "reset at 2026-10-21 18:00:00" does not match.
RESET_AT_RE = re.compile(r"""
    (?:resets?|reset\ at|try\ again\ at|available\ again\ at)
    \D{0,20}                        # filler without digits ("s at ", ": ")
    (                               # group 1: the timestamp
      \d{4}-\d{2}-\d{2} [\ T] \d{2}:\d{2}   # 2026-10-21T18:00 (or with a space)
      (?::\d{2})? (?:\.\d+)?        # optional seconds and fraction
      (?:Z|[+-]\d{2}:?\d{2})        # required zone: Z, +02:00, -0500
    )
""", re.I | re.X)


def duration_secs(text):
    """Seconds in a human duration; 0 if nothing parses.

    >>> duration_secs("2 hours 13 minutes")
    7980.0
    >>> duration_secs("1h30m"), duration_secs("45s"), duration_secs("1.5 days")
    (5400.0, 45.0, 129600.0)
    >>> duration_secs("soon")
    0.0

    "m"/"min"/"minutes" are minutes; months are not a unit."""
    unit = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    total = 0.0
    for n, u in DURATION_RE.findall(text):
        u = u.lower()
        key = "m" if u.startswith("min") or u == "m" else u[0]
        total += float(n) * unit[key]
    return total


def parse_when(value):
    """Epoch from an epoch number (s or ms) or a timezone-aware ISO time; None otherwise.
    Times without a zone are ignored on purpose: forge can't know whose clock they mean."""
    if isinstance(value, (int, float)) and value > 0:
        return value / 1000 if value > 1e12 else float(value)
    if isinstance(value, str):
        try:
            d = datetime.datetime.fromisoformat(value.strip().replace("Z", "+00:00").replace(" ", "T"))
        except ValueError:
            return None
        return d.timestamp() if d.tzinfo else None
    return None


def limit_reset_time(raw):
    """Best guess of when a usage limit lifts (epoch), or None.

    Sources: Claude Code rate_limit_event `resetsAt` (preferring rejected/overage events over
    plain status events), then "try again in 2h13m" / "resets at <ISO time with zone>" text
    in the last 4000 chars of the log. Only future times within MAX_COOLDOWN_DAYS count."""
    strong, weak = [], []
    for info in rate_limit_events(raw):
        bucket = strong if info.get("status") == "rejected" or overage_in_use(info) else weak
        for k in ("resetsAt", "resets_at", "resetAt", "reset_at"):
            t = parse_when(info.get(k))
            if t:
                bucket.append(t)
    tail_ = raw[-4000:]
    for m in RESET_IN_RE.finditer(tail_):
        secs = duration_secs(m.group(1))
        if secs:
            strong.append(time.time() + secs)
    for m in RESET_AT_RE.finditer(tail_):
        t = parse_when(m.group(1))
        if t:
            strong.append(t)
    horizon = time.time() + MAX_COOLDOWN_DAYS * 86400
    for bucket in (strong, weak):
        ok = [t for t in bucket if time.time() < t < horizon]
        if ok:
            return max(ok)
    return None
