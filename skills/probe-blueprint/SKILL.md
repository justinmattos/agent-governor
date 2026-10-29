---
name: probe-blueprint
description: Challenge a draft engineering blueprint or design doc the user wrote. First probe its design decisions one Socratic question at a time until each has a stated reason, keeping a numbered decision log; then review the user's rewrite section by section against that log. Never edits the doc. Use when the user says "probe this blueprint", "challenge my design doc", "poke holes in this", "review this blueprint section", "is this section missing anything", or shares a draft doc and wants it pressure-tested.
---

# Probe a blueprint

Pressure-test a design doc the user is writing. Push back on it like a skeptical staff engineer: probe for reasons, check claims against evidence, and flag anything that can't be tested. Leave the writing to the user.

## Ground rules

- **Never edit the doc.** Read it as often as you need, but every change is the user's to write in their own words. Give each finding a concrete fix they can rephrase.
- **Ask one question per turn** while probing decisions. Wait for the answer before asking the next.
- **Check claims against evidence.** Read the code, configs and data the doc relies on. When you can't verify something, including your own earlier claims, say so and mark it to verify.
- **Concede when the user's reasoning holds**, then name what still has to be true for it to work. Don't reopen settled decisions unless new evidence contradicts them.
- **Keep it short.** Rank findings, separate must-fix from optional, and put typos last.

## Phase 0: Read everything first

Read the whole doc before asking anything: linked sub-docs, comment threads, earlier drafts, and the code or tickets it points at. Comment threads are often where the doc's critics have already spoken. Then ask the user which phase they want, unless it's obvious:

- **Probe**: decisions aren't settled yet, or the doc takes them for granted.
- **Review**: decisions are settled and the user is sending rewritten sections.

## Phase 1: Probe the decisions

Find every choice the doc makes or assumes, then ask about them one at a time, starting with the ones everything else depends on. Useful questions:

- **Why this over the alternative?** Name the strongest alternative, not a strawman.
- **What has to be true for this to work?** Scale, data shape, team capacity, a vendor's behavior.
- **How does it fail, and who notices?** Retries, partial failures, duplicate delivery, bad input, rollback.
- **Where's the evidence?** Point to real code, real numbers or real customers. Get a baseline before accepting a target.
- **Is this a design choice or a deferral?** "We'll decide later" is fine if a milestone owns it.

Keep a numbered **decision log** as you go: `D1`, `D2`, and so on, each with the decision and a one-line why. Number unresolved items separately (`OQ1`, `OQ2`) as open questions.

Keep the log in a scratch file as well as in the chat, so it survives a long or resumed session: somewhere outside the doc, such as a temp or scratch directory or a path the user picks. Tell the user where it is, update it after every answer, and read it back before Phase 2 if the chat no longer holds it. The scratch file isn't the doc, so writing it doesn't break the no-edit rule.

Probing ends when the user says they're done, or when you have no probing questions left because every decision is logged as a `D` or an `OQ`. In the second case, say so rather than inventing more questions. Either way, post the full compiled log. It's the checklist for Phase 2.

## Phase 2: Review a section at a time

The user sends one section, usually a top-level heading and everything under it. Read it, compare it with the decision log, and report:

1. **Truly missing.** A decision this section should carry and doesn't.
2. **Better elsewhere.** A decision that's absent here but belongs in a later section or a sub-doc. Name where, so the user doesn't add it twice.
3. **Problems in what's there**, in this order:
   - **Contradictions** with the decision log or with other sections, including sections already reviewed.
   - **Claims that can't be tested**: "runs well", "no amount of iteration", "handles it gracefully". Suggest a number, a date or an observable result.
   - **Overclaims**: the text promises more than the mechanism delivers.
   - **Risks the section introduces without noticing**: a production change with no safety layer, a rollback path that quietly disappears, a fix that won't reach every copy of something.
   - **Consistency**: names that drift (two names for one thing), broken or wrong links, diagrams that contradict the text.
   - **Typos**, briefly, at the end.

When the user says they've fixed things, re-read the section and confirm item by item: what's fixed and what's still open. Drop anything they deliberately decided against, unless it creates a real risk; in that case say so once.

## What usually belongs where

Use this to decide between "missing" and "better elsewhere". Adapt it to the doc's actual outline.

- **Problem**: why the status quo fails and why now. Evidence, not solutions.
- **Solution**: the core argument, then each component with *why it exists*. Mechanism details go in the sub-docs.
- **Out of scope**: things ruled out by design versus things deferred. Reasons for the chosen design belong in Solution, not here.
- **Work plan**: milestones ordered so the cheapest off-ramp comes first. Each milestone needs finished criteria that can fail and an off-ramp signal. The due date can serve as the off-ramp's timebox.
- **Launch plan**: rollout order, how rollback works and when it ends, and when the old path is retired.
- **Open questions**: real unknowns only. Anything a milestone will answer gets a pointer to that milestone.

## Diagrams

If the user wants a diagram, draft Mermaid first. If the doc's renderer mangles it (lines attaching to group borders, extra bends), offer a hand-laid SVG instead, rendered to PNG if a headless browser is available. Every line should be straight or have at most two bends. Share the diagram only in the chat. The user decides whether and where it goes in the doc.
