"""skillsync — materialize one canonical skill library into every coding agent.

Canonical skills live in `skills/<name>/SKILL.md` (agent-neutral frontmatter +
body). `skillsync` emits an agent-appropriate copy into each agent's own skills
directory: frontmatter is filtered to the keys that agent understands, an
optional per-agent mechanics appendix is spliced in, supporting files are copied,
and the agent's registry (if any) is updated. See `skillsync/targets.py` for the
per-agent definitions and `skillsync/sync.py` for the engine + CLI.
"""
