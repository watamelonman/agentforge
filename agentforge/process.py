"""Launch one agent CLI and supervise it: timeout, paid-overage guard, endless API retries."""
from __future__ import annotations

import collections
import os
import signal
import subprocess
import time

from .parsers.claude import api_retry_stop, overage_in_use, rate_limit_events
from .vendors import CLAUDE_CODE_VENDORS

POLL_SECS = 2   # how often the log is checked while the agent runs


def run_supervised(proj, vendor, tag, cmd, cwd, env, stdin_text, log, timeout):
    """Run `cmd` with stdout+stderr in `log`; return (returncode, retry_stop).

    stdin_text is written to the CLI's stdin (None: stdin is just closed). retry_stop is
    "limit" or "auth" when the run was killed for retrying a 429/401 forever, else None."""
    with open(log, "w") as fh:
        p = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=fh,
                             stderr=subprocess.STDOUT, text=True, env=env,
                             start_new_session=True)
        _feed_stdin(p, stdin_text)
        retry_stop = _watch(proj, vendor, tag, p, log, timeout)
    return p.returncode, retry_stop


def _feed_stdin(p, text):
    try:
        if text is not None:
            p.stdin.write(text)
        p.stdin.close()
    except BrokenPipeError:
        pass


def kill_group(p):
    """SIGTERM the agent's whole process group, SIGKILL it 3 s later if still alive."""
    os.killpg(p.pid, signal.SIGTERM)
    time.sleep(3)
    if p.poll() is None:
        os.killpg(p.pid, signal.SIGKILL)
    p.wait()


class _LogTail:
    """Reads only the bytes added to a log since the last call (stream-json logs reach many
    MB) and keeps the newest 200 complete lines, which is what api_retry_stop looks at."""
    def __init__(self, reader):
        self.reader = reader
        self.recent = collections.deque(maxlen=200)
        self.pending = ""   # a half-written last line, completed by the next read

    def new_lines(self):
        lines = (self.pending + self.reader.read()).split("\n")
        self.pending = lines.pop()
        self.recent.extend(lines)
        return lines


def _watch(proj, vendor, tag, p, log, timeout):
    """Poll until the process exits; kill it on timeout or a bad stream. Returns retry_stop.

    Polling instead of communicate() lets a claude run that starts drawing paid overage be
    stopped within seconds (rate_limit_event arrives early in the stream), not at the end."""
    guard = vendor == "claude" and not proj.c("agents", "claude", "allow_overage", default=False)
    watch = vendor in CLAUDE_CODE_VENDORS and not proj.mock
    deadline = time.time() + timeout
    with open(log, errors="replace") as reader:
        tail = _LogTail(reader)
        while p.poll() is None:
            if time.time() > deadline:
                kill_group(p)
                proj.event(f"{tag}: {vendor} TIMEOUT after {timeout}s - killed")
                return None
            problem = _stream_problem(tag, vendor, tail, guard) if watch else None
            if problem:
                msg, retry_stop = problem
                kill_group(p)
                proj.event(msg)
                return retry_stop
            try:
                p.wait(timeout=POLL_SECS)
            except subprocess.TimeoutExpired:
                pass
    return None


def _stream_problem(tag, vendor, tail, guard):
    """(event message, retry_stop) when the Claude Code stream says to kill the run, else None."""
    lines = tail.new_lines()
    if guard and any(overage_in_use(i) for i in rate_limit_events("\n".join(lines))):
        return f"{tag}: claude switched to paid overage - killed (allow_overage = false)", None
    retry_stop = api_retry_stop("\n".join(tail.recent))
    if retry_stop:
        what = '401/403 (bad key/login)' if retry_stop == 'auth' else '429'
        return f"{tag}: {vendor} API keeps returning {what} - killed", retry_stop
    return None
