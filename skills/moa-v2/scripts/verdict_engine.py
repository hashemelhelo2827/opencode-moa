#!/usr/bin/env python3
"""verdict_engine.py — deterministic, no-LLM adjudicator for moa-v2.

Applies the PASS rules literally. Emits one of:
    PASS | FAIL | INCOMPLETE_REVIEW | ENVIRONMENT_BLOCKED | FATAL_INTEGRITY_ERROR

PASS requires ALL of:
  1. no critical security issue
  2. all required gates executed
  3. every blocking criterion VERIFIED
  4. major_coverage = VERIFIED / (all major - justified N/A) >= 0.90 (NO ROUNDING)
  5. no unjustified NOT_TESTED criterion
  6. all referenced evidence FRESH and resolvable to artifact_ids

A model never calls this with opinions — it only supplies normalized JSON evidence.
"""
from __future__ import annotations

import json
import sys
from typing import Any, Dict, List

VERDICTS = {
    "PASS",
    "FAIL",
    "INCOMPLETE_REVIEW",
    "ENVIRONMENT_BLOCKED",
    "FATAL_INTEGRITY_ERROR",
}
SEVERITIES = {"blocking", "major", "minor"}
STATUSES = {"VERIFIED", "FAILED", "NOT_TESTED", "NOT_APPLICABLE"}
EVIDENCE_STATES = {"FRESH", "STALE", "SUPERSEDED", "INVALID"}
COVERAGE_THRESHOLD = 0.90  # exact, no rounding


class PackageError(Exception):
    """Structural/validation error in the review package (integrity)."""


def _required(pkg: Dict[str, Any], key: str) -> Any:
    if key not in pkg:
        raise PackageError(f"missing required field: {key}")
    return pkg[key]


def _resolve_flaky(criteria: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Flaky policy: a pass-after-fail run on a blocking/major criterion -> FAILED."""
    resolved = []
    for c in criteria:
        c = dict(c)
        if c.get("flaky") is True and c.get("severity") in ("blocking", "major"):
            if c.get("status") == "VERIFIED":
                c["status"] = "FAILED"
                c["justification"] = (
                    c.get("justification", "")
                    + " [FLAKY: pass observed only after failure; policy => FAILED]"
                ).strip()
        else:
            c["flaky"] = False
        resolved.append(c)
    return resolved


def _check_evidence_resolvable(
    criteria: List[Dict[str, Any]], artifacts: Dict[str, Dict[str, Any]]
) -> List[str]:
    """Every evidence ref must exist in the artifact manifest and be FRESH."""
    problems: List[str] = []
    for c in criteria:
        for ref in c.get("evidence", []):
            art = artifacts.get(ref)
            if art is None:
                problems.append(
                    f"{c['criterion_id']}: evidence ref {ref} not in artifact manifest"
                )
                continue
            state = art.get("evidence_state", art.get("state", "FRESH"))
            if state != "FRESH":
                problems.append(
                    f"{c['criterion_id']}: evidence {ref} is {state} (not FRESH)"
                )
    return problems


def evaluate(pkg: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate a normalized review package. Returns a verdict dict (JSON-serializable)."""
    reasons: List[str] = []

    # ---- structural / integrity ----
    try:
        reviewed_revision = _required(pkg, "reviewed_revision")
        criteria = _required(pkg, "criteria")
        artifacts = pkg.get("artifacts", {})
        gates_required = pkg.get("gates_required", [])
        gates_executed = pkg.get("gates_executed", [])
        critical_security_issue = bool(pkg.get("critical_security_issue", False))
        env_blocked = bool(pkg.get("environment_blocked", False))
    except PackageError as exc:
        return _verdict("FATAL_INTEGRITY_ERROR", [str(exc)], pkg)

    if not isinstance(criteria, list):
        return _verdict("FATAL_INTEGRITY_ERROR", ["criteria must be a list"], pkg)

    # ---- flaky resolution (deterministic) ----
    criteria = _resolve_flaky(criteria)

    # validate fields
    for c in criteria:
        if c.get("severity") not in SEVERITIES:
            return _verdict(
                "FATAL_INTEGRITY_ERROR", [f"bad severity in {c.get('criterion_id')}"], pkg
            )
        if c.get("status") not in STATUSES:
            return _verdict(
                "FATAL_INTEGRITY_ERROR", [f"bad status in {c.get('criterion_id')}"], pkg
            )

    # ---- environment / completeness / integrity outcomes ----
    if env_blocked:
        return _verdict(
            "ENVIRONMENT_BLOCKED",
            ["driver reported environment blocked; cannot safely complete gates"],
            pkg,
        )

    missing_gates = [g for g in gates_required if g not in gates_executed]
    if missing_gates:
        return _verdict(
            "INCOMPLETE_REVIEW",
            [f"required gate(s) not executed: {', '.join(missing_gates)}"],
            pkg,
        )

    evidence_problems = _check_evidence_resolvable(criteria, artifacts)
    if evidence_problems:
        return _verdict("INCOMPLETE_REVIEW", evidence_problems, pkg)

    if gates_required:
        bad_evidence = _stale_or_invalid_evidence(criteria, artifacts)
        if bad_evidence:
            return _verdict("INCOMPLETE_REVIEW", bad_evidence, pkg)

    # ---- PASS conditions ----
    if critical_security_issue:
        reasons.append("critical security issue present")

    blocking = [c for c in criteria if c["severity"] == "blocking"]
    failed_blocking = [c for c in blocking if c["status"] != "VERIFIED"]
    if failed_blocking:
        reasons.append(
            "blocking criterion not VERIFIED: "
            + ", ".join(c["criterion_id"] for c in failed_blocking)
        )

    major_denominator = [
        c for c in criteria if c["severity"] == "major" and not c.get("is_not_applicable")
    ]
    major_verified = [c for c in major_denominator if c["status"] == "VERIFIED"]
    denominator = len(major_denominator)
    numerator = len(major_verified)
    coverage = (numerator / denominator) if denominator > 0 else 1.0
    if coverage < COVERAGE_THRESHOLD:
        reasons.append(
            f"major coverage {coverage:.4f} < {COVERAGE_THRESHOLD:.2f} "
            f"({numerator}/{denominator}, no rounding)"
        )

    unjust_not_tested = [
        c["criterion_id"]
        for c in criteria
        if c["status"] == "NOT_TESTED" and not c.get("justified_not_tested")
    ]
    if unjust_not_tested:
        reasons.append("unjustified NOT_TESTED: " + ", ".join(unjust_not_tested))

    if reasons:
        return _verdict("FAIL", reasons, pkg)

    return _verdict("PASS", ["all PASS conditions satisfied"], pkg)


def _stale_or_invalid_evidence(
    criteria: List[Dict[str, Any]], artifacts: Dict[str, Dict[str, Any]]
) -> List[str]:
    probs: List[str] = []
    for c in criteria:
        for ref in c.get("evidence", []):
            art = artifacts.get(ref)
            if art is None:
                continue
            state = art.get("state", "FRESH")
            if state in ("STALE", "SUPERSEDED", "INVALID"):
                probs.append(
                    f"{c['criterion_id']}: evidence {ref} not FRESH ({state})"
                )
    return probs


def _verdict(verdict: str, reasons: List[str], pkg: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "verdict": verdict,
        "reasons": reasons,
        "reviewed_revision": pkg.get("reviewed_revision"),
    }


def main(argv: List[str] | None = None) -> int:
    import sys

    args = argv if argv is not None else sys.argv[1:]
    if not args:
        sys.stderr.write(__doc__)
        return 2
    with open(args[0], "r", encoding="utf-8-sig") as fh:
        pkg = json.load(fh)
    result = evaluate(pkg)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())