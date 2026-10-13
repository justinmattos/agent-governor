"""Embedded mode: govd running inside a cloud agent sandbox.

The hooks plugin that skillsync publishes (see skillsync/publish.py) bundles the
adapters with govd itself and sets GOVD_EMBEDDED=1 on every hook command. There is
no LaunchAgent in a sandbox, so the first hook that finds the daemon down starts it
from the bundle, and later hooks reuse it — the daemon keeps per-session state
(e.g. plan_format's plan list) that a one-shot evaluation would lose.

No human answers prompts in an unattended task, so an "ask" is enforced as a deny.
"""
import os
import subprocess
import sys
import time
import urllib.request

EMBEDDED = os.environ.get("GOVD_EMBEDDED") == "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNATTENDED = " (No one can answer a prompt in an unattended cloud task, so this 'ask' is enforced as a deny.)"
START_TIMEOUT = 3.0


def _healthy(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/health", timeout=0.5) as resp:
            return resp.status == 200
    except Exception:
        return False


def ensure_daemon(port, home):
    """Start govd from this bundle unless it already answers. True once it's healthy.

    Two hooks racing here both spawn a server; the loser fails to bind and exits.
    """
    if _healthy(port):
        return True
    os.makedirs(home, mode=0o700, exist_ok=True)
    with open(os.path.join(home, "govd.out.log"), "ab") as log:
        subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "govd", "server.py")],
            stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True,
        )
    deadline = time.time() + START_TIMEOUT
    while time.time() < deadline:
        if _healthy(port):
            return True
        time.sleep(0.1)
    return False


def instructions(agent):
    """Standing instructions for `agent`, rendered from the bundled `instructions/`."""
    sys.path.insert(0, ROOT)
    from instrsync.sync import render
    return render(agent)
