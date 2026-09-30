# Examples

Copy-ready starting points. Nothing in this directory is live: the syncers scan
`instructions/` and `skills/`, so these files sit here inert until you copy them into
place.

Each subsystem has a **shared** form (committed, everyone gets it) and a **personal**
form (gitignored, only your machine, still applied by your daemon). The personal form
is a `.local` variant: `instructions/*.local.md`, `skills/<name>.local/`, and
`govd/policy/rules/*.local.py`.

## `about-me.local.md` — your personal standing instructions

```bash
cp examples/about-me.local.md instructions/about-me.local.md
$EDITOR instructions/about-me.local.md
bin/govctl instructions-sync
```

Everything matching `instructions/*.local.md` is gitignored, so your copy reaches every
agent on your machine and never lands in this repo. Files under `instructions/` that do
**not** end in `.local.md` are committed and shared with the whole team — put house
conventions there, personal ones in your `.local.md`.

Write instructions as concrete directions rather than self-description: "use they/them
when referring to me, including in commit messages" is followed far more reliably than
"I use they/them". Keep the whole set short — it loads into every session, and Codex
caps the combined size of all `AGENTS.md` files at 32 KiB by default.

Confirm what an agent will actually receive with `bin/govctl instructions-show --agent cursor`.

## `skill/` — a new skill

```bash
# shared (committed, everyone gets it):
cp -r examples/skill skills/<your-skill-name>
# personal (gitignored, your machine only, invoked the same way):
cp -r examples/skill skills/<your-skill-name>.local
$EDITOR skills/<your-skill-name>*/SKILL.md
bin/govctl skills-sync
```

Every directory under `skills/` with a `SKILL.md` is published to all three agents; a
`<name>.local/` dir is gitignored and materializes under the bare `<name>`, so it's
invoked as `/<name>` just like a shared skill (`skills-list` tags it `(personal)`). There
is no frontmatter setting that opts a skill out of sharing — the `.local/` suffix is how
you keep one private, which is why this template lives under `examples/`. Use the `agents:`
key to restrict *which* agents get it, `agents/<agent>.md` for per-agent mechanics, and
`references/` for material the agent should read on demand.

## `profiles/` — MCP servers as agent profiles

```bash
cp examples/profiles/servers.local.json profiles/servers.local.json
cp examples/profiles/investigator.local.md profiles/staging-investigator.local.md
$EDITOR profiles/servers.local.json profiles/*.local.md
bin/govctl profiles-sync --dry-run   # see what it will write and remove
bin/govctl profiles-sync
```

`servers.local.json` is the registry: every MCP server a profile can use, in `.mcp.json`
form, plus `write_tools` (blocked when a profile says `readonly: true`). It holds
connection strings and tokens, so it only ever exists as a gitignored `.local.json`.
`retire` names older everyday entries the registry replaces; a sync removes those and
every registry server from your everyday config. Each `*.local.md` profile becomes a
Claude Code subagent (`~/.claude/agents/<name>.md`) and can be started as its own
session with `bin/govctl profile <name>`.

## A new policy rule

There's no rule template here — the shared rules in `govd/policy/rules/` are the working
examples. Each subclasses `Rule` (`base.py`), filters events in `applies()`, and returns a
`Decision` (or `None` to abstain) from `evaluate()`. Shared shell-parsing helpers live in
`_shell.py`.

**Personal rule** (gitignored, auto-loaded on your machine only) — the common case:

```bash
cp govd/policy/rules/no_narrative_comments.py govd/policy/rules/<your_rule>.local.py
$EDITOR govd/policy/rules/<your_rule>.local.py   # rename the class and its `name`
bin/govctl restart && bin/govctl status          # the new rule should be listed
```

No registration step: the daemon discovers every `*.local.py` here at startup. A fresh
clone has none. (`prefer_graphite` and `plan_format` are this maintainer's personal rules,
shipped this way — so they aren't in the shared repo.)

**Shared rule** (committed, everyone gets it) — copy to a plain `<name>.py` instead, then
register it in `govd/policy/rules/__init__.py` (`SHARED_RULES`). Add a case to `SAMPLES` in
`bin/govctl` so `bin/govctl test` covers it. The engine takes the **most restrictive**
decision any rule returns.
