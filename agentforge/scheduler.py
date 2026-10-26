"""`forge run`: pick ready cards and run them on a thread pool until nothing is runnable."""
from __future__ import annotations

import concurrent.futures as cf
import signal
import time

from .cards import load_cards
from .choice import WAIT, pick_reviewer, pick_worker
from .commands.agents import cmd_audit
from .commands.info import cmd_status
from .limits import cooldown_until, load_limits, next_wakeup
from .project import STOP
from .task import run_task
from .util import die, fmt_time, git
from .vendors import vendor_names

REAP_POLL_SECS = 5   # how often finished tasks are collected and new ones started

# Files the planner rewrites; a pending edit to them must not block `forge run`/`forge up`.
DIRTY_OK = {"docs/SPEC_ISSUES.md"}


def can_start(proj, card, t):
    """True when a vendor this card needs next is free: a reviewer for a card parked with
    pending_review, otherwise a worker for its next attempt (pinned agent or the pool)."""
    if t.get("pending_review"):
        return pick_reviewer(proj, t.get("agent") or "claude") != WAIT
    return pick_worker(proj, card, t.get("attempts", 0) + 1, advance=False) is not None


def ready_tasks(proj, cards, running, waiting=None):
    """Cards that can start now: deps done, lowest open milestone (if strict), owns globs not
    overlapping any running or already-selected card, and a free vendor (can_start).
    Cards held back only by a missing vendor are appended to `waiting` when given."""
    st = proj.load_state()["tasks"]
    status = lambda t: st.get(t, {}).get("status", "todo")
    pending = [c for c in cards.values() if status(c["id"]) not in ("done", "blocked") and c["id"] not in running]
    if proj.c("project", "strict_milestones", default=True):
        open_ms = [c["milestone"] for c in cards.values() if status(c["id"]) != "done"]
        if open_ms:
            pending = [c for c in pending if c["milestone"] == min(open_ms)]
    busy = [g for r in running for g in cards[r]["owns"]]
    out = []
    for c in sorted(pending, key=lambda c: (c["milestone"], c["id"])):
        if all(status(d) == "done" for d in c["deps"]) and not overlaps(c["owns"], busy):
            if not can_start(proj, c, st.get(c["id"], {})):
                if waiting is not None:
                    waiting.append(c)
                continue
            out.append(c)
            busy += c["owns"]
    return out


def overlaps(a, b):
    """Conservative: same glob, or one glob's literal prefix contains the other."""
    for x in a:
        for y in b:
            px, py = x.split("*")[0], y.split("*")[0]
            if x == y or px.startswith(py) or py.startswith(px):
                return True
    return False


def cmd_run(proj, args):
    """`forge run`: pre-flight checks, then a thread-pool scheduler until nothing is runnable.

    When the only thing left is cards waiting for cooling vendors, it stops with a message,
    or with --wait sleeps until the next vendor frees up and carries on."""
    _preflight(proj)
    cards = _selected_cards(proj, args)
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    load_limits(proj)
    proj.event(f"run: {len(cards)} cards, parallel={args.parallel}, mock={proj.mock}")
    for v in vendor_names(proj):
        t = cooldown_until(proj, v)
        if t:
            proj.event(f"run: {v} is cooling down until {fmt_time(t)}; cards fall back to other vendors")
    with cf.ThreadPoolExecutor(max_workers=args.parallel) as ex:
        _schedule(proj, args, cards, ex)
    cmd_status(proj, args)
    st = proj.load_state()["tasks"]
    if proj.c("agents", "auditor") and any(st.get(c, {}).get("status") == "done" for c in cards) and args.audit:
        cmd_audit(proj, args)


def _preflight(proj):
    """Refuse to run on a dirty main checkout or on another branch."""
    dirty = [l for l in git(proj.root, "status", "--porcelain", "--untracked-files=no").splitlines()
             if l.split(maxsplit=1)[-1] not in DIRTY_OK]
    if dirty:
        die(f"main checkout has uncommitted changes; commit or stash them first:\n" + "\n".join(dirty))
    if git(proj.root, "rev-parse", "--abbrev-ref", "HEAD") != proj.main:
        die(f"main checkout must be on branch {proj.main}")


def _selected_cards(proj, args):
    cards = load_cards(proj)
    if args.task:
        cards = {k: v for k, v in cards.items() if k in args.task}
    if not cards:
        die("no task cards in tasks/ (run `forge plan` first)")
    return cards


def _schedule(proj, args, cards, ex):
    """Keep up to --parallel cards running; return when nothing more can start."""
    running = {}
    while not STOP.is_set():
        waiting = []
        for c in ready_tasks(proj, cards, running, waiting)[: args.parallel - len(running)]:
            running[c["id"]] = ex.submit(run_task, proj, c)
        if running:
            _reap(proj, running)
            continue
        if waiting and _wait_for_vendor(proj, args, waiting):
            continue
        return


def _wait_for_vendor(proj, args, waiting):
    """Only cards that wait for a vendor are left. With --wait sleep until the next vendor is
    free and return True; otherwise log why the run stops and return False."""
    wake = next_wakeup(proj)
    ids = ", ".join(c["id"] for c in waiting)
    if wake and getattr(args, "wait", False):
        proj.event(f"run: {ids} wait for a vendor; sleeping until {fmt_time(wake)} (--wait)")
        while time.time() < wake + 1 and not STOP.is_set():
            time.sleep(min(5.0, max(0.2, wake + 1 - time.time())))
        return True
    proj.event(f"run: {ids} wait for a vendor that is cooling down or unavailable; "
               + (f"next one is free at {fmt_time(wake)} - rerun then, or use `forge run --wait`"
                  if wake else "fix the setup problem logged above, then rerun"))
    return False


def _reap(proj, running):
    """Wait briefly for running tasks; drop finished ones (an exception blocks only its card)."""
    done, _ = cf.wait(running.values(), return_when=cf.FIRST_COMPLETED, timeout=REAP_POLL_SECS)
    for tid, fut in list(running.items()):
        if fut not in done:
            continue
        try:
            fut.result()
        except Exception as e:  # never let one task kill the run
            proj.event(f"{tid}: orchestrator error {e!r}")
            proj.set_task(tid, status="blocked", event={"msg": f"error {e!r}"})
        del running[tid]
