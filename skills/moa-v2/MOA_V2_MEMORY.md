# MOA_V2 Memory

Global registry for the moa-v2 pipeline. Read once per session at Step 1. Counters are updated by the primary agent after every model call. Writes are atomic (`.tmp` + rename) with `.lock` (wait <=30s, 2s backoff, stale steal after 60s).

Workflow Authority and catalog entries are USER-EDITABLE CONFIG. They select which steps run; they never modify verdict rules (enforced by classify_complexity.py + validate_flow.py + verdict_engine.py).

## Skills Registry (vetted)

| Skill | Source | Verdict | Notes |
|---|---|---|---|
| prompt-optimizer | built-in (moa-v2) | clean | Step 1 |
| decompose-plan | built-in (moa-v2) | clean | Step 2 |
| skill-finder-stacker | built-in (moa-v2) | clean | Step 3 |
| test-script-maker | built-in (moa-v2) | clean | Step 6 |
| taste-skill | local ~/.config/opencode/skills/taste-skill | clean | frontend design rules, ALWAYS load for frontend tasks |
| grill-me | built-in (moa-v2) | clean | Step 0 (default-on design-tree interview, 6-round/25-Q cap) |

## Project Context
- **Current project**: (not set)
- **Tech stack**: (not set)
- **Design system**: (not set)

## Rate-Limit State (reset monthly)

| Counter | Cap | Value |
|---|---|---|
| mistral_lo_calls_today (mistral-small-2603) | ~1B tokens/month | 0 |
| mistral_hi_calls_today (mistral-medium-2604) | ~1B tokens/month | 0 |
| mistral_reviewer_last_call | - | - |
| gemini35_calls_today | ~1400/day | 0 |
| gemini3_calls_today | ~1400/day | 0 |
| deepseek_synthesis_calls_today | unlimited (telemetry) | 0 |
| grill_fact_calls_today (telemetry) | - | 0 |

## Reviewer Benchmark

| Model | Passed Benchmark | Last Run | Status |
| mistral/mistral-small-2603 | PASSED | - | fallback available until regression |
| mistral/mistral-medium-2604 | PASSED | - | fallback available until regression |
| google/gemini-3-flash | NOT_RUN | - | unavailable until benchmark-passed (reviewer fallback) |

Benchmark re-run policy: on any reviewer model/provider change + quarterly. A regressed fallback is disqualified until it re-passes. If Mistral is down and the fallback is not benchmark-passed → INCOMPLETE_REVIEW (never silent fallback).

Rate window (measured 2026-08-04 via x-ratelimit headers): 50 RPM / 50K TPM per model. Reviewers must stay a single API call per pass — orchestrator pre-feeds file contents inline; batch-read via `Get-Content -Raw a,b,c` only when content was not supplied inline.

## Rejected Skills

(none)

## Interactive Mode
- enabled: false
- pause_after_skill_search: conditional (only if rejections)
- pause_on_complexity_out_of_reach: true

## Workflow Authority
- enabled: false                 # true = show flow menu at run start (all sessions); OFF = no interactive flow editor
- flow_menu_mode: flowchart      # flowchart | picker
- per_session_override: true     # "flow menu this session" works without persisting
- grill_me: true                 # false = skip Step 0 interview (does NOT disable project-flow ask)
- saved_flows_dir: saved-flows/  # relative to this skill dir (global, all projects)
- project_flow_dir: .moa-v2/workflow/  # per-project copy + auto-detect location

## Test Catalog
| Test | Stack | Verdict | You-lose-if-off |
|---|---|---|---|
| pytest-functional | Python | clean | No Gate C core evidence → INCOMPLETE_REVIEW |
| bandit-security | Python | clean | No security signal (signal≠proof) |
| mutation (mutate_workspace.py) | Python | clean | Gate D-light floor unmet |
| node:test-functional | Node/JS | clean | No Gate C evidence |
| npm audit --offline | Node/JS | clean | NOT_RUN_OFFLINE recorded (never fabricated) |
| DOM/behavior | Web | clean | No behavioral coverage |
| OWASP checklist | Web | clean | No security signal |
| playwright-visual | Web/frontend | clean | Visual gate can't PASS |

## Tool Registry
| Tool | Verdict | You-lose-if-off |
|---|---|---|
| Playwright | clean | No visual gate; flowchart falls back to picker |
| Docker | clean | No Gate C runtime evidence |
| Mistral reviewers (lo+hi) | clean | No Gates A/B/E1 → INCOMPLETE_REVIEW |

## Retention
- max_trace_age_days: 14
- auto_clean_on_start: true
