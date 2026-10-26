"""What a branch changed relative to its merge base, as the gates see it."""
from __future__ import annotations

from ..util import git, sh

def changed_files(wt, base):
    """List (status letter, current path, previous path) for merge-base...HEAD; renames tracked."""
    out = git(wt, "diff", "--name-status", "-M", f"{base}...HEAD")
    res = []
    for line in out.splitlines():
        parts = line.split("\t")
        res.append((parts[0][0], parts[-1], parts[1] if parts[0][0] == "R" else parts[-1]))
    return res  # (status, path_now, path_before)


def added_lines(wt, base, path):
    """Lines added to path in base...HEAD (zero-context diff, '+' prefix stripped)."""
    d = git(wt, "diff", "-U0", f"{base}...HEAD", "--", path, check=False)
    return [l[1:] for l in d.splitlines() if l.startswith("+") and not l.startswith("+++")]


def removed_lines(wt, base, path):
    """Lines removed from path in base...HEAD."""
    d = git(wt, "diff", "-U0", f"{base}...HEAD", "--", path, check=False)
    return [l[1:] for l in d.splitlines() if l.startswith("-") and not l.startswith("---")]


def sample_paths(wt, base):
    """Paths listed in .forge-samples as of `base` (the main-branch side of the diff).

    Read from base, never from the worker's tree, so a worker cannot whitelist a test
    by adding it to the manifest. Missing manifest -> empty set."""
    r = sh(["git", "-C", str(wt), "show", f"{base}:.forge-samples"], check=False)
    if r.returncode != 0:
        return set()
    return {l.strip() for l in r.stdout.splitlines() if l.strip() and not l.strip().startswith("#")}
