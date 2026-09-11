"""Per-agent target definitions.

Each Target says where an agent keeps its skills, which frontmatter keys that
agent understands (everything else is dropped on emit), which per-agent mechanics
file to splice in, and how to register a freshly-written skill so the agent
discovers it. All three agents consume the same `<name>/SKILL.md` directory
layout — the differences are the frontmatter subset, the root path, and Cursor's
sync manifest.
"""
import json
import os
import time
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class Target:
    name: str  # skillsync's id for the agent (matches the `agents:` frontmatter key)
    label: str  # human name for logs
    root: str  # skills dir, ~-expanded at use
    keep_keys: set  # frontmatter keys this agent understands; others are dropped
    register: Optional[Callable[["Target", str], None]] = field(default=None)

    def skill_dir(self, skill_name):
        return os.path.join(os.path.expanduser(self.root), skill_name)


def _register_cursor(target, skill_name):
    """Record the skill in Cursor's sync manifest so it isn't treated as stray.

    Cursor tracks synced skills in `.sync-manifest.json` (skill id -> lastSyncedAt
    epoch-ms). We add/update our own entry and never touch the builtin/managed
    manifest, which Cursor owns.
    """
    manifest = os.path.join(os.path.expanduser(target.root), ".sync-manifest.json")
    try:
        with open(manifest) as fh:
            data = json.load(fh)
    except (FileNotFoundError, ValueError):
        data = {"version": 1, "skills": {}}
    data.setdefault("skills", {})[skill_name] = {"lastSyncedAt": int(time.time() * 1000)}
    tmp = manifest + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, manifest)


# Frontmatter keys Claude Code understands (superset — canonical files should stay
# close to name/description, but passing these through keeps richer skills valid).
_CLAUDE_KEYS = {
    "name", "description", "disable-model-invocation",
    "allowed-tools", "argument-hint", "user-invocable", "license", "version",
}
# Cursor's frontmatter is minimal; anything else shows up as literal YAML text.
_CURSOR_KEYS = {"name", "description", "disable-model-invocation"}
# Codex sticks to the basics, plus disable-model-invocation so a deliberately
# slash-only skill (e.g. triage-pr-review-comments) stays non-auto-invoked here
# too — matching Cursor. Harmless if Codex ignores the key.
_CODEX_KEYS = {"name", "description", "disable-model-invocation"}


TARGETS = {
    "claude_code": Target(
        name="claude_code", label="Claude Code",
        root="~/.claude/skills", keep_keys=_CLAUDE_KEYS,
    ),
    "codex": Target(
        name="codex", label="Codex",
        root="~/.codex/skills", keep_keys=_CODEX_KEYS,
    ),
    "cursor": Target(
        name="cursor", label="Cursor",
        root="~/.cursor/skills-cursor", keep_keys=_CURSOR_KEYS,
        register=_register_cursor,
    ),
}

ALL_TARGETS = list(TARGETS.keys())
