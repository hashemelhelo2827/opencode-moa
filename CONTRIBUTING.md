# Contributing to opencode-moa

Thanks for your interest in contributing to the moa-v2 build pipeline. This project has strict invariants - read them carefully before making changes.

## Getting started

1. Fork the repository and clone your fork.
2. Follow the [Install](README.md#install) instructions to copy agents/skills into your opencode config.
3. Create a branch: `git checkout -b fix/my-change`.

## Core invariants (do not violate)

- Gate models NEVER write to the working tree (`edit: deny`).
- Gate IDs are always A-E. B-light/D-light are `gate_profiles`, never gate IDs.
- The orchestrator builds the review package with `gates_required = policy.required_gates` - NEVER from `00-flow.md`.
- Fail-closed: a missing required gate or an unbenchmarked fallback reviewer => `INCOMPLETE_REVIEW`, never PASS.
- Verdict logic stays pure Python - no LLM, no network.

## Before opening a PR

All checks must pass:

```powershell
cd skills\moa-v2\scripts
powershell -File .\test_moa_v2.ps1      # Gate 1 harness (97 checks)
python -m pytest tests -q               # unit tests (81 tests)
```

Run `gate2_dry_run.ps1` locally if your change touches providers or Docker.

## What to work on

- Bug fixes in the root-of-trust scripts (`verdict_engine.py`, `classify_complexity.py`, `validate_flow.py`).
- Unit tests in `skills/moa-v2/scripts/tests/`.
- Agent/SKILL.md content improvements (grill-me questions, prompt-optimizer tagging, decompose-plan criteria).
- New tools for the flow editor (`flow_menu.html`) - keep output untrusted and validated by `validate_flow.py`.

## Commit & PR guidelines

- Title format: `[moa-v2] <area>: <description>` or `Fix:`/`Feat:`/`Docs:` prefixes.
- When behavior changes, update `MOA_V2_MEMORY.md` budget counters and append to `LESSONS.md`.
- Reference the issue being fixed in the PR description.

## Reporting bugs

Open an issue with:

- The exact brief and flow configuration used
- Which gate (A-E) failed and its evidence/verdict output
- `python -m pytest tests -q` output if relevant
- opencode version and provider/API setup (never paste keys)
