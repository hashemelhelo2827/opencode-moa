# LESSONS.md — Append-only Lessons Log

Append-only log of verified patterns, preferences, failure modes, and hypotheses. The primary agent appends; never rewrites history.

## Lesson Schema

`{lesson_id, scope(global|stack|task), type(verified_pattern|preference|failure_mode|hypothesis), evidence, source_revision, created_at, expires_at, confidence, times_confirmed}`

- A `hypothesis` lesson can never modify the deterministic review rules (verdict thresholds, coverage formula, evidence freshness, flaky policy, security semantics).
- Registry/memory edits cannot change verdict rules.

---

## Lessons

(no lessons recorded yet)