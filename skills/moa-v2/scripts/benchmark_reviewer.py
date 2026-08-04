#!/usr/bin/env python3
"""benchmark_reviewer.py - fallback-reviewer benchmark bootstrap for moa-v2.

Purpose (spec section 14 Step C.3 / section 13): a fallback reviewer (and by
extension any newly-introduced reviewer model) is UNAVAILABLE until it passes a
fixed benchmark corpus. This script owns the deterministic part:

    - a FIXED_CORPUS of review tasks with gold guarantees,
    - a deterministic scorer that compares a reviewer's per-criterion status
      against the gold status,
    - a PASS / FAIL decision from those scores,
    - a CLI that writes the outcome into MOA_V2_MEMORY.md (atomic write).

The reviewer model itself is invoked by the opencode runtime (the primary
agent / gate), never by this script. The script is the adjudicator for WHAT
counts as "benchmark-passed", so a model cannot self-certify.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from typing import Any, Dict, List, Optional

from verdict_engine import evaluate as judge

CORPUS_SOURCE = os.path.abspath(__file__)
MAX_SCORE = 100.0
PASS_THRESHOLD = 80.0  # percentage of exact-status matches required to pass

# Each task: a synthetic review package (accepted by verdict_engine) plus the
# expected per-criterion status that a correct reviewer must produce.
CORPUS: List[Dict[str, Any]] = [
    {
        "id": "BC-01",
        "name": "trivial build correctness",
        "reviewed_revision": "abcd" + "1" * 60,
        "gate": "B-light",
        "expected": {"C-01": "VERIFIED", "C-02": "VERIFIED"},
        "package": {
            "reviewed_revision": "abcd" + "1" * 60,
            "gates_required": ["A"],
            "gates_executed": ["A"],
            "criteria": [
                {"criterion_id": "C-01", "severity": "minor", "status": "VERIFIED",
                 "evidence": ["r1"], "confidence": "high", "justification": "ok"},
                {"criterion_id": "C-02", "severity": "minor", "status": "VERIFIED",
                 "evidence": ["r2"], "confidence": "high", "justification": "ok"},
            ],
            "artifacts": {
                "r1": {"artifact_id": "r1", "evidence_state": "FRESH"},
                "r2": {"artifact_id": "r2", "evidence_state": "FRESH"},
            },
            "critical_security_issue": False,
            "environment_blocked": False,
        },
    },
    {
        "id": "BC-02",
        "name": "detect blocking regression",
        "reviewed_revision": "abcd" + "7" * 60,
        "gate": "E2",
        "expected": {"C-01": "FAILED"},
        "gold_verdict": "FAIL",
        "package": {
            "reviewed_revision": "abcd" + "7" * 60,
            "gates_required": ["A", "B", "C", "D", "E"],
            "gates_executed": ["A", "B", "C", "D", "E"],
            "criteria": [
                {"criterion_id": "C-01", "severity": "blocking", "status": "FAILED",
                 "evidence": ["r1"], "confidence": "high", "justification": "regression"},
            ],
            "artifacts": {"r1": {"artifact_id": "r1", "state": "FRESH"}},
            "critical_security_issue": False,
            "environment_blocked": False,
        },
    },
]


def check_corpus() -> List[str]:
    """Sanity: every corpus package must produce a valid, expected verdict."""
    problems = []
    for c in CORPUS:
        try:
            res = judge(c["package"])
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{c['id']}: judge raised {exc}")
            continue
        if res["verdict"] != c.get("gold_verdict", "PASS"):
            problems.append(f"{c['id']}: got {res['verdict']}, want {c.get('gold_verdict')}")
    return problems


def _normalize(resp: Dict[str, Any]) -> Dict[str, str]:
    """Flatten a reviewer response into {criterion_id: status}."""
    return {
        c.get("criterion_id", "?"): c.get("status", "?")
        for c in resp.get("criteria", [])
    }


def evaluate_run(response: Dict[str, Any]) -> Dict[str, Any]:
    """Score one reviewer response against the matched corpus task."""
    task_id = response.get("task_id") or response.get("id") or ""
    task = next((c for c in CORPUS if c["id"] == task_id), None)
    if task is None:
        raise ValueError(f"unknown or missing task_id for benchmark: {task_id}")

    gold = task["expected"]
    got = _normalize(response)
    exact = 0
    total = len(gold)
    mismatches = []
    for cid, want in gold.items():
        if got.get(cid) == want:
            exact += 1
        else:
            mismatches.append({"criterion_id": cid, "want": want, "got": got.get(cid)})
    pct = (exact / total * 100.0) if total else 100.0
    return {
        "task_id": task_id,
        "exact_matches": exact,
        "total": total,
        "score": round(pct, 2),
        "passed": pct >= PASS_THRESHOLD,
        "mismatches": mismatches,
    }


def run_all(responses: List[Dict[str, Any]]) -> Dict[str, Any]:
    scores = [evaluate_run(r) for r in responses]
    overall = round(sum(s["score"] for s in scores) / len(scores), 2) if scores else 0.0
    return {
        "scores": scores,
        "overall": overall,
        "passed": overall >= PASS_THRESHOLD and all(s["passed"] for s in scores),
    }


def patch_status(memory_path: str, model: str, status: str) -> None:
    """Atomically update a reviewer's row in the Reviewer Benchmark table.

    status: passed | unavailable | not_run. Writes via tempfile + os.replace.
    """
    if status == "passed":
        verdict = "PASSED"
        note = "fallback available until regression"
    elif status == "unavailable":
        verdict = "FAILED"
        note = "regressed; unavailable until benchmark-passed"
    else:
        verdict = "NOT_RUN"
        note = "unavailable until benchmark-passed"

    if not os.path.exists(memory_path):
        text = (
            "## Reviewer Benchmark\n"
            "| Model | Passed Benchmark | Last Run | Status |\n"
        ) + f"| {model} | {verdict} | - | {note} |\n"
    else:
        with open(memory_path, "r", encoding="utf-8") as fh:
            text = fh.read()

    line_key = "| " + model + " |"
    pat = re.compile(re.escape(line_key) + r"[^\n]*")
    row = f"| {model} | {verdict} | - | {note} |"
    if pat.search(text):
        new_text = pat.sub(row, text)
    else:
        marker = "| Model | Passed Benchmark | Last Run | Status |\n"
        m = re.search(r"(## Reviewer Benchmark\n[^\n]*\n)(```.*?```\s*)?", text, re.S)
        if m:
            end_line = text.find(marker, m.start())
            if end_line >= 0:
                eol = text.find("\n", end_line) + 1
                new_text = text[:eol] + row + "\n" + text[eol:]
            else:
                new_text = text + "\n" + row + "\n"
        else:
            head = "## Reviewer Benchmark\n| Model | Passed Benchmark | Last Run | Status |\n"
            new_text = text.rstrip("\n") + "\n\n" + head + row + "\n"

    d = os.path.dirname(os.path.abspath(memory_path))
    fd, tmp = tempfile.mkstemp(prefix=".bench-", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(new_text)
        os.replace(tmp, memory_path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main(argv: Optional[List[str]] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(description="moa-v2 reviewer benchmark")
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check-corpus")
    p_check.add_argument("--output", default="")

    p_score = sub.add_parser("score")
    p_score.add_argument("--responses", required=True, help="json list of reviewer responses")
    p_score.add_argument("--output", default="")

    p_run = sub.add_parser("run")
    p_run.add_argument("--responses", required=True)
    p_run.add_argument("--output", default="")
    p_run.add_argument("--memory", default="")
    p_run.add_argument("--model", default="google/gemini-3-flash")

    p_rec = sub.add_parser("set-status")
    p_rec.add_argument("--model", required=True)
    p_rec.add_argument("--status", choices=["passed", "unavailable", "not_run"])
    p_rec.add_argument("--memory", default="")

    ns = parser.parse_args(args)

    if ns.command == "check-corpus":
        problems = check_corpus()
        out = {"ok": not problems, "problems": problems}
        _emit(out, ns.output)
        return 0 if out["ok"] else 1

    if ns.command == "score":
        with open(ns.responses, "r", encoding="utf-8-sig") as fh:
            resp = json.load(fh)
        out = run_all(resp)
        _emit(out, ns.output)
        return 0 if out["passed"] else 1

    if ns.command == "run":
        with open(ns.responses, "r", encoding="utf-8-sig") as fh:
            resp = json.load(fh)
        score_result = run_all(resp)
        if ns.memory:
            patch_status(ns.memory, ns.model,
                         "passed" if score_result["passed"] else "unavailable")
        _emit(score_result, ns.output)
        return 0 if score_result["passed"] else 1

    if ns.command == "set-status":
        if not ns.memory:
            raise SystemExit("set-status requires --memory")
        patch_status(ns.memory, ns.model, ns.status)
        return 0


def _emit(obj: Dict[str, Any], path: str) -> None:
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=2)
    else:
        print(json.dumps(obj, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())