"""hooksync — install the governor's hook config into each agent's live settings.

Author the per-agent hook config once under `install/*.json`; hooksync merges the
governor's own hook entries into `~/.claude/settings.json`, `~/.codex/hooks.json`,
and `~/.cursor/hooks.json` idempotently, leaving everything else in those files
untouched. The daemon governs actions, skillsync governs skills, instrsync governs
instructions; hooksync is what wires the adapters that feed the daemon.
"""
