---
name: triage-merge-conflicts
description: Get a branch or Graphite stack back on top of the latest trunk — pull trunk, restack/rebase, resolve every conflict up the stack, and pass a mandatory lint/format gate before pushing so restack-reordered imports don't fail CI post-merge; invoking the skill authorizes force-pushing the restacked branch or stack to its own remote without a separate confirmation. Use when the user says "resolve merge conflicts", "rebase onto main", "restack this", "my branch has conflicts", "get latest and fix conflicts", or when a rebase/restack stops on a conflict.
---

# Triage Merge Conflicts

Bring a branch (or a whole Graphite stack) up to date with trunk and resolve the conflicts, then **prove lint and the formatter are clean before you push.** Restacking commonly re-emits a hand-resolved import block in the wrong order; the commit looks fine locally but CI's lint step fails after merge. The lint/format gate below exists to catch that before it ships.

Graphite (`gt`) owns branch topology and stacks here — drive the restack through it, not raw git. A plain-git fallback is at the end for repos without Graphite.

**Authorization:** invoking this skill *is* the user's go-ahead to force-push the restacked branch or stack — your own feature branch(es) — to its remote once the lint/format gate passes; do it without stopping to confirm. The force is with-lease, so it won't clobber a teammate's newer commit. The one thing it does not authorize is rewriting shared history (trunk, or a branch someone else is on) — never do that without an explicit request.

## Step 0 — Preflight

This skill assumes Graphite is set up for the repo (the standard here). Confirm where you are and what's stacked:

```bash
git rev-parse --abbrev-ref HEAD   # current branch
gt log short --stack               # the stack you're about to restack
git status                          # must be clean; stash/commit WIP before restacking
```

Restacking rewrites history on your branches. Never start one over uncommitted work — stash or commit first.

## Step 1 — Pull trunk and try a clean restack

`gt get` pulls the latest trunk and restacks your branch(es) onto it in one step:

```bash
gt get
```

- **Clean restack (no conflicts):** you're back on top of trunk with nothing to resolve. No hand-edits happened, so no imports moved — skip straight to **Step 4 (Submit)**.
- **Conflicts:** the restack halts on the first one. Continue to Step 2.

If a `gt get` isn't wanted (e.g. you already fetched), `gt restack` restacks onto the trunk you have without pulling.

## Step 2 — Resolve conflicts up the stack

A stack restacks bottom branch first and stops at each branch that conflicts. Work the loop until the whole stack is clean:

1. **Resolve** every conflicted file. Read the surrounding code — don't just keep both sides. When the conflict is in an import block, resolve it to a plausible order; the formatter in Step 3 will normalize it, but only if you stage the resolution first.
2. **Stage** the resolved files: `git add <files>` (or `git add -A`).
3. **Continue** the restack: `gt continue`.
4. Graphite moves to the next branch up the stack. If it stops on another conflict, repeat from 1. **Repeat until fully restacked** (`gt continue` reports the stack is restacked and returns you to a clean prompt).

Don't `git rebase --continue` inside a Graphite stack — `gt continue` is what keeps the stack metadata correct.

## Step 3 — Exit condition: lint & format must pass before you push

**Do not submit until the repo's linter and formatter both report clean with no further changes.** This is the gate that stops import-order thrash from reaching CI.

1. Run the same checks CI runs. Find the exact commands in `package.json` scripts, the pre-commit config, or the CI workflow rather than guessing — commonly some of:

   ```bash
   yarn lint          # or: npm run lint / pnpm lint / eslint
   yarn prettier --check .    # or the repo's format-check script
   ```

   Scope to the changed files where the tooling supports it (faster, same signal).
2. If the formatter **rewrites** anything (or `--check` reports a file), let it fix in place (`yarn prettier --write <files>` / the repo's format script), then **fold the fix into the commit that owns it**: `git add <files>` on that branch, `gt modify` (amends and restacks upstack automatically). A reorder can span several branches — fix each on its own branch.
3. **Re-run lint and format-check until both pass with zero remaining changes.** Only a clean pass clears the gate.

Note: pre-commit hooks don't reliably fire on `gt continue`/`git rebase --continue`, which is exactly why a hand-resolved import block can slip through — run the checks explicitly here, don't assume a hook already did.

## Step 4 — Submit

Push the restacked branch(es) to the remote. Force is required because the restack rewrote history — this rewrites **your own** feature branch/stack, which is normal, but it is an outward push:

- **Graphite stack:** `gt submit --stack --no-interactive` (the shorthand is `gt ss`).
- **Single tracked branch:** `gt submit --no-interactive`.

`gt submit` force-pushes with lease under the hood, so it won't clobber a teammate's newer commit — if the push is rejected, someone else moved the branch: re-run Step 1 to fold their work in before submitting again.

Invoking this skill authorizes this push (see **Authorization** above), so submit without a separate confirmation once the gate passes, even for a bare "resolve my conflicts" — it updates the open PR(s). The authorization covers only your own branch/stack; never force-push shared history.

## Plain-git fallback (no Graphite)

For a repo not on Graphite, the same shape with raw git:

1. `git fetch origin && git rebase origin/main`
2. Resolve conflicts, `git add <files>`, `git rebase --continue`. Repeat until the rebase finishes.
3. **Run the lint/format gate (Step 3)** and fold fixes in (`git add` + `git commit --amend`, or a fixup commit) until clean.
4. `git push --force-with-lease` (authorized by invoking the skill, per Step 4).

## Rules

- **Clean working tree before restacking.** Stash or commit WIP first — a restack over uncommitted changes loses them or refuses to run.
- **`gt continue`, not `git rebase --continue`, inside a Graphite stack.** Mixing them desyncs stack metadata.
- **Always `git add` before `gt modify`/`gt continue`.** They only pick up staged changes; an unstaged resolution silently doesn't make it into the commit.
- **The lint/format gate is not optional.** A locally-fine commit with reordered imports fails CI after merge — that's the whole reason this skill exists.
- **Force-push only your own branch/stack.** Never rewrite shared history (trunk, a branch someone else is on) without the user explicitly asking.
