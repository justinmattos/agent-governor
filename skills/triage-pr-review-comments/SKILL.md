---
name: triage-pr-review-comments
description: Triage unresolved review comments across a PR or a whole stack. Defaults to review-bot comments only (checking in only if a PR or stack has nothing but human comments), fetches unresolved threads for every PR, analyzes them in parallel, fixes valid issues on the correct branch, replies to bot false positives, drafts replies to human reviewers for approval before posting, and submits. Use when the user asks to review, triage, or address bot and/or human reviewer comments on a PR or stack.
disable-model-invocation: true
---

# Triage PR Review Comments

Systematically process every unresolved review comment on a PR (or across a stack): analyze each one, fix real issues, dismiss review-bot false positives, draft replies to human reviewers for approval, and submit. **Fixing code, replying to reviewers, and resolving threads are outward-facing — human replies are always drafted and approved before posting (see Step 4).**

## Prerequisites

- `gh` CLI authenticated with access to the repo.
- If the repo uses Graphite for stacks, `gt` configured (directly or via this agent's Graphite integration).
- The GraphQL queries and reply/resolve snippets are in [`references/github-graphql.md`](references/github-graphql.md).

## Inputs

No arguments required.

- **Default:** run from a branch in the stack. Enumerate the stack — `gt log short --stack` in a Graphite repo (the `--stack` keeps it to this stack's branches, not every branch you have), otherwise ask the user or treat it as the single current PR — then resolve each branch to its PR with `gh pr view <branch> --json number,title,headRefName,url`.
- **Explicit list:** if the user pastes PRs, use those and resolve each to its branch with `gh pr view <n> --json number,title,headRefName`.

Either way you end with each PR's number, title, head branch, and bottom-to-top order. Step 4 checks out branches by name.

## Workflow

### Step 0 — Scope

**Default to bot-only** — unresolved review-bot comments (Cursor Bugbot, CodeRabbit, etc.). Don't ask up front; just proceed on bot comments unless the user already asked to include human reviewers. Deferring human comments is safe: they're never auto-dismissed or auto-resolved anyway.

Check in **after fetching** (Step 1), not before, in these cases:

- A PR or the stack has **only human comments** and nothing for bot-only to act on — surface that and ask whether to triage the human comments too, so a bot-only run doesn't silently do nothing.
- The user explicitly asked to include human comments — then handle both from the start (Steps 3–4).

Also confirm: **re-trigger the review bot after submitting?** Many bots review automatically only on first publish and do **not** re-review on later pushes — those must be re-triggered manually (e.g. commenting the bot's trigger phrase). Default to yes when the run will push code fixes; skip it for a reply-only run. Record the answer for Step 5.

### Step 1 — Fetch comments for all PRs (parallel)

For each PR, fetch review threads with the GraphQL query in the reference. Keep only unresolved threads (`isResolved: false`) and split by the first comment's author:

- **Bot threads** — first comment authored by the review bot. Extract thread `id`, `body`, `path`, `line`, severity.
- **Human threads** (only if in scope) — any other first author. Extract `body`, `path`, `line`, `author.login`. Treat other automated authors (`github-actions`, `vercel`, …) as low priority; use judgment on whether they warrant a response.

Skip PRs with zero relevant unresolved comments.

### Step 2 — Confirm order

Process fixes bottom-to-top so a stack restacks cleanly. For a single PR this is trivial.

### Step 3 — Analyze all comments (parallel)

Analyze one PR's comments per worker (in parallel if this agent supports subagents; otherwise sequentially). Each reads the flagged source and traces every claim through the actual code — imports, call sites, endpoints — before judging.

**Bot comments** → a verdict: **VALID BUG**, **FALSE POSITIVE**, or **LOW-PRIORITY CLEANUP**. Review bots hallucinate bugs when run with limited context, so verify against the real code rather than trusting the claim. For valid bugs, include a concise fix.

**Human comments** → don't force a bug verdict; a reviewer may be asking, requesting, nitpicking, suggesting, or just remarking. For each:

- **Category:** `blocking-change` / `nit` / `question` / `suggestion` / `discussion` / `no-action`
- **Assessment:** whether the point is correct and what the code should do about it
- **Recommended action:** `fix` / `reply` / `fix-and-reply` / `flag` (subjective or architectural — needs the user)
- **Draft reply** (everything except `no-action`): concise and collaborative; if pushing back, explain and cite specific code; if it's a judgment call, say so and defer to the user.

### Step 4 — Process results bottom-up

**Bot comments (automatic):**

- False positives / low-priority cleanups → reply on the thread (reply snippet in the reference), 2–3 sentences citing the code that disproves the claim. Then resolve the thread (it posts immediately).
- Valid bugs → fix on the correct branch (see "Apply a fix"). **Resolve these threads only after the fix is actually pushed** (Step 5) — resolving on a local-only fix risks a submit failure leaving the thread resolved but the fix unpushed.

Only resolve bot threads. Never auto-resolve human threads.

**Human comments (draft, then confirm before posting):** Present every human comment as its own inline block — **not** a table (a table cell can't hold a readable diff). Give enough context to follow each thread without opening GitHub. Each block has four parts:

1. **Header** — `PR #<n> (<branch>) · <path>:<line> · <category> (<author>)`, where category is `blocking-change` / `nit` / `question` / `suggestion` / `discussion`.
2. **Inline diff** — a `diff` fenced block anchored on `path:line`, with a few lines of context. Include `+` lines only when the proposed step involves a code fix; for a `reply`-only or `flag` step, show just the flagged lines. If the thread is on an outdated line, quote the outdated code.
3. **Original comment** — the reviewer's comment verbatim, plus any prior back-and-forth on the thread.
4. **Proposed next step** — `fix` / `reply` / `fix-and-reply` / `flag`, with the draft reply and/or a one-line fix summary.

Example:

**PR #123** (`ab/eco-1234`) · `backend/src/pay.ts:42` · nit (alice)

```diff
   const total = items.reduce((a, i) => a + i.cost, 0)
-  return total
+  return Math.round(total * 100) / 100
```

**Original comment:** "This can return floating-point cents — round it."

**Proposed next step:** `fix-and-reply` — round to cents as above; reply "Good catch, rounding to cents."

Order the blocks bottom-to-top by stack position so they read in the order you'll apply them. Wait for approval, then execute only approved items: apply approved fixes, post approved replies (post the user's edit if they changed a draft), skip rejected ones, and leave threads they'll handle themselves untouched.

**Apply a fix:**

1. Checkout the PR's branch: `git checkout <branch>` (or `gt checkout <branch>` in a Graphite repo).
2. Read the file and apply the fix; stage with `git add <files>`.
3. Amend/commit on that branch: Graphite → `gt modify -m "<original message>"` (restacks upstack automatically); plain git → `git commit --amend` (or a new commit) as appropriate. Let hooks run.

### Step 5 — Submit

After all fixes are applied and confirmed: push the branch(es). Graphite → `gt submit --stack --no-interactive`; plain git → `git push` per branch. Only after the push succeeds, resolve the bot threads whose valid-bug fixes just landed. If the push fails, leave them unresolved so a re-run reprocesses them.

**Re-trigger the bot** (if opted in at Step 0): once the push succeeds, comment the bot's trigger phrase on each PR. Findings trickle in over minutes; to triage the new wave in the same session, wait for them to land, then re-run from Step 1. Otherwise tell the user the wave is running and they can re-invoke this skill when it finishes.

### Step 6 — Report

Present a summary (omit empty sections):

- **Valid bugs fixed** — PR · bug · severity · fix
- **Bot false positives dismissed** — PR · bug · why invalid
- **Human comments addressed** — PR · comment (author) · category · resolution (fixed / replied / flagged for you)

## Key patterns

- **Stacked-PR false positives:** code introduced in PR N and consumed in PR N+k is not dead code. Check upstack branches before flagging "unused" exports/hooks.
- **Mutation timing:** fire-and-forget mutations mean any toast/navigation that follows synchronously is premature — use success/error callbacks or await.
- **Shallow-copy pitfalls:** spreading an array copies references, not the objects inside; deep-copy one level when mutating cached objects.
- **Field-name mismatches:** clients and backends sometimes use different field shapes for the same data — verify the receiving endpoint's expected type before "fixing" a mismatch the reviewer flagged.
