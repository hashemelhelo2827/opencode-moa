# AGENTS.md

## Project Overview

opencode-moa (moa-v2) is an evidence-based build pipeline for opencode. It orchestrates 10 sub-agents (DeepSeek, Nemotron, North, Mimo, Big Pickle, Gemini plan authors, Mistral reviewers) to build complete deliverables and proves correctness through a deterministic 5-gate review pipeline (semantic, static, runtime, adversarial, verdict). No model opinion can issue PASS - PASS is the output of the Python verdict engine applied to typed evidence bound to a hashed revision.

Stack: opencode agents + skills, Python 3.14+, PowerShell scripts, Docker (Gate C sandbox), Playwright (visual gate).

## Repository Layout

- `agents/` - 9 agent definitions (moa-v2 + team), each a `.md` file
- `skills/moa-v2/` - skill family: `grill-me/`, `prompt-optimizer/`, `decompose-plan/`, `skill-finder-stacker/`, `test-script-maker/`
- `skills/moa-v2/scripts/` - root-of-trust Python + PS1 scripts:
  - `verdict_engine.py` - authoritative verdict (no LLM)
  - `classify_complexity.py` - complexity scaling + policy requirement sets
  - `validate_flow.py` - browser-run gate: schema REJECT / policy normalize
  - `build_review_package.py` - typed review package builder
  - `mutate_workspace.py` - copy-on-write mutation tests
  - `benchmark_reviewer.py` - fallback-reviewer benchmark
  - `sandbox/` - Docker sandbox for Gate C (copy-in, no network, read-only fs)
  - `tests/` - pytest unit tests (81 tests)
  - `flow_menu.html` - flowchart editor (Mode 1)
- `config/opencode.jsonc.example` - trimmed provider + agent + Playwright MCP config
- `MOA_V2_MEMORY.md`, `LESSONS.md`, `STEP_B.md` - operational memory, lessons, and staged instructions

## Setup Commands

```powershell
# Copy agents into opencode config
Copy-Item -Recurse agents\* ~\.config\opencode\agents\

# Copy the skill family
Copy-Item -Recurse skills\moa-v2 ~\.config\opencode\skills\

# Merge config/opencode.jsonc.example blocks into your opencode.jsonc
```

API keys (env vars, never literals in repo): `MISTRAL_API_KEY` (reviewers), `GOOGLE_API_KEY`/Gemini (plan authors), opencode Zen/DeepSeek (orchestrator + parallel agents).

## Verification (run before pushing changes)

```powershell
cd skills\moa-v2\scripts
powershell -File .\test_moa_v2.ps1     # Gate 1 harness (97 checks)
powershell -File .\gate2_dry_run.ps1  # Gate 2 (providers + Docker)
python -m pytest tests -q             # unit tests (81 tests)
```

## Core Invariants

- Gate models NEVER write to the working tree (`edit: deny`).
- Gate IDs are always A-E. B-light/D-light are `gate_profiles` (depth floors), never gate IDs.
- Policy is enforced by `classify_complexity.py`; the orchestrator builds the review package with `gates_required = policy.required_gates` - NEVER from `00-flow.md`.
- Fail-closed: a missing required gate => `INCOMPLETE_REVIEW`, never PASS. If Mistral is down and the fallback reviewer is not benchmark-passed => `INCOMPLETE_REVIEW`, never a silent swap.
- Flow = execution preference. Policy = immutable requirement. Flow drops execution, never a requirement.
- Flow editor output is untrusted - every flow is validated by `validate_flow.py` before the run.

## Code Style

- Python 3.14+; tests use pytest and live in `scripts/tests/`.
- PowerShell scripts must be runnable from `scripts/` (paths relative).
- Keep root-of-trust logic in Python (deterministic); keep model-adjacent logic in agent `.md`/`SKILL.md` files.
- Verdict logic must stay pure (no LLM, no network).
- When adding a reviewer or fallback, add a benchmark entry and update `benchmark_reviewer.py`.

## Rate Limits & Quota

- Mistral free tier: 50 RPM / 50K TPM per model. Each reviewer pass must stay a single API call - pre-feed file contents inline. On 429: `Start-Sleep -Seconds 5` then retry.
- Gemini: ~1400 RPD / ~10 RPM - plan authoring only; implementation always goes to @moa-deepseek.
- Fail-closed as described under Core Invariants.

## Pull Request Guidelines

- Title format: `[moa-v2] <area>: <description>` or `Docs:`/`Fix:`/`Feat:` prefixes.
- Required checks: `powershell -File .\test_moa_v2.ps1` and `python -m pytest tests -q` must pass.
- Update `MOA_V2_MEMORY.md` budget counters and `LESSONS.md` (append-only) when behavior changes.
