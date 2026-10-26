"""One card's lifecycle: work attempts -> gates -> cross review -> serialized merge.

TaskRun keeps the per-card state the old single function kept in locals (attempts,
feedback, last failure, limit handoffs). Each pass of the loop runs the steps below in
order; a step returns None to go on to the next one, RETRY to start the next pass, BLOCK
to give up on the card, or True/False to end run_task with that result.
"""
from __future__ import annotations

import json

from .choice import WAIT, pick_reviewer, pick_worker
from .context import build_context, with_context
from .gates import run_gates
from .gitops import branch_author, commit_all, ensure_worktree, restore_deps, sync_main
from .project import MERGE_LOCK, STOP
from .runner import AgentResult, run_agent
from .util import event_excerpt, git, render, sh
from .vendors import vendor_names

RETRY = "retry"   # start the next pass of the attempt loop
BLOCK = "block"   # leave the loop: the card ends blocked (or parked if the run is stopping)


def run_task(proj, card, regate=False, continue_work=False):
    """Full lifecycle of one card: attempts of work -> gates -> review -> serialized merge.

    regate=True (`forge regate`): the first pass skips the worker and gates/reviews/merges
    the work already on forge/<ID>. If that fails, stop (state gates_failed/review_failed)
    unless continue_work, in which case normal worker attempts follow with the report as
    feedback. Returns True when merged. Every exit path records state; see docs/LIFECYCLE.md.

    Usage limits (docs/LIMITS.md): a worker that hits one hands the card (and its partial work)
    to the next free vendor without charging an attempt; a reviewer that hits one is replaced
    by the next allowed reviewer. When nobody suitable is free, the card is parked as `todo`
    (with `pending_review` if only the review is missing) and resumes when a vendor frees up."""
    return TaskRun(proj, card, regate, continue_work).run()


class TaskRun:
    def __init__(self, proj, card, regate, continue_work):
        self.proj, self.card = proj, card
        self.regate, self.continue_work = regate, continue_work
        self.tid = tid = card["id"]
        self.wt, self.branch = ensure_worktree(proj, tid)
        restore_deps(proj, self.wt, tid)
        self.max_attempts = proj.c("budget", "max_attempts", default=3)
        self.context = build_context(proj, card, "work")   # once per card: identical text on every attempt
        tstate = proj.task_state(tid)
        resume = bool(tstate.get("pending_review")) and not regate
        self.feedback = tstate.get("feedback") or "None - this is the first attempt."
        self.last_fail = None
        self.attempts = tstate.get("attempts", 0)
        proj.set_task(tid, status="running", branch=self.branch,
                      event={"msg": "resumed: review pending" if resume else "started"})
        if regate:
            self.attempts = 0   # a re-gate is a fresh start for the attempt budget
        self.skip_work = regate or resume
        self.resume = resume
        self.hops, self.max_hops = 0, 2 * len(vendor_names(proj))   # limit handoffs; bounded so flapping can't loop
        self.worker = None

    def run(self):
        while (self.attempts < self.max_attempts or self.skip_work) and not STOP.is_set():
            outcome = self._one_pass()
            if outcome == RETRY:
                continue
            if outcome == BLOCK:
                break
            return outcome
        if STOP.is_set() and self.attempts < self.max_attempts:
            return self._park("run stopped")   # budget/run cap/SIGTERM
        self.proj.set_task(self.tid, status="blocked", event={"msg": "attempts exhausted", "last": self.feedback[:2000]})
        self.proj.event(f"{self.tid}: BLOCKED - needs human or `forge reset {self.tid}`")
        return False

    def _park(self, msg, **kw):
        # Back to todo without charging anything; feedback is kept for whoever continues.
        self.proj.set_task(self.tid, status="todo", attempts=self.attempts, feedback=self.feedback,
                           event={"msg": msg}, **kw)
        return False

    def _one_pass(self):
        if self.skip_work:
            res = self._take_existing_branch()
        else:
            res = self._work_attempt()
            if not isinstance(res, AgentResult):
                return res
        first_pass, self.skip_work = self.skip_work, False
        outcome = self._sync_with_main(first_pass)
        if outcome is not None:
            return outcome
        base = git(self.wt, "merge-base", "HEAD", self.proj.main)
        outcome, report = self._gate(res, base, first_pass)
        if outcome is not None:
            return outcome
        outcome = self._review(base, report)
        if outcome is not None:
            return outcome
        return self._merge(base)

    # -------------------------------------------------------------- steps
    def _take_existing_branch(self):
        """Re-gate / resume pass: no worker; judge the existing branch as committed."""
        proj, tid, wt = self.proj, self.tid, self.wt
        self.worker = branch_author(proj, wt) or proj.task_state(tid).get("agent") or pick_worker(proj, self.card, 1)
        proj.set_task(tid, agent=self.worker)
        res = AgentResult(True, "existing branch")
        commit_all(wt, f"{tid}: uncommitted changes picked up by {'regate' if self.regate else 'resume'}")
        proj.event(f"{tid}: {'re-gating' if self.regate else 'resuming review of'} existing branch {self.branch} "
                   f"({git(wt, 'rev-parse', '--short', 'HEAD')})")
        return res

    def _work_attempt(self):
        """One worker attempt. AgentResult when it finished, else a loop outcome."""
        proj, tid = self.proj, self.tid
        if self.regate and not self.continue_work:
            proj.event(f"{tid}: re-gate failed; branch kept. Fix by hand + `forge regate {tid}`, "
                       f"or `forge regate {tid} --continue` to let workers retry.")
            return False
        worker = self.worker = pick_worker(proj, self.card, self.attempts + 1)
        if worker is None:
            proj.event(f"{tid}: no worker vendor is free (cooling down or unavailable) - card waits")
            return self._park("waiting for a free worker vendor")
        self.attempts += 1
        proj.set_task(tid, attempts=self.attempts, agent=worker, status="running", pending_review=False)
        prompt = render(with_context(proj.prompt("worker"), self.context), CARD=self.card["raw"],
                        FEEDBACK=self.feedback, ATTEMPT=self.attempts, MAX_ATTEMPTS=self.max_attempts, TASK_ID=tid)
        res = run_agent(proj, worker, "work", prompt, self.wt, tid)
        if res.limited:
            return self._hand_over(worker)
        commit_all(self.wt, f"{tid}: attempt {self.attempts} by {worker}")
        return res

    def _hand_over(self, worker):
        """The worker hit a usage limit: keep its partial work, charge nothing, try again."""
        self.attempts -= 1   # not the card's fault
        self.hops += 1
        # Keep what the stopped worker wrote; this commit message is not an "attempt N by"
        # line, so branch_author still names the last vendor that finished an attempt.
        if commit_all(self.wt, f"{self.tid}: partial work by {worker} (stopped by usage limit)") \
                and "stopped mid-task" not in self.feedback:
            self.feedback = (f"The previous worker ({worker}) stopped mid-task because of a usage limit. "
                             "Its partial changes are already in your worktree: check them, keep what is "
                             "right, and finish the task.\nEarlier feedback: " + self.feedback)
        self.proj.set_task(self.tid, attempts=self.attempts,
                           event={"msg": f"{worker} unavailable (limit/setup); handing over"})
        if self.hops > self.max_hops:
            return self._park("too many usage-limit handoffs in one go")
        return RETRY

    def _sync_with_main(self, first_pass):
        proj, tid, main = self.proj, self.tid, self.proj.main
        ok, conflicts = sync_main(self.wt, main)
        if ok:
            return None
        self.feedback = (f"Your branch conflicts with {main} in: {conflicts}. {main} has moved; "
                         "re-read those files and redo your change on top of the current code.")
        if first_pass and self.regate:   # never discard existing work during a re-gate
            proj.event(f"{tid}: re-gate: branch conflicts with {main} in {conflicts}; resolve by hand")
            proj.set_task(tid, status="blocked", event={"msg": "regate conflict", "files": conflicts})
            return False
        sh(["git", "-C", str(self.wt), "reset", "-q", "--hard", main], check=False)
        proj.set_task(tid, event={"msg": "merge conflict", "files": conflicts})
        return RETRY

    def _gate(self, res, base, first_pass):
        """(outcome or None, gate report)."""
        proj, tid = self.proj, self.tid
        gok, report = run_gates(proj, self.wt, base, self.card)
        if not res.ok and not res.text:
            report = f"Agent exited rc={res.rc} without finishing.\n" + report
        if gok:
            return None, report
        proj.event(f"{tid}: gates FAILED\n" + event_excerpt(report))
        proj.set_task(tid, status="gates_failed", pending_review=False,
                      event={"msg": "gates failed", "report": report[:2000]})
        if report == self.last_fail and not first_pass:
            proj.event(f"{tid}: identical failure twice - blocking to save tokens")
            return BLOCK, report
        self.last_fail = report
        self.feedback = report
        return RETRY, report

    def _review(self, base, report):
        proj, tid = self.proj, self.tid
        # Cross review against whoever wrote the branch's newest work: a failed attempt that
        # changed nothing (e.g. the worker crashed) must not make the author its own reviewer.
        author = branch_author(proj, self.wt) or self.worker
        reviewer, rv = self._run_reviewer(author, base, report)
        if reviewer == WAIT:
            proj.event(f"{tid}: gates passed, but every reviewer allowed for {author}'s work is cooling down "
                       "- card waits for review (no worker rerun needed)")
            return self._park("waiting for a free reviewer", pending_review=True)
        if not reviewer:
            return None
        verdict = (rv.data or {}).get("verdict", "FAIL" if rv.data else "ERROR")
        (proj.logs / f"{tid}-review-{self.attempts}.json").write_text(json.dumps(rv.data, indent=2))
        if verdict == "PASS":
            return None
        issues = (rv.data or {}).get("issues", []) or [{"problem": rv.text[:1500] or "reviewer gave no verdict"}]
        self.feedback = "REVIEWER REJECTED your change. Fix every blocking issue:\n" + "\n".join(
            f"- [{i.get('severity', 'blocker')}] {i.get('file', '')}: {i.get('problem', '')} "
            f"-> {i.get('fix', '')}" for i in issues)
        proj.event(f"{tid}: review {verdict} by {reviewer}")
        proj.set_task(tid, status="review_failed", pending_review=False,
                      event={"msg": f"review {verdict}", "issues": issues})
        return RETRY

    def _run_reviewer(self, author, base, report):
        """(reviewer, its AgentResult). reviewer is None when review is off, WAIT when nobody
        allowed is free. A reviewer that hits a limit cools down and the next one is asked."""
        proj, tid = self.proj, self.tid
        while True:
            reviewer = pick_reviewer(proj, author)
            if reviewer in (None, WAIT):
                return reviewer, None
            diff = git(self.wt, "diff", f"{base}...HEAD", check=False)
            cap = proj.c("budget", "max_review_diff_chars", default=60000)
            if len(diff) > cap:
                diff = diff[:cap] + "\n[... diff truncated; read files directly ...]"
            rprompt = render(with_context(proj.prompt("reviewer"), build_context(proj, self.card, "review")),
                             CARD=self.card["raw"], DIFF=diff, GATES=report, TASK_ID=tid)
            rv = run_agent(proj, reviewer, "review", rprompt, self.wt, tid, schema="review")
            if not rv.limited:
                return reviewer, rv
            self.hops += 1   # that reviewer now cools down; pick_reviewer offers the next one
            if self.hops > self.max_hops:
                return WAIT, rv

    def _merge(self, base):
        """Sync with main once more and fast-forward it, one task at a time."""
        proj, tid, wt, main = self.proj, self.tid, self.wt, self.proj.main
        with MERGE_LOCK:
            ok, conflicts = sync_main(wt, main)
            if ok and git(wt, "rev-parse", f"{main}") != base:
                gok, report = run_gates(proj, wt, git(wt, "merge-base", "HEAD", main), self.card)
                if not gok:
                    self.feedback = f"After merging latest {main}, gates fail:\n{report}"
                    proj.set_task(tid, status="gates_failed", event={"msg": "gates failed after sync", "report": report[:2000]})
                    return RETRY
            if not ok:
                self.feedback = f"Conflict with {main} in {conflicts}; redo on top of current code."
                proj.set_task(tid, event={"msg": "merge conflict at merge time", "files": conflicts})
                sh(["git", "-C", str(wt), "reset", "-q", "--hard", main], check=False)
                return RETRY
            r = sh(["git", "-C", str(proj.root), "merge", "--ff-only", "-q", self.branch], check=False)
            if r.returncode != 0:
                proj.event(f"{tid}: ff-merge failed: {r.stderr.strip()}")
                proj.set_task(tid, status="blocked", event={"msg": "ff merge failed", "err": r.stderr})
                return False
        proj.event(f"{tid}: MERGED into {main}")
        proj.set_task(tid, status="done", pending_review=False, feedback="", event={"msg": "merged"})
        sh(["git", "-C", str(proj.root), "worktree", "remove", "--force", str(wt)], check=False)
        return True
