import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from benchmark_reviewer import (
    CORPUS,
    PASS_THRESHOLD,
    check_corpus,
    evaluate_run,
    patch_status,
    run_all,
)


def test_corpus_is_self_consistent_with_verdict_engine():
    problems = check_corpus()
    assert problems == [], problems


def test_all_corpus_tasks_have_expected_gold():
    for c in CORPUS:
        assert "id" in c
        assert "expected" in c and isinstance(c["expected"], dict)
        assert "package" in c


def test_perfect_response_scores_100_and_passes():
    resp = {
        "task_id": "BC-01",
        "criteria": [
            {"criterion_id": "C-01", "status": "VERIFIED"},
            {"criterion_id": "C-02", "status": "VERIFIED"},
        ],
    }
    res = evaluate_run(resp)
    assert res["score"] == 100.0
    assert res["passed"] is True


def test_mismatched_status_scores_below_passing():
    resp = {
        "task_id": "BC-01",
        "criteria": [
            {"criterion_id": "C-01", "status": "FAILED"},
            {"criterion_id": "C-02", "status": "VERIFIED"},
        ],
    }
    res = evaluate_run(resp)
    assert res["score"] == 50.0
    assert res["passed"] is False


def test_run_all_requires_all_tasks_pass():
    responses = [
        {
            "task_id": "BC-01",
            "criteria": [
                {"criterion_id": "C-01", "status": "VERIFIED"},
                {"criterion_id": "C-02", "status": "VERIFIED"},
            ],
        },
        {
            "task_id": "BC-02",
            "criteria": [{"criterion_id": "C-01", "status": "NOT_TESTED"}],
        },
    ]
    res = run_all(responses)
    assert res["passed"] is False


def test_unknown_task_raises():
    with pytest.raises(ValueError):
        evaluate_run({"task_id": "NOPE", "criteria": []})


def test_patch_status_adds_and_updates_row(tmp_path):
    mem = tmp_path / "MOA_V2_MEMORY.md"
    model = "google/gemini-3-flash"

    patch_status(str(mem), model, "not_run")
    text = mem.read_text(encoding="utf-8")
    assert "| google/gemini-3-flash | NOT_RUN |" in text
    assert "## Reviewer Benchmark" in text

    patch_status(str(mem), model, "passed")
    text = mem.read_text(encoding="utf-8")
    assert "| google/gemini-3-flash | PASSED |" in text
    # no duplicate rows
    assert text.count("google/gemini-3-flash") == 1


def test_patch_status_updates_existing_file(tmp_path):
    mem = tmp_path / "MOA_V2_MEMORY.md"
    mem.write_text(
        "## Reviewer Benchmark\n"
        "| Model | Passed Benchmark | Last Run | Status |\n"
        "| google/gemini-3-flash | NOT_RUN | - | unavailable until benchmark-passed |\n",
        encoding="utf-8",
    )
    patch_status(str(mem), "google/gemini-3-flash", "passed")
    assert "| google/gemini-3-flash | PASSED |" in mem.read_text(encoding="utf-8")
    assert mem.read_text(encoding="utf-8").count("google/gemini-3-flash") == 1