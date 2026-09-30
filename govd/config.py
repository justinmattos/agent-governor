import os

GOVD_HOME = os.path.expanduser(os.environ.get("GOVD_HOME", "~/.govd"))
HOST = "127.0.0.1"
DEFAULT_PORT = int(os.environ.get("GOVD_PORT", "8787"))

PORT_FILE = os.path.join(GOVD_HOME, "port")
PID_FILE = os.path.join(GOVD_HOME, "govd.pid")
AUDIT_FILE = os.path.join(GOVD_HOME, "audit.jsonl")
ADAPTER_ERROR_LOG = os.path.join(GOVD_HOME, "adapter-errors.log")

VERSION = "0.1.0"

# Orphaned MCP server processes (see govd/reaper.py). A comma-separated list of
# substrings matched against the full command line; empty disables the reaper, as
# does an interval of 0.
REAP_PATTERNS = [p.strip() for p in os.environ.get("GOVD_REAP_PATTERNS", "mongodb-mcp-server").split(",") if p.strip()]
REAP_INTERVAL_SECONDS = int(os.environ.get("GOVD_REAP_INTERVAL", "300"))
REAP_GRACE_SECONDS = int(os.environ.get("GOVD_REAP_GRACE", "120"))


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
