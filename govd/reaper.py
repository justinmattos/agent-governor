"""Reap MCP server processes left behind by ended agent sessions.

An agent session starts its stdio MCP servers as child processes. When the session
ends without shutting them down, they are reparented to launchd (ppid 1) and keep
running — each one holding memory, often in swap, until the machine restarts. The
reaper finds those orphans by command pattern and stops them together with their
descendants (the `npm exec` wrapper's node server, for instance).

Only a process that matches a configured pattern AND has been adopted by launchd
AND is older than the grace period counts as an orphan: a live session's server
always has that session as its parent, so it is never touched.
"""
import os
import re
import signal
import subprocess
import threading
import time
from collections import namedtuple

from . import audit, config

Proc = namedtuple("Proc", "pid ppid age rss command")

_ETIME = re.compile(r"^(?:(?:(\d+)-)?(\d+):)?(\d+):(\d+)$")


def _seconds(etime):
    m = _ETIME.match(etime.strip())
    if not m:
        return 0
    days, hours, minutes, seconds = (int(g or 0) for g in m.groups())
    return ((days * 24 + hours) * 60 + minutes) * 60 + seconds


def snapshot():
    out = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,etime=,rss=,command="],
        capture_output=True, text=True, timeout=10,
    ).stdout
    procs = []
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        try:
            procs.append(Proc(int(parts[0]), int(parts[1]), _seconds(parts[2]), int(parts[3]), parts[4]))
        except ValueError:
            continue
    return procs


def find_orphans(procs, patterns, grace):
    """Group each orphaned matching process with its descendants, root first."""
    children = {}
    for p in procs:
        children.setdefault(p.ppid, []).append(p)
    me = os.getpid()
    groups = []
    for root in procs:
        if root.ppid != 1 or root.pid == me or root.age < grace:
            continue
        if not any(pat in root.command for pat in patterns):
            continue
        group, stack = [], [root]
        while stack:
            p = stack.pop()
            group.append(p)
            stack.extend(children.get(p.pid, []))
        groups.append(group)
    return groups


def _still_same(expected):
    """Pids from `expected` that still run the same command under the same parent."""
    now = {p.pid: p for p in snapshot()}
    return [p for p in expected if p.pid in now
            and now[p.pid].ppid == p.ppid and now[p.pid].command == p.command]


def _signal(procs, sig):
    for p in procs:
        try:
            os.kill(p.pid, sig)
        except OSError:
            pass


def kill_group(group, wait=3.0):
    """Stop a group with SIGTERM, then SIGKILL whatever is still running after `wait`.

    Every pid is re-checked against a fresh process table before each signal, so a
    pid the OS has reused for an unrelated process is never signalled.
    """
    _signal(_still_same(group), signal.SIGTERM)
    deadline = time.time() + wait
    while time.time() < deadline:
        if not _still_same(group):
            return
        time.sleep(0.2)
    _signal(_still_same(group), signal.SIGKILL)


def reap(patterns=None, grace=None, dry_run=False):
    """One scan. Returns the orphan groups found (and stopped, unless `dry_run`)."""
    patterns = config.REAP_PATTERNS if patterns is None else patterns
    grace = config.REAP_GRACE_SECONDS if grace is None else grace
    if not patterns:
        return []
    groups = find_orphans(snapshot(), patterns, grace)
    for group in groups:
        if not dry_run:
            kill_group(group)
            try:
                audit.record_reap(group)
            except Exception:
                pass
    return groups


class Reaper:
    """Runs `reap` on an interval in a daemon thread and keeps totals for /v1/health."""

    def __init__(self, interval=None):
        self.interval = config.REAP_INTERVAL_SECONDS if interval is None else interval
        self.last_run = None
        self.groups_reaped = 0
        self.rss_reaped_kb = 0
        self._lock = threading.Lock()

    def run_once(self):
        groups = reap()
        with self._lock:
            self.last_run = time.time()
            self.groups_reaped += len(groups)
            self.rss_reaped_kb += sum(p.rss for g in groups for p in g)
        return groups

    def _loop(self):
        while True:
            try:
                self.run_once()
            except Exception:
                pass
            time.sleep(self.interval)

    def start(self):
        if self.interval > 0 and config.REAP_PATTERNS:
            threading.Thread(target=self._loop, name="govd-reaper", daemon=True).start()
        return self

    def stats(self):
        with self._lock:
            return {
                "enabled": self.interval > 0 and bool(config.REAP_PATTERNS),
                "interval_seconds": self.interval,
                "patterns": list(config.REAP_PATTERNS),
                "last_run": self.last_run,
                "groups_reaped": self.groups_reaped,
                "rss_reaped_mb": round(self.rss_reaped_kb / 1024, 1),
            }
