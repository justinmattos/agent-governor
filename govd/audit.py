import json
import os
import re
import threading
from datetime import datetime, timezone

from . import config

_lock = threading.Lock()

# Credential-shaped values are replaced before anything reaches disk: the log
# records every command an agent ran, and commands carry secrets.
_SECRET_KEY = (
    r"[A-Za-z0-9_.-]*(?:api[_-]?key|apikey|access[_-]?key|private[_-]?key|client[_-]?secret"
    r"|secret|token|passw(?:or)?d|pwd)[A-Za-z0-9_.-]*"
)
_REDACTIONS = [
    (re.compile(r"(?i)(authorization\s*:\s*(?:bearer|basic|token)\s+)[^\s\"']+"), r"\1[REDACTED]"),
    (re.compile(r"((?:^|\s)(?:-u|--user|--proxy-user)[\s=]+[\"']?[^\s:\"']+:)[^\s\"']+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)((?:^|\s)--(?:password|passwd|pass|token|api[-_]?key|apikey|secret|access[-_]?token|client[-_]?secret|private[-_]?key)\s+)([\"']?)((?=[^\s\"']*[0-9_./+=-])[^\s\"']{6,}|[^\s\"']{12,})\2"), r"\1\2[REDACTED]\2"),
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{16,}"), r"\1[REDACTED]"),
    (re.compile(r"(?i)\b(" + _SECRET_KEY + r")([\"']?\s*[=:]\s*[\"']?)([^\s\"'&;|]+)"), r"\1\2[REDACTED]"),
    (re.compile(r"(://[^/\s:@]*:)[^@\s/]+@"), r"\1[REDACTED]@"),
    (re.compile(r"(?i)([?&](?:token|signature|sig|key|secret|access_token|api_key|apikey|password|passwd|pwd)=)[^&\s\"']+"), r"\1[REDACTED]"),
    (re.compile(r"\bgh[opusr]_[A-Za-z0-9]{20,}"), "[REDACTED]"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), "[REDACTED]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "[REDACTED]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}(?:\.[A-Za-z0-9_-]+)?"), "[REDACTED]"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"), "[REDACTED]"),
]


def redact(text):
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def record(event, decision):
    line = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "agent": event.agent,
        "event": event.event,
        "tool": event.tool,
        "raw_tool_name": event.raw_tool_name,
        "target": redact(_target(event)),
        "cwd": event.cwd,
        "session_id": event.session_id,
        "decision": decision.decision,
        "reason": redact(decision.reason),
        "rules": decision.rule,
    }
    with _lock:
        fd = os.open(config.AUDIT_FILE, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")


def _target(event):
    data = event.input or {}
    if "command" in data:
        return str(data.get("command"))[:400]
    for key in ("file_path", "path", "file"):
        if key in data:
            return str(data.get(key))
    return ""
