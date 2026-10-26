"""Usage limits: per-vendor cooldowns, setup-problem disables and monthly allowance windows.

A limit pauses one vendor, not the run (docs/LIMITS.md). The containers below are module
globals on purpose: every worker thread of one `forge run` shares them, and they are
mirrored into state.json so the next run knows them too.
"""
from __future__ import annotations

import threading
import time

from .pools import pool_until
from .util import fmt_time, now
from .vendors import agent_cfg, vendor_names

DEFAULT_COOLDOWN_MIN = 60     # when the CLI's message gives no reset time
MAX_COOLDOWN_DAYS = 8         # parsed reset times further out than this are treated as garbage
COOL_LOCK = threading.Lock()  # guards COOLDOWNS, DISABLED, SPEND
COOLDOWNS = {}                # vendor -> {"until": epoch, "why": str}; mirrored in state.json "cooldowns"
DISABLED = {}                 # vendor -> reason: login/key/config problems, this process only
SPEND = {}                    # vendor -> [[epoch, usd], ...] for 31 days; mirrored in state.json "spend_log"
# OpenCode Go splits each model's monthly allowance into windows: at most 20% in any 5 hours,
# 50% in any 7 days, 100% in 30 days. Used only for vendors with `monthly_usd` set.
ALLOWANCE_WINDOWS = ((5 * 3600, 0.20), (7 * 86400, 0.50), (30 * 86400, 1.00))


# A usage limit pauses one vendor until its reset time; the run carries on with the others.
# Cooldowns live in memory (COOLDOWNS) for speed and in state.json so the next `forge run`
# knows them too. Login/key problems disable a vendor for the rest of this process only,
# because they end when you fix them, not at a reset time. See docs/LIMITS.md.
def load_limits(proj):
    """Load persisted cooldowns and the spend log from state.json (start of a run)."""
    st = proj.load_state()
    with COOL_LOCK:
        COOLDOWNS.clear()
        COOLDOWNS.update({v: c for v, c in (st.get("cooldowns") or {}).items()
                          if float(c.get("until", 0)) > time.time()})
        SPEND.clear()
        SPEND.update(st.get("spend_log") or {})


def default_cooldown_min(proj, vendor):
    """Cooldown when the limit message names no reset time: per vendor, else [budget], else 60."""
    v = agent_cfg(proj, vendor).get("cooldown_min")
    return float(v if v is not None else proj.c("budget", "limit_cooldown_min", default=DEFAULT_COOLDOWN_MIN))


def set_cooldown(proj, vendor, until, why):
    """Pause `vendor` until epoch `until` (in memory and in state.json) and log it."""
    entry = {"until": until, "why": why, "set": now()}
    with COOL_LOCK:
        COOLDOWNS[vendor] = entry
    proj.update_state(lambda s: s.setdefault("cooldowns", {}).__setitem__(vendor, entry))
    proj.event(f"{vendor}: cooling down until {fmt_time(until)} ({why}); other vendors keep working")


def disable_vendor(proj, vendor, why):
    """Take `vendor` out of this process (bad key, not logged in, missing sandbox, ...)."""
    with COOL_LOCK:
        DISABLED[vendor] = why
    proj.event(f"{vendor}: SETUP PROBLEM ({why}) - not used again in this run; fix it, then rerun")


def allowance_until(proj, vendor, at=None):
    """For a vendor with `monthly_usd`, the epoch when its recorded spend is back under every
    allowance window (ALLOWANCE_WINDOWS x allowance_margin); 0 when it is under them now.
    Caller holds COOL_LOCK. Spend is the CLI's own cost report per run."""
    a = agent_cfg(proj, vendor)
    cap = float(a.get("monthly_usd") or 0)
    if cap <= 0:
        return 0
    margin = float(a.get("allowance_margin", 0.9))
    at = at or time.time()
    until = 0
    for span, share in ALLOWANCE_WINDOWS:
        limit = cap * share * margin
        inside = sorted((t, c) for t, c in SPEND.get(vendor, []) if t > at - span)
        total = sum(c for _, c in inside)
        for t, c in inside:          # the window frees up as its oldest runs age out
            if total < limit:
                break
            total -= c
            until = max(until, t + span)
    return until


def allowance_use(proj, vendor):
    """[(window label, spent usd, window limit usd)] for `forge limits`; [] without monthly_usd."""
    a = agent_cfg(proj, vendor)
    cap = float(a.get("monthly_usd") or 0)
    if cap <= 0:
        return []
    out = []
    with COOL_LOCK:
        for (span, share), label in zip(ALLOWANCE_WINDOWS, ("5h", "7d", "30d")):
            spent = sum(c for t, c in SPEND.get(vendor, []) if t > time.time() - span)
            out.append((label, spent, cap * share))
    return out


def cooldown_until(proj, vendor):
    """Epoch until which `vendor` must not start (hard limit or allowance window); 0 = free now."""
    with COOL_LOCK:
        c = COOLDOWNS.get(vendor)
        hard = float(c["until"]) if c else 0
        soft = allowance_until(proj, vendor)
    t = max(hard, soft, pool_until(proj, vendor))
    return t if t > time.time() else 0


def available(proj, vendor):
    """True when `vendor` may start a run now: not disabled and not cooling down."""
    with COOL_LOCK:
        if vendor in DISABLED:
            return False
    return cooldown_until(proj, vendor) == 0


def record_spend(vendor, cost, at=None):
    """Remember one run's reported cost (memory only; run_agent persists it in state.json)."""
    if cost <= 0:
        return
    at = at or time.time()
    with COOL_LOCK:
        SPEND[vendor] = [e for e in SPEND.get(vendor, []) if e[0] > at - 31 * 86400] + [[at, round(cost, 6)]]


def next_wakeup(proj):
    """Earliest future epoch at which some cooling vendor becomes free again, else None.

    `forge run --wait` sleeps until this time. Example: claude cools down until 14:00 and an
    OpenCode pool until 12:30, codex is free -> 12:30 (codex counts as 0 and is ignored);
    with nobody cooling down -> None."""
    ts = [cooldown_until(proj, v) for v in vendor_names(proj)]
    ts = [t for t in ts if t]
    return min(ts) if ts else None
