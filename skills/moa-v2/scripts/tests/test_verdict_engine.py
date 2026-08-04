import pytest

from verdict_engine import evaluate, COVERAGE_THRESHOLD


def _pkg(**overrides):
    base = {
        "reviewed_revision": "abc123",
        "criteria": [
            {
                "criterion_id": "C-01",
                "severity": "blocking",
                "status": "VERIFIED",
                "evidence": ["a1"],
            },
            {
                "criterion_id": "C-02",
                "severity": "major",
                "status": "VERIFIED",
                "evidence": ["a2"],
            },
            {"criterion_id": "C-03", "severity": "major", "status": "VERIFIED",
             "evidence": ["a3"]},
            {"criterion_id": "C-04", "severity": "major", "status": "VERIFIED",
             "evidence": ["a4"]},
            {"criterion_id": "C-05", "severity": "major", "status": "VERIFIED",
             "evidence": ["a5"]},
            {"criterion_id": "C-06", "severity": "major", "status": "VERIFIED",
             "evidence": ["a6"]},
        ],
        "artifacts": {
            "a1": {"state": "FRESH"},
            "a2": {"state": "FRESH"},
            "a3": {"state": "FRESH"},
            "a4": {"state": "FRESH"},
            "a5": {"state": "FRESH"},
            "a6": {"state": "FRESH"},
        },
        "gates_required": ["A", "B", "C", "D", "E"],
        "gates_executed": ["A", "B", "C", "D", "E"],
        "critical_security_issue": False,
        "environment_blocked": False,
    }
    base.update(overrides)
    return base


def test_pass_all_conditions():
    res = evaluate(_pkg())
    assert res["verdict"] == "PASS"


def test_critical_security_fails():
    p = _pkg(critical_security_issue=True)
    assert evaluate(p)["verdict"] == "FAIL"


def test_missing_required_gate_incomplete():
    p = _pkg(gates_executed=["A", "B", "C"])
    assert evaluate(p)["verdict"] == "INCOMPLETE_REVIEW"


def test_8_of_9_major_no_rounding_fails():
    p = _pkg(criteria=[
        {
            "criterion_id": f"C-{i:02d}",
            "severity": "major",
            "status": "VERIFIED" if i <= 8 else "FAILED",
            "evidence": [],
        }
        for i in range(1, 10)
    ])
    assert COVERAGE_THRESHOLD == 0.90
    assert (8 / 9) < 0.90  # guard
    assert evaluate(p)["verdict"] == "FAIL"


def test_9_of_10_major_passes():
    p = _pkg(criteria=[
        {
            "criterion_id": f"C-{i:02d}",
            "severity": "major",
            "status": "VERIFIED" if i != 10 else "FAILED",
            "evidence": [],
        }
        for i in range(1, 11)
    ])
    assert (9 / 10) == 0.90
    assert evaluate(p)["verdict"] == "PASS"


def test_unjustified_not_tested_fails():
    p = _pkg(criteria=[
        {"criterion_id": "C-01", "severity": "major", "status": "NOT_TESTED",
         "evidence": []},
    ])
    assert evaluate(p)["verdict"] == "FAIL"


def test_justified_not_tested_allowed():
    # justified NOT_TESTED on a minor criterion does not violate the no-unjustified test,
    # and minors do not count against major coverage -> PASS.
    p = _pkg(criteria=[
        {
            "criterion_id": "C-01", "severity": "blocking", "status": "VERIFIED",
            "evidence": ["a1"],
        },
        {
            "criterion_id": "C-02", "severity": "major", "status": "VERIFIED",
            "evidence": ["a2"],
        },
        {
            "criterion_id": "C-03", "severity": "minor", "status": "NOT_TESTED",
            "justified_not_tested": True, "evidence": [],
        },
    ])
    assert evaluate(p)["verdict"] == "PASS"


def test_justified_not_tested_major_still_counts_in_coverage():
    # a justified-NOT_TESTED major is NOT 'justified N/A': it still sits in the
    # coverage denominator, so 0/N coverage fails.
    p = _pkg(criteria=[
        {
            "criterion_id": "C-01", "severity": "major", "status": "NOT_TESTED",
            "justified_not_tested": True, "evidence": [],
        },
    ])
    assert evaluate(p)["verdict"] == "FAIL"


def test_blocking_not_verified_fails():
    p = _pkg(criteria=[
        {"criterion_id": "C-01", "severity": "blocking", "status": "NOT_TESTED",
         "evidence": []},
    ])
    assert evaluate(p)["verdict"] == "FAIL"


def test_stale_evidence_incomplete():
    p = _pkg()
    p["artifacts"]["a2"]["state"] = "STALE"
    assert evaluate(p)["verdict"] == "INCOMPLETE_REVIEW"


def test_missing_artifact_reference_incomplete():
    p = _pkg()
    p["criteria"][0]["evidence"] = ["nonexistent"]
    assert evaluate(p)["verdict"] == "INCOMPLETE_REVIEW"


def test_environment_blocked():
    assert evaluate(_pkg(environment_blocked=True))["verdict"] == "ENVIRONMENT_BLOCKED"


def test_missing_reviewed_revision_integrity():
    p = _pkg()
    del p["reviewed_revision"]
    assert evaluate(p)["verdict"] == "FATAL_INTEGRITY_ERROR"


def test_flaky_pass_after_fail_becomes_failed():
    p = _pkg()
    p["criteria"].append({
        "criterion_id": "C-X", "severity": "blocking", "status": "VERIFIED",
        "evidence": ["a6"], "flaky": True,
    })
    assert evaluate(p)["verdict"] == "FAIL"


def test_flaky_minor_not_downgraded():
    p = _pkg()
    p["criteria"].append({
        "criterion_id": "C-X", "severity": "minor", "status": "VERIFIED",
        "evidence": ["a6"], "flaky": True,
    })
    assert evaluate(p)["verdict"] == "PASS"