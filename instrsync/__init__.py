"""instrsync — deliver one set of standing instructions into every coding agent.

Canonical instructions live in `instructions/*.md`: short, always-on context the
user would otherwise re-type into every session (pronouns, house preferences).
`instrsync` renders them per agent and delivers them at *user* scope, so they apply
in every project and every worktree: a managed block spliced into
`~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md`, and — because Cursor has no
user-level rules file — served live to `adapters/cursor.py`, which returns them
as `additional_context` from Cursor's `sessionStart` hook. See
`instrsync/targets.py` for the per-agent definitions and `instrsync/sync.py` for
the engine + CLI.
"""
