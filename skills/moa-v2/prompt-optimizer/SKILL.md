---
name: moa-v2-prompt-optimizer
description: moa-v2 pipeline Step 1 — Optimize the user query into a structured brief with task_type and needs_frontend_synthesis tags, always preserving the original user text verbatim as a separate layer. Use when starting a moa-v2 run.
---

# Prompt Optimizer (moa-v2 Step 1)

Convert the user's request into an execution brief WITHOUT altering their words.

## Rules

- **Preserve the original user text verbatim.** Store it in its own section (`## Original Request`) in `02-brief.md`. Never paraphrase it away.
- Derive a `task_type`: `web | app | analysis | data | infra | mixed`.
- Set `needs_frontend_synthesis`: `true` if any part of the deliverable involves UI / frontend / visual work, else `false`.
- Implicit and explicit requirements are both candidates for criteria. Nothing the user says should silently disappear.
- State any assumptions you are making (auto-mode: proceed with the stated assumptions; do not block).

## Output

Write `02-brief.md` in `.moa-v2/traces/<run-id>/` with:

```
## Original User
<verbatim>

## Objective
<one line>

## Tags
task_type: <...>
needs_frontend_synthesis: <true|false>

## Assumptions
- <...>
```

Then hand off to Step 2 (decompose-plan).