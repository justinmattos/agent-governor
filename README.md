# governor — one governance layer for every coding agent

> **TL;DR** — `govd` is a local daemon that enforces one policy set (type-check
> locking, dangerous-command blocking, self-protection — plus your own personal rules
> like Graphite-preferred git) across **Claude Code, Codex, and Cursor** at once,
> `skillsync` publishes one shared skill library to all three, and `instrsync` delivers
> one set of standing instructions (your pronouns, house preferences) into each agent's
> user-scope context, and `profilesync` keeps MCP servers out of everyday sessions by
> moving them into agent profiles. Rules, skills, instructions, and profiles are
> authored once and apply everywhere — and each has a gitignored `.local` layer for
> what's personal to you.

This repo governs the AI coding agents running on a developer's machine from a single
source of truth. It has four parts that share one repo and one CLI (`bin/govctl`):

- **[`govd`](#govd--governing-actions) — governs _actions._** An always-on local daemon
  decides `allow` / `ask` / `deny` on what an agent is about to _do_ (run a shell
  command, edit a file), the same way for every agent.
- **[`skillsync`](#skillsync--governing-skills) — governs _skills._** One canonical
  skill library is materialized into every agent's own skills directory, so the skills
  you _invoke_ are authored once and identical everywhere.
- **[`instrsync`](#instrsync--governing-instructions) — governs _instructions._** One
  set of standing instructions — the always-on context every agent should hold in every
  session, like your pronouns — is delivered into each agent's user-scope context.
- **[`profilesync`](#profilesync--governing-mcp-servers) — governs _MCP servers._**
  Servers live in named profiles instead of every session; each profile runs as a worker
  your main session delegates to, or as a session of its own.

```
ACTIONS — runtime governance ─────────────────────────────────────────────────
 Claude Code ─┐                        ┌─ adapters/claude_code.py ─┐
 Codex ───────┤  native hooks (stdin)  ├─ adapters/codex.py       ─┤  POST /v1/evaluate
 Cursor ──────┘                        └─ adapters/cursor.py      ─┘        │
                                                                            ▼
                                                     ┌──────────────────────────────────┐
                                                     │  govd  (127.0.0.1, localhost)    │
                                                     │  policy engine + rules           │
                                                     │  shared state (typecheck lock)   │
                                                     │  audit log (~/.govd/audit.jsonl) │
                                                     └──────────────────────────────────┘

SKILLS — authored once, synced everywhere ────────────────────────────────────
                                                            ┌─ ~/.claude/skills/<name>/
 skills/<name>/ ── skillsync (filter fm, splice, place) ────┼─ ~/.codex/skills/<name>/
   SKILL.md                                                 └─ ~/.cursor/skills-cursor/<name>/  (+ sync manifest)
   agents/
   references/

INSTRUCTIONS — standing context, authored once ───────────────────────────────
                                                            ┌─ ~/.claude/CLAUDE.md   (managed block)
 instructions/*.md ── instrsync (concat, splice block) ─────┼─ ~/.codex/AGENTS.md    (managed block)
                                                            └─ Cursor: no user-level rules file, so
                                                               adapters/cursor.py injects them live
                                                               as sessionStart additional_context
```

**Why one shared layer instead of per-agent config**

- **Author once, all three agents obey it.** No per-agent duplication of rules, skills, or instructions.
- **Shared runtime state** a per-agent hook can't see — e.g. a `tsc` started by Claude Code blocks one attempted by Codex or Cursor.
- **One audit trail** of every governed action across every agent.

## Repo layout

| Path                                     | Purpose                                                                                                  |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `govd/server.py`                         | the daemon (Python stdlib only)                                                                          |
| `govd/policy/engine.py`                  | rule runner; most-restrictive decision wins                                                              |
| `govd/policy/rules/`                     | one file per rule; `*.local.py` is gitignored and auto-loaded for personal rules                         |
| `govd/state.py`                          | shared lock table                                                                                        |
| `govd/reaper.py`                         | stops MCP server processes left behind by ended agent sessions                                           |
| `govd/audit.py`                          | JSONL audit log                                                                                          |
| `adapters/{claude_code,codex,cursor}.py` | per-agent stdin→daemon→stdout translators                                                                |
| `skills/<name>/`                         | canonical skill library — one `SKILL.md` per skill; `<name>.local/` is gitignored for personal skills    |
| `skillsync/`                             | materializes each canonical skill into every agent's own skills dir                                      |
| `instructions/*.md`                      | canonical standing instructions — one topic per file, delivered to every agent at user scope; `*.local.md` is gitignored for personal ones |
| `instrsync/`                             | splices the instructions into `~/.claude/CLAUDE.md` / `~/.codex/AGENTS.md`; serves them to the Cursor adapter |
| `examples/`                              | copy-ready templates: personal instructions, a skill, and a pointer to the rule template; inert where they sit |
| `bin/govctl`                             | one CLI for all three: start / stop / status / tail / reap / mcp-cost / test / install-agent / hooks-sync / hooks-list / skills-sync / skills-list / instructions-sync / instructions-list / instructions-show / profiles-sync / profiles-list / profile / secrets-import / mcp-launch / mcp-headers |
| `install/*.json`                         | canonical per-agent hook config, the source of truth; `{python}` / `{governor_root}` are resolved at sync time |
| `profiles/`                              | agent profiles (`<name>.local.md`) and the MCP server registry (`servers.local.json`), both gitignored |
| `profilesync/`                           | turns each profile into a Claude Code subagent and a Codex session profile, and removes its servers from everyday config |
| `hooksync/`                              | merges the hook config into each agent's live settings (`~/.claude/settings.json`, `~/.codex/hooks.json`, `~/.cursor/hooks.json`) |

State and logs live in `~/.govd/` (`port`, `govd.pid`, `audit.jsonl`, `govd.out.log`,
`adapter-errors.log`). The directory is `0700` and its files `0600`, re-applied on every
daemon start, and the audit log redacts credential-shaped values before writing —
bearer/basic auth headers, `*token*=` / `*secret*=` / `*key*=` / `password=` pairs, URL
passwords and `?token=`-style parameters, GitHub/OpenAI/Slack/AWS token shapes, JWTs,
and PEM private keys. `govctl tail` strips control characters before printing, so a
command carrying terminal escape sequences cannot rewrite what you see. The daemon
listens on loopback only and accepts only `Content-Type: application/json`, so a web
page cannot drive it with a no-CORS form post. Override the daemon port with
`GOVD_PORT`.

---

# govd — governing actions

`govd` is a single always-on local daemon that enforces one set of policies across
every AI coding agent on this machine. Each agent's native hook system calls a thin
adapter; the adapter forwards a normalized event to the daemon over `127.0.0.1`, which
decides `allow` / `ask` / `deny` and returns guidance. Policy, shared state, and the
audit log live in one place instead of being copied into each agent's config. When
several rules match, the **most-restrictive decision wins**.

## Why a daemon

- **Write a rule once, all three agents obey it.** No per-agent duplication.
- **Shared runtime state.** The typecheck lock coordinates across agents — a `tsc`
  started by Claude Code blocks one attempted by Codex or Cursor. A per-agent hook
  can't see the others.
- **One audit trail** of every governed action across every agent.

## Shared rules

These ship with the repo and load on every install. Two more —
`prefer_graphite` and `plan_format` — are **personal** on this maintainer's machine;
see [Personal rules](#personal-rules).

| Rule                    | Fires on              | Effect                                                                                                                                                                                                                                               |
| ----------------------- | --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `typecheck_lock`        | shell `tsc`/`tsgo`    | denies a second concurrent type-check anywhere on the machine (holds a daemon lock + checks the process table)                                                                                                                                       |
| `no_narrative_comments` | edits to `.ts`/`.tsx` | surfaces newly-added narrative comments and demands the deletion test                                                                                                                                                                                |
| `dangerous_bash`        | shell commands        | denies catastrophic commands: a recursive `rm`, `chmod`/`chown`, or `find -delete` aimed at `/`, `~`, or a system dir in any spelling (`-rf`, `-fr`, `-r -f`, `--recursive`, `/*`, `"$HOME"`, via `sudo`/`sh -c`/`eval`/`ssh`), fork bombs, `mkfs`/`wipefs`/`diskutil erase`, and raw block-device writes. Regex-proof indirection (`base64 \| sh`, `python -c`) is out of scope — that is what the agent's own permission prompt is for                                                                                                                                         |
| `secret_reads`          | shell commands        | asks before an agent's shell prints a keychain password (`security find-*-password -w`/`-g`), dumps or exports the keychain, runs `govctl mcp-headers`, or touches a `*.bak-govd-*` config backup — the MCP credentials [`profilesync`](#credentials-in-the-keychain) keeps out of files. Pattern-matched, so `python -c` indirection gets past it |
| `protect_governor`      | shell, file edits, Claude Code settings changes | asks a human before any action that would modify or disable the governor itself — this repo's `adapters/`, `govd/`, `bin/`, `install/`, `~/.govd`, each agent's hook config, the LaunchAgent, `govctl stop`/`restart`, killing the daemon, `disableAllHooks` — and blocks a live Claude Code settings change that drops the govd hook or sets `disableAllHooks`. Reads (`cat`, `grep`, `git log`, `govctl status`/`tail`/`test`) pass untouched. A session working **inside this repo** (cwd under the repo root) edits its own source (`adapters/`, `govd/`, `bin/`, `install/`) without a prompt — the trusted case governor development happens in; the live targets (`~/.govd`, each agent's hook config, the LaunchAgent) and the control actions (`govctl stop`/`restart`, killing the daemon, `disableAllHooks`) still ask, so an in-repo session can't silently disable the running governor either |

## Personal rules

A rule you don't want to share lives in a **gitignored `*.local.py`** file in
`govd/policy/rules/`. The daemon discovers and loads it at startup exactly like a shared
rule; a fresh clone has none and runs only the shared set. To add one, copy any shared
rule to `<name>.local.py` — the relative imports are identical — and restart. `govctl
status` lists it; `govctl test` skips its samples where it isn't loaded.

This maintainer keeps two as personal: `prefer_graphite` (steers `git`/`gh` workflow
commands to Graphite `gt`, blocks merges, inert outside Graphite repos) and
`plan_format` (holds every agent plan to a fixed plain-language shape). Being
gitignored, they don't reach the shared repo — a teammate who wants them writes
their own.

## Adding a rule

Drop a file in `govd/policy/rules/` subclassing `Rule` with `applies(event)` and
`evaluate(event, ctx)` (return a `Decision` or `None`), register it in
`govd/policy/rules/__init__.py`, and `bin/govctl restart` — itself a governed action, so an
agent running it prompts you; approve it or run it from your own terminal. `evaluate` may use
`ctx.locks` for machine-wide shared state. Widen the matcher in the relevant
`install/*.json` if the rule needs a tool the adapters don't currently forward.

## Prerequisites

- **macOS.** The daemon is supervised by `launchctl` and there is no systemd unit yet.
  Everything else — adapters, syncers, `govctl` — is platform-neutral.
- **Python 3.8+, stdlib only.** Nothing to install: no dependencies, no build step, no
  virtualenv. `bin/govctl` runs under whatever `python3` resolves to.
- **Optional:** Graphite (`gt`), if you adopt the Graphite-oriented personal skills or
  the `prefer_graphite` personal rule. None of the shared rules or skills require it.

## First run

Clone the repo wherever you keep your tools, then, from inside it:

```bash
bin/govctl hooks-sync         # wire the adapters into every agent's hook config
bin/govctl skills-sync        # publish the skill library to every agent
bin/govctl instructions-sync  # splice standing instructions into each agent's context
bin/govctl install-agent      # LaunchAgent: start govd at login, restart if it dies
bin/govctl status             # verify it's running
bin/govctl test               # self-check the rules — expect all PASS
```

Nothing needs hand-editing for your machine. `install/*.json` ships
`{python} {governor_root}/adapters/<agent>.py` rather than a literal path, and
`hooks-sync` resolves both against the interpreter running it and this checkout's own
location, so the repo works from wherever you cloned it.

Then make it yours — the personal half of your instructions is gitignored, so start
from the template:

```bash
cp examples/about-me.local.md instructions/about-me.local.md
$EDITOR instructions/about-me.local.md && bin/govctl instructions-sync
```

[`examples/`](examples/README.md) also holds a skill template and shows how to add a
personal or shared skill and rule, with copy-and-edit steps for each.

> **The checkout location is load-bearing.** Each agent's hook config stores the
> absolute path to this repo, and `adapters/cursor.py` imports `instrsync` from it at
> every session start. If you move or rename the clone, re-run `bin/govctl hooks-sync`.
> Until you do, the adapters fail open and your agents run ungoverned —
> `bin/govctl hooks-list` reports `MISSING` whenever the installed command no longer
> matches this checkout.

## Install & wire up

`hooks-sync` merges the governor's hook entries from `install/*.json` into each
agent's live hook config idempotently — only govd's own entries are touched, and
every other key and every hook you added is left in place:

| Agent       | File it writes                                                                    |
| ----------- | -------------------------------------------------------------------------------- |
| Claude Code | `~/.claude/settings.json` — its `ConfigChange` hook lets govd block a settings edit that removes the hook or sets `disableAllHooks`; its `Stop` hook lets a Stop-gating rule (like the personal `plan_format`) hold a turn open until a `.context/plans/` plan conforms |
| Codex       | `~/.codex/hooks.json` (`$CODEX_HOME` respected) — including the `Stop` hook a rule like `plan_format` uses |
| Cursor      | `~/.cursor/hooks.json` — its `sessionStart` hook is also how [standing instructions](#instrsync--governing-instructions) reach Cursor, which has no user-level rules file |

```bash
bin/govctl hooks-list                          # which agents are wired
bin/govctl hooks-sync --dry-run                # show what would change, write nothing
bin/govctl hooks-sync --agents claude_code     # one agent
```

Writing an agent's hook config is a governed action, so an agent running `hooks-sync`
prompts you (`protect_governor`); approve it or run it from your own terminal.

## Operating the daemon

```bash
bin/govctl status       # running? which rules? reaper totals
bin/govctl tail 40      # last 40 governed actions (and reaped processes)
bin/govctl reap --dry-run  # list orphaned MCP servers without stopping them
bin/govctl mcp-cost     # startup tokens each MCP server adds (headless Claude runs)
bin/govctl test         # sample evaluations, PASS/FAIL
bin/govctl restart
bin/govctl uninstall-agent
```

### Orphaned MCP servers

An agent starts its stdio MCP servers as child processes, and a session that ends
without shutting them down leaves them running, adopted by launchd. Enough of them
fill memory and swap. The reaper is **opt-in**: list the servers that leak on your
machine in a gitignored `govd/config.local.json` and restart the daemon.

```json
{ "reap_patterns": ["mongodb-mcp-server"] }
```

Every 5 minutes the daemon then stops any process that matches a pattern, has launchd
(pid 1) as its parent, and is older than 2 minutes, together with its child processes. A live session's servers always have that session
as their parent, so they are never touched. Each stop is written to the audit log
(`REAP` in `govctl tail`); `govctl status` shows the totals and `govctl reap` runs a
scan on demand.

| `config.local.json` key | Environment override | Default  | Meaning                                                        |
| ----------------------- | -------------------- | -------- | -------------------------------------------------------------- |
| `reap_patterns`         | `GOVD_REAP_PATTERNS` (comma-separated) | none: off | substrings matched against the command line                |
| `reap_interval_seconds` | `GOVD_REAP_INTERVAL` | `300`    | seconds between scans; `0` disables                            |
| `reap_grace_seconds`    | `GOVD_REAP_GRACE`    | `120`    | minimum process age, in seconds, before it can be reaped       |

## Fail-open by design — never silent, never loosening

If the daemon is unreachable, every adapter allows the action within ~2s, so a crashed
daemon never bricks your agents. It is never silent about it: each adapter appends to
`~/.govd/adapter-errors.log`, and on Claude Code the transcript shows a warning that
the action ran ungoverned. This suits guidance-style policy. For a hard security gate,
raise `dangerous_bash` to fail-closed at the config layer (Cursor: `"failClosed": true`)
and constrain the agent's own sandbox.

govd never _loosens_ an agent's own permissions either. When no rule objects, the
Claude Code adapter prints nothing, so Claude Code's own rules, modes, and prompts
still apply — an explicit hook `allow` would skip that prompt. And the
`protect_governor` rule keeps the governor itself off-limits without a human: stopping
or killing the daemon, editing the adapters or rules, repointing `~/.govd/port`, or
touching an agent's hook config prompts for approval, and a live settings change that
removes the govd hook or sets `disableAllHooks` is blocked from taking effect. The one
carve-out is deliberate: a session whose cwd is inside this repo may edit the repo's own
source (`adapters/`, `govd/`, `bin/`, `install/`) without a prompt, because that is where
governor development happens — but the running governor stays gated even there, so
restarting the daemon, editing `~/.govd` or a live hook config, or `disableAllHooks` still
asks. The signal is the session's cwd, which fails safe: an unknown cwd is treated as
outside the repo and gated, so the worst a wrong guess does is add a prompt.

## Per-agent limitations

- **Codex** honors `deny` on `PreToolUse`/`PermissionRequest` but **not** `ask`, and
  fails open on a hook crash/timeout. `govd` never auto-approves on Codex — it only
  blocks — so your normal approval prompts still fire, and an `ask` that Codex cannot
  put to you is enforced as `deny`.
- **Cursor** post-edit events are observation-only, so `no_narrative_comments` shows
  as guidance there rather than a hard block, and `protect_governor` can only guard the
  shell side on Cursor, not file edits. Claude Code enforces both fully. Cursor's hook
  docs don't say whether a hook `allow` skips Cursor's own approval prompt, and an
  empty reply is fail-open there anyway, so the Cursor adapter still returns an
  explicit `allow`.
- **The `plan_format` personal rule, when installed, is enforced on Claude Code and Codex, not Cursor.** Claude Code's
  plan-mode proposals are gated at `ExitPlanMode` (denied until they conform); plans
  written straight to `.context/plans/` — Codex via `apply_patch`, or any `Write` —
  are gated at the `Stop` hook (top-level `{"decision":"block"}`, which Claude Code
  and Codex both support). Cursor exposes neither surface here, so the daemon records
  the `.context/plans/` files Cursor writes but nothing checks them. Note that both
  the `ExitPlanMode` matcher and the `Stop` hook are read at session start, so a
  session already running when they were wired won't enforce until it restarts.
- New/changing hook surfaces: re-check each vendor's hook docs when upgrading.

---

# skillsync — governing skills

The daemon governs _actions_. `skillsync` handles the other half — the skills you
invoke regularly — from the same repo. Author a skill once under `skills/<name>/` and
materialize it into all three agents. All three consume the same `<name>/SKILL.md`
directory layout, so the "transform" is frontmatter normalization + placement +
registration, not reformatting.

## Why one library

- **One source of truth per skill.** Edit `skills/<name>/`, sync, done — no drift
  between what Claude Code, Codex, and Cursor each run.
- **Per-agent shaping without forks.** The same canonical skill emits a Claude-Code
  copy with richer frontmatter and a Cursor/Codex copy trimmed to what each supports,
  from one file.
- **Generated, identifiable copies.** Every emitted skill carries a `.skillsync`
  marker, so an agent's copy is never confused with a hand-authored one.

## Shared skills

These ship with the repo. Two more — `create-pr` and `orchestrate` — are **personal**
on this maintainer's machine; see [Personal skills](#personal-skills).

| Skill                       | What it does                                                                                                                                                                                         | Invocation                                        |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| `triage-pr-review-comments` | Triage unresolved review comments across a PR or stack (bot comments by default): fix valid issues on the right branch, reply to bot false positives, draft human replies for approval, then submit. | slash-only (`disable-model-invocation`)           |
| `triage-merge-conflicts`    | Restack a branch or Graphite stack onto the latest trunk and resolve conflicts up the stack, gated on a mandatory lint/format pass before pushing so restack-reordered imports don't fail CI post-merge. | "resolve merge conflicts", "restack this", "rebase onto main" |

## Personal skills

A skill you don't want to share lives in a **gitignored `skills/<name>.local/`** dir. It
syncs under the bare `<name>`, so you still invoke it as `/<name>`, and a fresh clone has
none. To add one, copy any skill dir to `<name>.local/` and run `skills-sync`; `skills-list`
tags it `(personal)`. This maintainer keeps `create-pr` (Graphite PR creation) and
`orchestrate` (plan-and-delegate) personal — being gitignored, they don't reach the
shared repo.

## How a skill is materialized

For each target agent, `skillsync emit`:

1. **Filters frontmatter** to the keys that agent understands; everything else is
   dropped so it never leaks in as literal YAML text. Claude Code keeps a superset
   (`name`, `description`, `disable-model-invocation`, `allowed-tools`,
   `argument-hint`, `user-invocable`, `license`, `version`); Codex and Cursor keep the
   minimal `name`, `description`, `disable-model-invocation`.
2. **Splices in per-agent mechanics** — if `agents/<agent>.md` exists, its body is
   appended after the shared body (used for genuinely agent-specific mechanics, e.g.
   `orchestrate`'s delegation primitive, only verified on Claude Code).
3. **Places the copy** in that agent's skills dir:
   `~/.claude/skills/<name>/`, `~/.codex/skills/<name>/`, or
   `~/.cursor/skills-cursor/<name>/`.
4. **Copies `references/`** verbatim next to `SKILL.md`, if present.
5. **Drops a `.skillsync` marker** (`skill`, `source`, `synced_at`) so the copy is
   identifiable as generated. On Cursor it also records the skill in
   `.sync-manifest.json` so Cursor doesn't treat it as stray.

Writes are atomic (temp file + `os.replace`).

## Authoring a skill

A canonical skill is a directory under `skills/`:

```
skills/<name>/SKILL.md            frontmatter + agent-neutral body (required)
skills/<name>/agents/<agent>.md   mechanics spliced in for that agent (optional)
skills/<name>/references/…         copied verbatim next to SKILL.md (optional)
```

Frontmatter is plain `key: value` scalars. One control key is consumed by skillsync
and never emitted: `agents: [claude_code, codex, cursor]` restricts which agents
receive the skill (default: all).

**The emitted copies are generated.** Edit the canonical `skills/<name>/` and re-run
`skills-sync`; hand-edits to an agent's copy are overwritten on the next sync.

## Syncing

```bash
bin/govctl skills-list                              # canonical skills and where each emits
bin/govctl skills-sync                              # write them into every agent's skills dir
bin/govctl skills-sync --dry-run                    # show what would change, write nothing
bin/govctl skills-sync --only triage-merge-conflicts   # one skill
bin/govctl skills-sync --agents claude_code,codex   # subset of agents
```

---

# instrsync — governing instructions

The daemon governs _actions_ and `skillsync` governs _skills_. `instrsync` covers the
third thing every agent needs from you: **standing instructions** — the short, always-on
context you would otherwise re-type into every session, such as your pronouns. Author them
once under `instructions/` and every agent receives them at **user scope**, so they apply
in every project and every worktree. (A per-repo `CLAUDE.local.md` or `AGENTS.md` would
not: a tool like Conductor spins up a fresh worktree per workspace, and a gitignored file
only exists where you created it.)

## Where each agent reads them

| Agent       | Delivery                                                                                                                                                                       |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Claude Code | a managed block in `~/.claude/CLAUDE.md` — user-scope memory, loaded at the start of every session in every project                                                           |
| Codex       | a managed block in `~/.codex/AGENTS.md` (`$CODEX_HOME` respected) — the global layer Codex loads before any project `AGENTS.md`                                                |
| Cursor      | Cursor has no user-level rules file (User Rules live only in its settings UI), so `adapters/cursor.py` returns the rendered instructions as `additional_context` from the `sessionStart` hook — live, nothing to sync |

The managed block is delimited by `<!-- governor:instructions:begin -->` and
`<!-- governor:instructions:end -->`. Everything outside it in `CLAUDE.md` / `AGENTS.md`
is yours and is never touched; re-running the sync replaces only the block, and removes it
if nothing targets that agent any more. Claude Code strips HTML comments before injecting
`CLAUDE.md`, so the markers cost no context there.

## Authoring

One markdown file per topic under `instructions/`, concatenated in filename order. Two
kinds of file live there:

- **`<topic>.md`** is committed — shared with anyone who clones this repo.
- **`<topic>.local.md`** is gitignored — for personal preferences (your pronouns, your
  name) that should reach every agent on _your_ machine but never land in a repo you
  might one day share. Same format, same delivery; only git treats it differently.

Write instructions concretely — they are delivered as context, not enforced
configuration, so "use they/them pronouns when referring to me, including in commit
messages" is followed far more consistently than "I use they/them". Optional frontmatter
holds one control key, consumed and never emitted. Copy
[`examples/about-me.local.md`](examples/about-me.local.md) to
`instructions/about-me.local.md` and fill in your own:

```markdown
---
agents: [claude_code, codex]   # restrict which agents receive this file (default: all)
---

## About me

- Use <your pronouns> when referring to me, including in commit messages, PR
  descriptions, and code comments.
- My name is <your name>.
```

Keep the whole set short: it is loaded into every session, and Codex caps the combined
size of all `AGENTS.md` files at 32 KiB by default.

## Syncing

```bash
bin/govctl instructions-list                     # canonical files and which agents get each
bin/govctl instructions-show --agent cursor      # exactly what one agent will see
bin/govctl instructions-sync                     # splice into ~/.claude/CLAUDE.md and ~/.codex/AGENTS.md
bin/govctl instructions-sync --dry-run           # report what would change, write nothing
```

Cursor needs no sync step — its adapter reads the canonical files at each session start —
but `instructions-sync` checks that `~/.cursor/hooks.json` carries the `sessionStart` hook
and says so if it doesn't. `bin/govctl test` also runs the adapter against a synthetic
`sessionStart` and checks the injected text. To confirm the instructions reached a session,
run `/context` in Claude Code and look for `~/.claude/CLAUDE.md` under **Memory files**, or
simply ask the agent which pronouns to use for you.

---

# profilesync — governing MCP servers

Every MCP server in an agent's everyday config loads into every session: its tool names
cost context before you type anything, a stdio server starts a process per session, and
every session can reach every database. `profilesync` moves servers into **profiles**
— named bundles of servers, each with a brief — so a normal session starts with none of
them and reaches one only when it needs it.

One profile runs two ways:

- **As a worker (Claude Code).** Each profile becomes a Claude Code subagent in `~/.claude/agents/`.
  Its servers are defined inline, so they connect when the subagent starts and
  disconnect when it finishes; the main session never loads them. The main session
  delegates a question, the worker reads the raw results, and only its answer comes
  back — which keeps large query results out of your conversation too.
- **As a session (Claude Code and Codex).** `bin/govctl profile <name>` starts Claude
  with only that profile's servers (`--strict-mcp-config`, which also leaves out
  claude.ai connectors) and the profile's brief appended to the system prompt.
  `bin/govctl profile <name> --agent codex` runs `codex -p <name>`, layering the synced
  `~/.codex/<name>.config.toml` (the profile's servers and brief) over your base config.
  Use a session for work that is mostly MCP, where many back-and-forth delegations
  would cost more than they save.

Codex has no worker mode yet: Codex 0.155 starts a custom agent without the
`mcp_servers` its file declares, so `profilesync` writes only the session profile there.
Codex also defers MCP tools behind a tool search, so each Codex brief starts with a line
telling the model to search before it concludes a tool is missing.

## Authoring

Server definitions live in `profiles/servers.local.json`, the registry, in `.mcp.json`
form. Two extra keys are governor-only and never emitted: `write_tools`, the tools a
`readonly: true` profile blocks, and `writable`. The registry holds connection strings
and tokens, so it is gitignored. A profile is `profiles/<name>.local.md` (or a shared
`<name>.md` with no credentials):

```markdown
---
name: staging-investigator
description: Read-only investigation of STAGING data. The main session reads this to decide when to delegate.
servers: [mongodb-staging, internal-api-staging]
readonly: true
model: sonnet          # optional; omit to inherit
tools: [Read, Grep]    # optional allowlist; omit to inherit the main session's tools
---
The worker's brief: what it's for, how narrowly to query, and what to report back.
```

A server that every session should have — an issue tracker you use mid-task, say —
sets `"everyday": true` in the registry instead of belonging to a profile. A sync writes
it into each agent's everyday config (`~/.claude.json`, `~/.codex/config.toml`), so it
is still authored once. Codex reads header values from environment variables, which
only `govctl profile` sets, so an everyday server can't use keychain headers there.

**claude.ai connectors** load into every Claude Code session too, and they can't be
scoped by any local file. To leave them on in claude.ai chat but out of Claude Code, set
`ENABLE_CLAUDEAI_MCP_SERVERS=false` in the `env` block of `~/.claude/settings.json`,
then add back the ones you use as registry servers pointing at the vendor's hosted MCP
URL (`claude mcp list` shows each connector's URL). OAuth sign-ins are per URL, so
each needs one sign-in in Claude Code.

Start from [`examples/profiles/`](examples/profiles/). For a database, prefer the
server's own read-only mode where it has one (`MDB_MCP_READ_ONLY=true` for
`mongodb-mcp-server`), with a read-only credential and `readonly: true` as further layers.

## Credentials in the keychain

A registry value can be a reference, `{"keychain": "<account>"}`, in place of the
secret. The secret is a generic password in your login keychain under the service
`governor-mcp`, and no generated file ever contains it:

- a stdio server whose `env` holds a reference is emitted as `govctl mcp-launch <server>`,
  which reads the secret, sets it in the environment, and replaces itself with the real
  server;
- an HTTP server whose `headers` hold a reference gets a Claude Code `headersHelper`
  (`govctl mcp-headers <server>`), and in Codex an `env_http_headers` variable that
  `govctl profile <name> --agent codex` fills in when it starts the session.

Write secrets inline while authoring, then move them:

```bash
bin/govctl secrets-import --dry-run   # which values would move
bin/govctl secrets-import             # store each in the keychain; the registry keeps references
bin/govctl profiles-sync
```

It moves every header value and every `env` value whose name looks like a credential
(`*STRING*`, `*TOKEN*`, `*KEY*`, `*SECRET*`, `*PASSW*`, `*AUTH*`, `*URI*`), writing
through `security -i` on stdin so no secret appears on a command line. The keychain is
not a wall against an agent determined to read it — any process running as you can call
`security` — so the shared `secret_reads` rule asks before an agent's shell prints a
keychain password, dumps the keychain, runs `govctl mcp-headers`, or touches a
`*.bak-govd-*` config backup.

## Syncing

```bash
bin/govctl profiles-list               # profiles, their servers, and the registry
bin/govctl profiles-sync --dry-run     # what would be written and removed
bin/govctl profiles-sync               # write the subagents; retire servers from everyday config
bin/govctl profile staging-investigator  # a Claude session with only that profile's servers
```

A sync writes one subagent per profile (mode `0600`, since it carries the server
definitions), removes subagents it generated for profiles that no longer exist, and
never overwrites an agent file it didn't generate. It then removes every registry
server — and every name in the registry's `retire` list — from `~/.claude.json`, leaving
servers the registry doesn't know about alone. `profiles-sync` asks for approval like
`hooks-sync`, and `protect_governor` treats each generated subagent as live governance.

OAuth sign-ins are stored per server URL, so signing in once — in `/mcp` inside a
`govctl profile` session — covers the subagent too. OAuth sign-in for a server that
exists only in a Codex profile is untested; `codex mcp login` reads the base config only.

For Codex the sync writes `~/.codex/<name>.config.toml` per profile and removes the same
servers' `[mcp_servers.*]` tables (and their sub-tables) from `~/.codex/config.toml`,
leaving every other line of that file untouched.

## License

MIT — see [LICENSE](LICENSE).
