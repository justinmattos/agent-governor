"""Per-agent hook-install targets.

Each target maps a canonical `install/*.json` to the agent's live hook settings
file and names the adapter substring that identifies the governor's own entries in
that file — so a sync can replace them without disturbing hooks the user added.
"""
import os
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.expanduser("~")


def _display(path):
    return "~" + path[len(HOME):] if path.startswith(HOME + os.sep) else path


@dataclass
class HookTarget:
    name: str  # id used on the CLI (--agents) and in logs
    label: str  # human name
    source: str  # canonical hook config, relative to the repo root
    dest: str  # the agent's live hook settings file (~ / $CODEX_HOME expanded at use)
    adapter: str  # substring identifying the governor's own hook entries

    def source_path(self):
        return os.path.join(ROOT, self.source)

    def dest_path(self):
        return os.path.expanduser(self.dest)

    def describe(self):
        return f"{_display(self.source_path())} -> {_display(self.dest_path())}"


TARGETS = {
    "claude_code": HookTarget(
        name="claude_code", label="Claude Code",
        source="install/claude-code.settings.json", dest="~/.claude/settings.json",
        adapter="adapters/claude_code.py",
    ),
    "codex": HookTarget(
        name="codex", label="Codex",
        source="install/codex.hooks.json",
        dest=os.path.join(os.environ.get("CODEX_HOME") or "~/.codex", "hooks.json"),
        adapter="adapters/codex.py",
    ),
    "cursor": HookTarget(
        name="cursor", label="Cursor",
        source="install/cursor.hooks.json", dest="~/.cursor/hooks.json",
        adapter="adapters/cursor.py",
    ),
}

ALL_TARGETS = list(TARGETS.keys())
