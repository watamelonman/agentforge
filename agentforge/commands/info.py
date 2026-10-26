"""Read-mostly commands: status, limits, gates, and `up` (tmux launcher)."""
from __future__ import annotations

import os
import shlex
import sys
import time

from ..cards import load_cards
from ..gates import run_gates
from ..limits import COOLDOWNS, allowance_use, cooldown_until, load_limits
from ..pools import pool_append, pool_of, pool_path, pool_until, pool_use
from ..util import FORGE_SCRIPT, die, fmt_time, sh
from ..vendors import family_of, harness_of, used_vendors, vendor_names

def cmd_status(proj, args):
    """`forge status`: task table, status counts, run count and estimated spend."""
    cards = load_cards(proj)
    st = proj.load_state()
    rows = []
    for tid, c in cards.items():
        t = st["tasks"].get(tid, {})
        last = (t.get("history") or [{}])[-1].get("msg", "")
        rows.append((tid, f"M{c['milestone']}", t.get("status", "todo"), t.get("agent", c["agent"]),
                     str(t.get("attempts", 0)), c["title"][:38], last[:30]))
    hdr = ("TASK", "MS", "STATUS", "AGENT", "TRY", "TITLE", "LAST")
    w = [max(len(r[i]) for r in rows + [hdr]) for i in range(len(hdr))]
    for r in [hdr] + rows:
        print("  ".join(x.ljust(w[i]) for i, x in enumerate(r)))
    counts = {}
    for r in rows:
        counts[r[2]] = counts.get(r[2], 0) + 1
    print(f"\n{counts}  agent runs: {st.get('agent_runs', 0)}  est. Claude spend: ${st.get('total_usd', 0):.2f}")
    if st.get("vendor_runs"):
        print("runs by vendor: " + ", ".join(f"{k} {v}" for k, v in sorted(st["vendor_runs"].items())))
    if "grok_usd_reported" in st:
        print(f"grok reported cost: ${st['grok_usd_reported']:.2f} (xAI's figure when it sends one; not in the budget)")
    if "glm_usd_nominal" in st:
        print(f"glm nominal cost: ${st['glm_usd_nominal']:.2f} (Claude Code's Anthropic-price estimate; "
              "not what the Z.ai plan charges, not counted in the budget)")
    if st.get("vendor_usd"):
        print("opencode reported cost: " + ", ".join(f"{k} ${v:.2f}" for k, v in sorted(st["vendor_usd"].items()))
              + " (API-price figures; not in the budget)")
    for v, c in sorted((st.get("cooldowns") or {}).items()):
        if float(c.get("until", 0)) > time.time():
            print(f"{v} cooling down until {fmt_time(float(c['until']))}: {c.get('why', '')}  (`forge limits`)")


def cmd_limits(proj, args):
    """`forge limits`: per-vendor state (free / cooling until / disabled), allowance use for
    vendors with monthly_usd, and --clear to lift cooldowns early (spend history is kept)."""
    if args.clear is not None:
        _clear_cooldowns(proj, set(args.clear))
    load_limits(proj)
    st = proj.load_state()
    rows = [("VENDOR", "HARNESS", "FAMILY", "STATE", "ALLOWANCE (spent/limit)")]
    for v in dict.fromkeys(used_vendors(proj) + list((st.get("cooldowns") or {}).keys())):
        if v not in vendor_names(proj):
            continue
        use = "  ".join(f"{lbl} ${s:.2f}/${lim:.2f}" for lbl, s, lim in allowance_use(proj, v)) or "-"
        rows.append((v, harness_of(proj, v) or "?", family_of(proj, v), _vendor_state(proj, v), use))
    w = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        print("  ".join(x.ljust(w[i]) for i, x in enumerate(r)).rstrip())
    _print_pools(proj)


def _clear_cooldowns(proj, targets):
    """--clear [VENDOR...]: drop cooldowns from state.json and the shared pool ledgers."""
    unknown = targets - set(vendor_names(proj))
    if unknown:
        die(f"unknown vendor(s): {', '.join(sorted(unknown))}")

    def f(s):
        cd = s.get("cooldowns") or {}
        for v in list(cd):
            if not targets or v in targets:
                del cd[v]
    proj.update_state(f)
    pools = {pool_of(proj, v) for v in (targets or vendor_names(proj))} - {None}
    for pool in sorted(pools):     # a plan-level cooldown is shared; clearing it clears it everywhere
        pool_append(pool, {"kind": "clear", "project": str(proj.root)})
    print("cooldowns cleared: " + (", ".join(sorted(targets)) if targets else "all")
          + (f" (pools: {', '.join(sorted(pools))})" if pools else ""))


def _vendor_state(proj, v):
    """'free' or 'cooling until <time> (<why> | pool <name> | allowance window)'."""
    t = cooldown_until(proj, v)
    if not t:
        return "free"
    c = COOLDOWNS.get(v)
    pt = pool_until(proj, v)
    if c and float(c["until"]) >= t:
        why = f" ({c['why'][:50]})"
    elif pt and pt >= t:
        why = f" (pool {pool_of(proj, v)})"
    else:
        why = " (allowance window)"
    return f"cooling until {fmt_time(t)}" + why


def _print_pools(proj):
    pools = {}
    for v in used_vendors(proj):
        if pool_of(proj, v):
            pools.setdefault(pool_of(proj, v), []).append(v)
    for pool, members in sorted(pools.items()):
        use = "  ".join(f"{lbl} ${s:.2f}/${lim:.2f}" for lbl, s, lim in pool_use(proj, pool)) or "no caps set"
        pt = pool_until(proj, members[0])
        print(f"pool {pool} ({', '.join(members)}): {use}; "
              + (f"cooling until {fmt_time(pt)}" if pt else "free") + f"  [{pool_path(pool)}]")


def cmd_up(proj, args):
    """tmux layout: orchestrator | status | event log."""
    sess = f"forge-{proj.root.name}"
    me = shlex.quote(str(FORGE_SCRIPT))   # bin/forge itself, even when reached through a symlink
    root = shlex.quote(str(proj.root))
    mock = "FORGE_MOCK=1 " if proj.mock else ""
    wait = " --wait" if args.wait else ""
    run = f"{mock}{me} -C {root} run --parallel {args.parallel}{wait}; echo '[run finished - press enter]'; read"
    status = f"watch -n 5 -t {me} -C {root} status"
    events = f"touch {root}/.forge/logs/events.log; tail -n 50 -F {root}/.forge/logs/events.log"
    if sh(["tmux", "has-session", "-t", sess], check=False).returncode == 0:
        die(f"tmux session {sess} exists; attach with `tmux attach -t {sess}`")
    sh(["tmux", "new-session", "-d", "-s", sess, "-n", "forge", "-c", str(proj.root), run])
    sh(["tmux", "split-window", "-h", "-t", f"{sess}:forge", "-c", str(proj.root), status])
    sh(["tmux", "split-window", "-v", "-t", f"{sess}:forge.1", "-c", str(proj.root), events])
    sh(["tmux", "new-window", "-t", sess, "-n", "shell", "-c", str(proj.root)])
    sh(["tmux", "select-window", "-t", f"{sess}:forge"])
    print(f"started tmux session {sess}")
    if not args.detach and sys.stdout.isatty():
        os.execvp("tmux", ["tmux", "attach", "-t", sess])


def cmd_gates(proj, args):
    """Run gates on the main checkout against a base ref (for CI / humans)."""
    fake = {"id": "manual", "owns": ["**"], "docs": [], "tests_required": False, "may_edit_tests": True}
    ok, rep = run_gates(proj, proj.root, args.base, fake)
    print(rep)
    sys.exit(0 if ok else 1)

