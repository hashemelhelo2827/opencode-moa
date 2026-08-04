# MOA_V2 Memory

Global registry for the moa-v2 pipeline. Read once per session at Step 1. Counters are updated by the primary agent after every model call. Writes are atomic (`.tmp` + rename) with `.lock` (wait <=30s, 2s backoff, stale steal after 60s).

## Skills Registry (vetted)

| Skill | Source | Verdict | Notes |
|---|---|---|---|
| prompt-optimizer | built-in (moa-v2) | clean | Step 1 |
| decompose-plan | built-in (moa-v2) | clean | Step 2 |
| skill-finder-stacker | built-in (moa-v2) | clean | Step 3 |
| test-script-maker | built-in (moa-v2) | clean | Step 6 |
| taste-skill | local ~/.config/opencode/skills/taste-skill | clean | frontend design rules, ALWAYS load for frontend tasks |

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

## Retention
- max_trace_age_days: 14
- auto_clean_on_start: true
