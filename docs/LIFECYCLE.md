# Worktree and merge lifecycle

For each card, `run_task` does the following:

1. **Worktree:** `git worktree add -b forge/<ID> .forge/worktrees/<ID> main`. If the
   branch already exists, it's reused, so a re-run continues the earlier work.
2. **Attempt loop** (up to `max_attempts`):
   1. Pick the worker: the card's `agent`, otherwise round-robin over the `workers` that aren't
      cooling down (or, if all are out, over `fallback_workers`). From attempt 3, switch vendor
      if `swap_on_retry` is set. If no suitable
      vendor is free, the card goes back to `todo` until one is.
   2. Run the worker in the worktree with the card and the previous feedback. If it hits a
      usage limit, its partial work is committed, the attempt isn't counted, and the next free
      worker continues (see [LIMITS](LIMITS.md)).
   3. `git add -A && git commit` (by forge, with `--no-verify`).
   4. `git merge main` into the branch. On conflict: abort, `reset --hard main`, and tell the
      worker which files conflicted. The previous attempt's work is discarded.
   5. Run the gates against `merge-base(HEAD, main)`. On failure, the report becomes the next
      attempt's feedback.
   6. Run the reviewer. On FAIL, its issues become the next attempt's feedback. If the reviewer
      hits a usage limit, the next allowed reviewer takes over; if none is free, the card is
      parked with `pending_review` and later resumes at step 4 without a new worker run.
   7. Under `MERGE_LOCK`: merge `main` again. If `main` moved, run the gates again. Then
      `git merge --ff-only forge/<ID>` in the main checkout, and remove the worktree. Status
      becomes `done`.
3. When attempts run out, status becomes `blocked`. The worktree and branch are kept for
   inspection (`forge review <ID> --gates-only`, or `cd .forge/worktrees/<ID>`).

`CHANGELOG.md` and `docs/DECISIONS.md` use git's `union` merge driver (`.gitattributes`), so
parallel appends don't conflict.

**Your rules while forge runs:** don't commit to `main` in the main checkout (the
fast-forward would fail and the task becomes `blocked`). Make your own changes on another
branch or in the editor between runs. `forge run` refuses to start with uncommitted
tracked changes (except `docs/SPEC_ISSUES.md`, which `forge plan` rewrites) or when
you're not on `main_branch`.

## Who reviews

The reviewer is chosen against the vendor that wrote the branch's newest work, read from the
newest `<ID>: attempt N by <vendor>` commit. An attempt that changed nothing (for example a
worker that crashed) leaves no commit, so the previous author stays the author and is never
asked to review its own change.

## Stops

A global stop (`max_agent_runs` reached, SIGTERM) returns in-flight cards to `todo` instead of
`blocked`, as long as they still had attempts left. Agent processes already running are not
killed; each card stops at its next step. `budget.max_total_usd` is not a global stop: it
only disables `claude`. A vendor usage limit is **not** a global
stop: only that vendor pauses, and a usage-limited run is not counted as an attempt. Parked
cards keep their last feedback in `state.json` (`feedback`), so whoever continues sees it.
Details: [LIMITS](LIMITS.md).

## Re-gating existing work

The re-gate pass attributes the change to the vendor named in the newest
`<ID>: attempt N by <vendor>` commit on the branch (falling back to the task state), records
it as the task's `agent`, and picks the cross-vendor reviewer from that vendor.
`forge regate ID` runs the same lifecycle from step 4 (merge main, gates, review, merge) on
the branch as it already is. The worker step is skipped. A failure stops there unless you
pass `--continue`, and a conflict marks the task `blocked` rather than resetting the branch.
Before the first worker (and before a re-gate), `[setup] restore` runs in the worktree.

## Scheduling
A card is ready when it's not done or blocked, all its `deps` are done, it belongs to the
lowest open milestone (if `strict_milestones`), its `owns` don't overlap the `owns` of a
running card, and a vendor it needs next is free (`can_start`: a reviewer for a card waiting
for review, otherwise a worker). Cards held back only by cooling vendors make `forge run`
end with a message, or sleep until the next vendor frees up with `--wait`. Overlap is conservative: two globs overlap if one's literal prefix (the text
before the first `*`) starts with the other's.
