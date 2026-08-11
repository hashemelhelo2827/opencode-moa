---
name: moa-v2-grill-me
description: moa-v2 pipeline Step 0 — relentless design-tree interview before prompt-optimizer. Runs by default (grill_me: true), capped at 6 rounds / 25 questions. Use when starting a moa-v2 run, or when the user says "grill me" / "stress-test this" / "interview me" / "challenge my plan".
---

# Grill Me (moa-v2 Step 0)

Run a relentless design-tree interview BEFORE prompt-optimizer. Runs by default on every moa-v2 invocation.

## What grill-me contributes

Grill improves requirement DISCOVERY. It is NOT evidence and is never required for PASS.
- `grill_me: false` skips the interactive Step 0 interview; it does NOT mean lower quality.
- `grill_me: true` does NOT guarantee coverage; Gate A (semantic coverage) remains the sole authority for requirement coverage.

## When to skip

Skip the interview ONLY when any of:
1. `MOA_V2_MEMORY.md → Workflow Authority → grill_me: false` (persistent). The effective value is recorded per-run in `00-flow.md`.
2. Workflow authority is on AND the user explicitly removed Step 0 in the flow menu.
3. The user says "skip the interview" this run.

Note: `grill_me: false` does NOT make a run fully automated — project-flow auto-detect (the "Use it?" ask) still applies when `<project>/.moa-v2/workflow/flow.json` exists.

## Protocol

1. **Design tree** — model the request as a tree: every decision branches into the decisions hanging off it.
2. **Rounds on the frontier** — the frontier = every decision whose prerequisites are settled. In one round, ask the WHOLE frontier: number each question and give your recommended answer.
3. **Exact question format:**

   ❓ **Qn** - **<question title>**: <question body, possibly multiple paragraphs, including multiple choices>

   ➡️ <your recommended answer>

4. **Recompute** — after answers, settled decisions push the frontier outward. A question depending on another still-open question in this round belongs to a LATER round, not this one.
5. **Facts are the agent's job, never the user's** — when a frontier question needs an environment fact (filesystem, tools, existing code), dispatch a sub-agent to find it; never ask the user for anything findable. Do not block unrelated questions on it — only questions downstream of the fact wait. The DECISIONS are the user's — put each to them and wait.
   - Before EVERY fact-finding dispatch: increment `grill_fact_calls_today` in `MOA_V2_MEMORY.md` and log the dispatch. Telemetry only (delegate agents are quota-unlimited via Zen); never a hard cap.
   - Record the dispatch in the Fact Evidence table (see Output) BEFORE interpreting it: `FACT → USER DECISION`, never `AGENT CLAIM → USER DECISION`.
6. **Bound (hard cap)** — stop when the first of these hits: 6 rounds completed, OR 25 total questions asked. On reaching either cap, proceed with remaining risks logged as open items in `01-grilling.md`. Never run unbounded.
7. **Terminate** when the frontier is empty OR the cap is reached. Do NOT proceed until the user explicitly confirms shared understanding (or the cap forces continuation with open items).
8. If the user cuts the session short, record remaining risks as open items — never silently assume.

## Output

Write `.moa-v2/traces/<run-id>/01-grilling.md`:

- **Provenance header** — `input_hash` (SHA-256 of the original user text), `session_id`, `created_at`, `output_hash`.
- **Goal** — one line, one reading, no "or maybe".
- **Resolved decisions** — one line each, with the accepted answer.
- **Assumptions uncovered**.
- **Unknowns** — parked as `?`, never guessed into existence.
- **Open items** — anything left when the cap or an early stop fired.
- **Fact Evidence table** — per dispatch: `fact_id | agent | tool/command | raw result | timestamp | confidence | interpretation`.
- **Handoff** — `→ feeds Step 1 (prompt-optimizer) → 02-brief.md (source: 01-grilling.md, output_hash: <hash>)`.
- **Telemetry** — `grill_fact_calls_today` current value after this run.
