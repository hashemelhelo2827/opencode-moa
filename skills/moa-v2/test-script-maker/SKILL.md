---
name: moa-v2-test-script-maker
description: moa-v2 pipeline Step 6 — Generate the test matrix and scripts per stack, build command templates, and record execution inside the Docker sandbox. Use when the implementation is ready to be tested.
---

# Test Script Maker (moa-v2 Step 6)

Produce verified, runnable tests bound to criteria.

## Test Matrix

Source: MOA_V2_MEMORY.md → Test Catalog, filtered by the run's flow selection (00-flow.md).

| Stack | Functional | Security signal |
|---|---|---|
| Python | pytest | bandit |
| Node / JS | node:test | npm audit `--offline` (else `NOT_RUN_OFFLINE`) + manual |
| Web | DOM / behavior | OWASP Top 10 checklist |
| Unknown | per-entry smoke | manual OWASP Top 10 |

## Rules

- Each test maps to at least one criterion_id. Record the mapping so Gate B can prove coverage.
- Tests are executed inside the Docker sandbox by @moa-runtime-verifier (Gate C). Never assume host execution.
- Provide the exact command for each suite.
- npm audit MUST run with `--offline`; if it cannot, record `NOT_RUN_OFFLINE` as the evidence state — never fabricate audit results.
- Set fixed seeds where randomness is involved so runs are reproducible.
- Tests are chosen from the vetted Test Catalog matching the run's stack AND `00-flow.md` test picks. Catalog tests are already vetted; anything discovered mid-run follows the quarantine stance (`04-vet-*`) before use.
- Unselected catalog tests are NOT run; they are listed in `00-flow.md` with their loss line for Gate A transparency.
- `MANIFEST.md` maps every chosen test → `criterion_id(s)` → stack.

## Output

Write test files under `.moa-v2/tests/` and a `.moa-v2/tests/MANIFEST.md` mapping each test → criterion_id(s) → stack.