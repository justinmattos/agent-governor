import os

GOVD_HOME = os.path.expanduser(os.environ.get("GOVD_HOME", "~/.govd"))
HOST = "127.0.0.1"
DEFAULT_PORT = int(os.environ.get("GOVD_PORT", "8787"))

PORT_FILE = os.path.join(GOVD_HOME, "port")
PID_FILE = os.path.join(GOVD_HOME, "govd.pid")
AUDIT_FILE = os.path.join(GOVD_HOME, "audit.jsonl")
ADAPTER_ERROR_LOG = os.path.join(GOVD_HOME, "adapter-errors.log")

VERSION = "0.1.0"


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
