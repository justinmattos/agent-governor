---
name: example-skill
description: A template to copy when authoring a new skill. Describe precisely when the skill should fire — this text is the only thing an agent sees when deciding whether to invoke it, so name the trigger phrases a user would actually say.
agents: [claude_code, codex, cursor]
---

# Example Skill

Copy this directory to `skills/<your-skill-name>/` to publish a new skill to every
agent. Anything under `skills/` with a `SKILL.md` is synced; this copy lives under
`examples/` so it is not.

## Frontmatter

`name` and `description` are the real contract. `agents:` is a control key consumed by
the syncer and never written to the output — use it to restrict which agents receive
the skill, and omit it to reach all three. Every other key is passed through to the
agents that accept it.

## Body

Write the body agent-neutral: steps, checks, and the conditions to stop on. Say what
authorization invoking the skill implies, if any, so the agent does not stop to
re-confirm something the user already greenlit by invoking it.

## Step 1 — a worked step

Number the steps and make each one checkable. State the failure mode explicitly rather
than leaving the agent to infer it.

## Optional extras

- `agents/<agent>.md` — per-agent mechanics appended to the body for that agent only,
  for the cases where one agent needs different tool names or invocation details.
- `references/` — longer supporting docs copied verbatim next to the skill. Put
  anything an agent needs only sometimes here, so the skill body stays short.
