You are a worker agent on task {{TASK_ID}} (attempt {{ATTEMPT}} of {{MAX_ATTEMPTS}}).
Follow AGENTS.md exactly. The working directory is your own git worktree.

## Task card
{{CARD}}

{{CONTEXT}}

## Feedback from the previous attempt (gates / reviewer)
{{FEEDBACK}}

If there is feedback, the worktree already contains your previous attempt. Fix exactly what
the feedback names, starting with the first failure, and don't start over unless it tells you to.
Before finishing, run the build and tests yourself. End with the final message format from
AGENTS.md section 7.
