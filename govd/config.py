import json
import os

GOVD_HOME = os.path.expanduser(os.environ.get("GOVD_HOME", "~/.govd"))
HOST = "127.0.0.1"
DEFAULT_PORT = int(os.environ.get("GOVD_PORT", "8787"))

PORT_FILE = os.path.join(GOVD_HOME, "port")
PID_FILE = os.path.join(GOVD_HOME, "govd.pid")
AUDIT_FILE = os.path.join(GOVD_HOME, "audit.jsonl")
ADAPTER_ERROR_LOG = os.path.join(GOVD_HOME, "adapter-errors.log")

VERSION = "0.1.0"

# Personal, gitignored daemon settings (govd/config.local.json). A fresh clone has
# none, so anything configured only here is off for everyone else.
try:
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.local.json")) as _fh:
        LOCAL = json.load(_fh)
except (FileNotFoundError, ValueError):
    LOCAL = {}

# Orphaned MCP server processes (see govd/reaper.py). Opt-in: substrings matched
# against the full command line, from GOVD_REAP_PATTERNS (comma-separated) or
# `reap_patterns` in config.local.json. No patterns, or an interval of 0, disables it.
_patterns = os.environ.get("GOVD_REAP_PATTERNS")
REAP_PATTERNS = ([p.strip() for p in _patterns.split(",") if p.strip()] if _patterns is not None
                 else list(LOCAL.get("reap_patterns") or []))
REAP_INTERVAL_SECONDS = int(os.environ.get("GOVD_REAP_INTERVAL", LOCAL.get("reap_interval_seconds", 300)))
REAP_GRACE_SECONDS = int(os.environ.get("GOVD_REAP_GRACE", LOCAL.get("reap_grace_seconds", 120)))


def ensure_home():
    os.makedirs(GOVD_HOME, mode=0o700, exist_ok=True)
    try:
        os.chmod(GOVD_HOME, 0o700)
        for name in os.listdir(GOVD_HOME):
            path = os.path.join(GOVD_HOME, name)
            if os.path.isfile(path):
                os.chmod(path, 0o600)
    except OSError:
        pass

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Reverse-DNS label for the macOS LaunchAgent. Override it to install under your
# own namespace; the plist filename follows.
LAUNCH_AGENT_LABEL = os.environ.get("GOVD_LAUNCH_LABEL", "com.governor.govd")
LAUNCH_AGENT_PLIST = os.path.expanduser(f"~/Library/LaunchAgents/{LAUNCH_AGENT_LABEL}.plist")
