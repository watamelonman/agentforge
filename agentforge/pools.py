"""Shared plan-wide pools: one flock'd JSONL spend/cooldown ledger per pool, machine-wide."""
from __future__ import annotations

import fcntl
import json
import os
import re
import time
from pathlib import Path

from .util import die, fmt_time
from .vendors import agent_cfg

# ------------------------------------------------------------- shared pools
# A pool is one paid plan shared by several vendors and by every forge project on this machine
# (OpenCode Go: one plan-wide allowance for all its models). Spend and plan-level cooldowns go
# into one append-only JSONL ledger per pool under POOL_DIR, guarded by flock, so a run in one
# repo sees what runs in the others spent. Per-vendor monthly_usd still applies on top.
POOL_DIR = Path(os.environ.get("FORGE_POOL_DIR") or
                Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
                / "agentforge" / "pools")
POOL_WINDOWS = (("usd_5h", "5h", 5 * 3600), ("usd_7d", "7d", 7 * 86400), ("usd_30d", "30d", 30 * 86400))
# Provider wording for "the whole plan is out" (not just this model). OpenCode Go 2026-10-21:
# "Go usage limit exceeded". Override per pool with pools.<name>.plan_limit_re.
POOL_LIMIT_RE = r"\bGo usage limit\b|plan[- ]wide (?:usage )?limit"
# A 429 / rate limit from any pooled vendor also cools the whole pool: on a shared plan one
# model's 429 usually means the account is throttled, and retrying siblings just burns allowance.
POOL_RATE_RE = re.compile(r"\b429\b|rate[- ]limit|too many requests|usage/rate limit", re.I)
POOL_CACHE = {}   # pool -> ((mtime_ns, size), entries); the ledger only grows, so size changes


def pool_of(proj, vendor):
    """Name of the shared pool `vendor` draws from ([agents.<vendor>] pool), else None."""
    p = agent_cfg(proj, vendor).get("pool")
    return str(p) if p else None



def pool_path(pool):
    if not re.fullmatch(r"[A-Za-z0-9._-]+", pool):
        die(f"bad pool name {pool!r} (letters, digits, . _ - only)")
    return POOL_DIR / f"{pool}.jsonl"


def pool_append(pool, entry):
    """Append one ledger entry under an exclusive flock (safe across processes and repos)."""
    path = pool_path(pool)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(dict(entry, t=round(float(entry.get("t") or time.time()), 3)), sort_keys=True) + "\n"
    with open(path, "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            fh.write(line)
            fh.flush()
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def pool_entries(pool):
    """All ledger entries (dicts with a numeric "t"); torn or foreign lines are skipped."""
    path = pool_path(pool)
    try:
        st = path.stat()
    except FileNotFoundError:
        return []
    key = (st.st_mtime_ns, st.st_size)
    hit = POOL_CACHE.get(pool)
    if hit and hit[0] == key:
        return hit[1]
    with open(path) as fh:
        fcntl.flock(fh, fcntl.LOCK_SH)
        try:
            text = fh.read()
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
    out = []
    for line in text.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and isinstance(e.get("t"), (int, float)):
            out.append(e)
    POOL_CACHE[pool] = (key, out)
    return out


def pool_caps(proj, pool):
    """[(key, label, span secs, cap usd)] from [pools.<pool>]; a cap of 0/unset is off."""
    cfg = proj.c("pools", pool, default={}) or {}
    return [(k, lbl, span, float(cfg.get(k) or 0)) for k, lbl, span in POOL_WINDOWS]


def pool_spend(pool):
    return sorted((float(e["t"]), float(e.get("usd") or 0)) for e in pool_entries(pool)
                  if e.get("kind") == "spend")


def pool_until(proj, vendor, at=None):
    """Epoch until which `vendor`'s pool blocks it (plan-level cooldown from any project, or a
    pools.<name>.usd_* window at its cap); 0 when free or not pooled."""
    pool = pool_of(proj, vendor)
    if not pool:
        return 0
    at = at or time.time()
    entries = pool_entries(pool)
    cleared = max((e["t"] for e in entries if e.get("kind") == "clear"), default=0)
    until = max((float(e.get("until") or 0) for e in entries
                 if e.get("kind") == "cooldown" and e["t"] > cleared), default=0)
    spend = pool_spend(pool)
    for _k, _lbl, span, cap in pool_caps(proj, pool):
        if cap <= 0:
            continue
        inside = [(t, c) for t, c in spend if t > at - span]
        total = sum(c for _, c in inside)
        for t, c in inside:          # the window frees up as its oldest runs age out
            if total < cap:
                break
            total -= c
            until = max(until, t + span)
    return until if until > at else 0


def pool_use(proj, pool):
    """[(label, spent usd, cap usd)] for `forge limits`."""
    spend, now_ = pool_spend(pool), time.time()
    return [(lbl, sum(c for t, c in spend if t > now_ - span), cap)
            for _k, lbl, span, cap in pool_caps(proj, pool) if cap > 0]


def record_pool_spend(proj, vendor, cost):
    """Add one run's reported cost to the vendor's pool ledger (no-op when not pooled)."""
    pool = pool_of(proj, vendor)
    if pool and cost > 0:
        pool_append(pool, {"kind": "spend", "usd": round(cost, 6), "vendor": vendor,
                           "project": str(proj.root)})


def is_plan_limit(proj, vendor, text):
    """True when a limit message means the whole pool's plan is out."""
    pool = pool_of(proj, vendor)
    if not pool:
        return False
    pat = proj.c("pools", pool, "plan_limit_re", default=None) or POOL_LIMIT_RE
    return bool(re.search(pat, text or "", re.I))


def pool_wide_limit(proj, vendor, why, raw=""):
    """True when a pooled vendor's limit should pause its whole pool: the plan-level message
    (plan_limit_re) or any 429 / rate limit."""
    if not pool_of(proj, vendor):
        return False
    return bool(is_plan_limit(proj, vendor, why) or is_plan_limit(proj, vendor, (raw or "")[-8000:])
                or POOL_RATE_RE.search(why or ""))


def set_pool_cooldown(proj, vendor, until, why):
    """Pause every vendor in `vendor`'s pool, in every project sharing the ledger."""
    pool = pool_of(proj, vendor)
    pool_append(pool, {"kind": "cooldown", "until": round(until, 3), "why": why, "vendor": vendor,
                       "project": str(proj.root)})
    proj.event(f"pool {pool}: plan-wide limit ({why}); every vendor in the pool pauses until "
               f"{fmt_time(until)} in every project")

