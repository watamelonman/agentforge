"""Choosing vendors: the worker for an attempt and the cross reviewer for finished work."""
from __future__ import annotations

import threading

from .limits import available
from .vendors import family_of, harness_of, vendor_names

WAIT = "(wait)"               # pick_reviewer: a reviewer is needed but every candidate is cooling down
ROUND_LOCK = threading.Lock() # guards pick_worker's round-robin cursor (called from worker threads)


def other(vendor):
    """Legacy two-vendor fallback partner: claude<->codex, everything else -> codex."""
    return "claude" if vendor == "codex" else "codex"


def review_pool(proj):
    """Vendors cross review may pick from: [agents] review_pool, else [agents] workers."""
    return list(proj.c("agents", "review_pool", default=None) or proj.c("agents", "workers", default=["claude"]))


def review_candidates(proj, author):
    """Cross-review candidates for `author`'s work, best first (never the author itself).

    Ranked by distance from the author, keeping review_pool order inside each rank:
    1. other model family AND other CLI   (codex reviews claude; claude reviews oc-kimi)
    2. other family, same CLI             (glm reviews claude; oc-glm reviews oc-kimi)
    3. same family, other CLI             (oc-glm reviews glm)
    4. same family, same CLI
    If the pool has nothing but the author: the legacy partner other(author), so old configs
    such as workers = ["claude"] still get codex as reviewer."""
    names = vendor_names(proj)
    pool = [v for v in dict.fromkeys(review_pool(proj)) if v in names and v != author]
    fam, har = family_of(proj, author), harness_of(proj, author)
    ranked = sorted(pool, key=lambda v: (family_of(proj, v) == fam, harness_of(proj, v) == har))
    if not ranked and other(author) != author:
        ranked = [other(author)]
    return ranked


def cross_reviewer(proj, author):
    """First available review candidate; WAIT when all of them are cooling down right now."""
    ranked = review_candidates(proj, author)
    for v in ranked:
        if available(proj, v):
            return v
    # [agents] self_review_fallback: when every other reviewer is cooling down, let the
    # author's own vendor review rather than leave finished work waiting.
    if proj.c("agents", "self_review_fallback", default=False) and author in vendor_names(proj) \
            and available(proj, author):
        return author
    return WAIT if ranked else other(author)


def pick_worker(proj, card, attempt, counter=[0], advance=True):
    """Choose the worker vendor for an attempt, or None when no suitable vendor is free now.

    Pinned card agent wins; otherwise round-robin over the available vendors in [agents]
    workers (the mutable default `counter` is a deliberate process-wide cursor, guarded by
    ROUND_LOCK; advance=False peeks without moving it). From attempt 3, if swap_on_retry,
    rotate to another available vendor in workers: a fresh model often unsticks a task the
    first one loops on. Cooling-down or disabled vendors are skipped."""
    workers = proj.c("agents", "workers", default=["claude"])
    avail = [v for v in workers if available(proj, v)]
    if not avail and card["agent"] not in vendor_names(proj):
        # [agents] fallback_workers: used only when every vendor in workers is cooling down
        # (e.g. Claude writes only when Codex and the OpenCode pool are both out).
        fb = proj.c("agents", "fallback_workers", default=[]) or []
        avail = [v for v in fb if v in vendor_names(proj) and available(proj, v)]
    if card["agent"] in vendor_names(proj):
        w = card["agent"]
    elif not avail:
        return None
    else:
        with ROUND_LOCK:
            w = avail[counter[0] % len(avail)]
            if advance:
                counter[0] += 1
    # After two failed attempts, rotate to a different vendor in workers (fresh eyes):
    # attempt 3 -> first other vendor, attempt 4 -> next, ... (two vendors = plain swap).
    if attempt >= 3 and proj.c("agents", "swap_on_retry", default=True) and len(workers) > 1:
        alts = [v for v in avail if v != w]
        if alts:
            w = alts[(attempt - 3) % len(alts)]
    return w if available(proj, w) else None


def pick_reviewer(proj, worker):
    """Reviewer vendor for a worker per [agents] reviewer: a vendor name, None when review is
    disabled, or WAIT when the reviewer(s) it may use are all cooling down."""
    r = proj.c("agents", "reviewer", default="cross")
    if r == "none":
        return None
    if r == "cross":
        return cross_reviewer(proj, worker)
    return r if available(proj, r) else WAIT
