"""Commands that run one agent or one card directly: plan, review, audit, regate, reset."""
from __future__ import annotations

import json
import time

from ..cards import load_cards, write_card
from ..context import build_context, with_context
from ..gates import run_gates
from ..limits import load_limits
from ..runner import run_agent
from ..task import run_task
from ..util import die, git, now, render, sh
from ..vendors import check_vendor

def cmd_plan(proj, args):
    """`forge plan`: planner agent (read-only) -> new task cards + docs/SPEC_ISSUES.md."""
    vendor = check_vendor(proj, args.agent or proj.c("agents", "planner", default="claude"))
    cards = load_cards(proj)
    existing = "\n".join(f"- {c['id']} (M{c['milestone']}): {c['title']}" for c in cards.values()) or "none"
    prompt = render(proj.prompt("planner"), SPEC=args.spec or proj.c("project", "spec", default="spec/SPEC.md"),
                    MILESTONE=args.milestone or "the first milestone that has no task cards yet",
                    EXISTING=existing)
    res = run_agent(proj, vendor, "plan", prompt, proj.root, "plan", schema="plan")
    if not res.data or "tasks" not in res.data:
        die(f"planner returned no valid plan; see {res.log}")
    new = 0
    for t in res.data["tasks"]:
        if t["id"] in cards:
            continue
        write_card(proj, t)
        new += 1
    issues = res.data.get("spec_issues", [])
    # Always overwrite, so the file reflects only the latest plan run and never goes stale.
    (proj.root / "docs").mkdir(exist_ok=True)
    (proj.root / "docs" / "SPEC_ISSUES.md").write_text(
        f"# Spec issues found by planner ({now()})\n\n"
        + ("\n".join(f"- {i}" for i in issues) if issues else "No issues.") + "\n")
    print(f"wrote {new} task cards to tasks/; {len(issues)} spec issues -> docs/SPEC_ISSUES.md")
    print("Review/edit the cards, `git commit` them, then `forge run` or `forge up`.")


def cmd_review(proj, args):
    """`forge review`: re-run gates and optionally a reviewer on an existing worktree (no merge)."""
    cards = load_cards(proj)
    c = cards.get(args.task) or die(f"no card {args.task}")
    wt = proj.wts / args.task
    if not wt.exists():
        die("no worktree for that task (already merged or never started)")
    base = git(wt, "merge-base", "HEAD", proj.main)
    ok, rep = run_gates(proj, wt, base, c)
    print(rep)
    if args.gates_only:
        return
    vendor = check_vendor(proj, args.agent or "codex")
    rv = run_agent(proj, vendor, "review", render(with_context(proj.prompt("reviewer"), build_context(proj, c, "review")), CARD=c["raw"],
                   DIFF=git(wt, "diff", f"{base}...HEAD"), GATES=rep, TASK_ID=args.task), wt, args.task, schema="review")
    print(json.dumps(rv.data, indent=2) if rv.data else rv.text)


def cmd_audit(proj, args):
    """`forge audit`: whole-repo monitor agent; writes a report and any FIX-* cards."""
    vendor = check_vendor(proj, getattr(args, "agent", None) or proj.c("agents", "auditor", default="codex"))
    log = git(proj.root, "log", "--oneline", "-30")
    prompt = render(proj.prompt("auditor"), GITLOG=log,
                    SPEC=proj.c("project", "spec", default="spec/SPEC.md"))
    res = run_agent(proj, vendor, "audit", prompt, proj.root, "audit", schema="audit")
    d = res.data or {}
    ts = time.strftime("%Y%m%d-%H%M")
    rep = proj.dir / f"audit-{ts}.md"
    rep.write_text(f"# Audit {ts} ({vendor}) verdict={d.get('verdict')}\n\n" + "\n".join(
        f"- [{f.get('severity')}] {f.get('file', '')}: {f.get('issue', '')}" for f in d.get("findings", [])))
    for t in d.get("new_tasks", []):
        write_card(proj, t)
    print(f"audit verdict={d.get('verdict')} findings={len(d.get('findings', []))} "
          f"new fix cards={len(d.get('new_tasks', []))} -> {rep}")


def cmd_reset(proj, args):
    """`forge reset`: back to todo/0 attempts; --hard also drops worktree and branch."""
    for tid in args.task:
        wt = proj.wts / tid
        if wt.exists() and args.hard:
            sh(["git", "-C", str(proj.root), "worktree", "remove", "--force", str(wt)], check=False)
            sh(["git", "-C", str(proj.root), "branch", "-D", f"forge/{tid}"], check=False)
        proj.set_task(tid, status="todo", attempts=0, event={"msg": "reset by human"})
        print(f"reset {tid}")


def cmd_regate(proj, args):
    """`forge regate`: gates + review + merge on the existing forge/<ID> branch, no worker run."""
    cards = load_cards(proj)
    load_limits(proj)   # respect cooldowns from earlier runs when choosing the reviewer
    for tid in args.task:
        c = cards.get(tid) or die(f"no card {tid}")
        branch = f"forge/{tid}"
        if not git(proj.root, "branch", "--list", branch) and not (proj.wts / tid).exists():
            die(f"{tid}: no branch {branch} to re-gate; use `forge run --task {tid}`")
        ok = run_task(proj, c, regate=True, continue_work=args.cont)
        print(f"{tid}: {'merged' if ok else proj.task_state(tid).get('status', 'not merged')}")
