"""Git plumbing for task branches: worktrees, commits, syncing with main, authorship."""
from __future__ import annotations

import re
import subprocess

from .util import event_excerpt, git, sh
from .vendors import vendor_names

def ensure_worktree(proj, tid):
    """Create (or reuse) .forge/worktrees/<id> on branch forge/<id> from main.

    Reusing an existing branch means an interrupted run resumes the previous work."""
    wt = proj.wts / tid
    branch = f"forge/{tid}"
    if not wt.exists():
        exists = git(proj.root, "branch", "--list", branch)
        if exists:
            git(proj.root, "worktree", "add", str(wt), branch)
        else:
            git(proj.root, "worktree", "add", "-b", branch, str(wt), proj.main)
    return wt, branch


def commit_all(wt, msg):
    """Stage and commit everything in the worktree; False if there was nothing to commit.

    --no-verify: project hooks must not block the orchestrator; the gates are the checks."""
    git(wt, "add", "-A")
    r = sh(["git", "-C", str(wt), "commit", "-q", "--no-verify", "-m", msg], check=False)
    return r.returncode == 0


def sync_main(wt, main):
    """Merge main into the task branch. On conflict abort and return (False, files)."""
    r = sh(["git", "-C", str(wt), "merge", "--no-edit", "-q", main], check=False)
    if r.returncode != 0:
        conflicts = git(wt, "diff", "--name-only", "--diff-filter=U", check=False)
        sh(["git", "-C", str(wt), "merge", "--abort"], check=False)
        return False, conflicts
    return True, ""


def restore_deps(proj, wt, tid):
    """Run [setup] restore (e.g. `dotnet restore`) in the worktree before a worker starts.

    Agent sandboxes may have no network; restoring here, outside any sandbox, fills the
    package cache and obj/ so offline builds inside the sandbox still work. Failure is
    logged, not fatal: the build gate will report the real error."""
    cmd = proj.c("setup", "restore", default="")
    if not cmd:
        return True
    try:
        r = sh(cmd, cwd=wt, check=False, timeout=proj.c("setup", "timeout_sec", default=600))
    except subprocess.TimeoutExpired:
        proj.event(f"{tid}: restore timed out: {cmd}")
        return False
    if r.returncode != 0:
        proj.event(f"{tid}: restore FAILED (`{cmd}` rc={r.returncode})\n" + event_excerpt(r.stdout + r.stderr, 10))
    return r.returncode == 0


def branch_author(proj, wt):
    """Vendor that produced the newest work on this branch, read from forge's own
    "<ID>: attempt N by <vendor>" commit messages. Used by regate so the cross-vendor
    reviewer is chosen against the vendor that actually wrote the change (task state
    may name a later, failed attempt). None when no such commit exists."""
    log = git(wt, "log", "--format=%s", f"{proj.main}..HEAD")
    for subj in log.splitlines():
        m = re.search(r": attempt \d+ by ([\w.-]+)$", subj)
        if m and m.group(1) in vendor_names(proj):
            return m.group(1)
    return None
