---
name: moa-v2-decompose-plan
description: moa-v2 pipeline Step 2 — Decompose the brief into concrete tasks and measurable success criteria tagged blocking|major|minor. Unmeasurable criteria are rejected, not kept. Use when starting the planning step of a moa-v2 run.
---

# Decompose & Plan (moa-v2 Step 2)

Turn the brief (Step 1) into an executable plan and a measurable criteria list.

## Rules

- Produce a numbered task list in dependency order.
- For every task, define **measurable criteria**. A criterion is admissible only if a test/reviewer can decide VERIFIED / FAILED from observable artifact(s). If it cannot be proved, **reject it** — do not carry vague criteria forward.
- Tag every criterion `blocking | major | minor`:
  - `blocking` — must be VERIFIED for a PASS (e.g., core functionality promised to the user, any `security` framing).
  - `major` — important; must collectively reach 90% coverage.
  - `minor` — nice-to-have; not required for PASS.
- Keep a mapping: criterion → which module(s) and which test(s) will prove it.
- Assign a `criterion_id` like `C-01`.

## Output

Append to `02-brief.md` (or a `02-plan.md` sibling):

```
## Tasks
1. ...

## Criteria
| id | severity | criterion | proof (module + test) |
|----|----------|-----------|------------------------|
| C-001 | blocking | <measurable> | <module> / <test> |
```

Unmeasurable desires go to a `## Rejected (unmeasurable)` note, never into the criteria table.