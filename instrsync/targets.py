"""Per-agent delivery targets for standing instructions.

Two shapes. A FileTarget owns one marker-delimited block inside an instructions
file the agent loads at user scope; everything outside the block belongs to the
user and is never touched. A HookTarget has no file: the agent's governor adapter
renders the instructions at session start and hands them over as context, so
there is nothing to write — sync only verifies the hook is wired.
"""
import json
import os
from dataclasses import dataclass

HOME = os.path.expanduser("~")


def _display(path):
    return "~" + path[len(HOME):] if path.startswith(HOME + os.sep) else path


@dataclass
class FileTarget:
    name: str  # instrsync's id for the agent (matches the `agents:` frontmatter key)
    label: str  # human name for logs
    file: str  # instructions file, ~-expanded at use
    kind = "file"

    def path(self):
        return os.path.expanduser(self.file)

    def describe(self):
        return f"managed block in {_display(self.path())}"


@dataclass
class HookTarget:
    name: str
    label: str
    hooks_file: str  # the agent's hook config, ~-expanded at use
    event: str  # hook event whose output carries the instructions
    adapter: str  # substring identifying the governor adapter in a hook command
    kind = "hook"

    def path(self):
        return os.path.expanduser(self.hooks_file)

    def describe(self):
        return f"injected live by {self.adapter} on {self.event} (no user-level rules file)"

    def wired(self):
        try:
            with open(self.path(), encoding="utf-8") as fh:
                hooks = (json.load(fh) or {}).get("hooks") or {}
        except (FileNotFoundError, ValueError):
            return False
        entries = hooks.get(self.event) or []
        return any(self.adapter in (e.get("command") or "") for e in entries if isinstance(e, dict))

    def check(self, body):
        if not self.wired():
            return (f"NOT WIRED: add a `{self.event}` hook to {_display(self.path())} "
                    f"(see install/cursor.hooks.json)")
        if not body:
            return f"live via {self.event} hook (nothing targets {self.label}; injects nothing)"
        return f"live via {self.event} hook ({len(body)} bytes injected at each session start)"


TARGETS = {
    "claude_code": FileTarget(
        name="claude_code", label="Claude Code", file="~/.claude/CLAUDE.md",
    ),
    "codex": FileTarget(
        name="codex", label="Codex",
        file=os.path.join(os.environ.get("CODEX_HOME") or "~/.codex", "AGENTS.md"),
    ),
    "cursor": HookTarget(
        name="cursor", label="Cursor", hooks_file="~/.cursor/hooks.json",
        event="sessionStart", adapter="adapters/cursor.py",
    ),
}

ALL_TARGETS = list(TARGETS.keys())
