#!/usr/bin/env python3
"""build_review_package.py — assembles the normalized review package (Gate E output) input.

Consumes the per-gate normalized reports plus an artifact manifest, verifies structural
integrity (every evidence ref resolves), computes the reviewed_revision, and writes a
review-package.json that verdict_engine.py can evaluate.

NOT a decision-maker: it performs no pass/fail judgment itself.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from typing import Any, Dict, List

GATE_STAGES = ("A", "B", "C", "D", "E", "VISUAL")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_tree(root: str, ignore: List[str]) -> str:
    """Deterministic tree hash: sha256 over sorted relative paths + file hashes."""
    if not os.path.isdir(root):
        raise FileNotFoundError(f"not a directory: {root}")
    entries = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if os.path.join(os.path.relpath(dirpath, root), d) not in ignore
        ]
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            if any(rel.startswith(ig.rstrip("/\\") + os.sep) or rel == ig for ig in ignore):
                continue
            entries.append((rel.replace("\\", "/"), sha256_file(full)))
    entries.sort(key=lambda e: e[0])
    h = hashlib.sha256()
    for rel, digest in entries:
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        h.update(digest.encode("ascii"))
        h.update(b"\x00")
    return h.hexdigest()


def build(
    *,
    reports: List[Dict[str, Any]],
    artifacts: List[Dict[str, Any]],
    gates_executed: List[str],
    gates_required: List[str],
    reviewed_revision: str,
    critical_security_issue: bool = False,
    environment_blocked: bool = False,
) -> Dict[str, Any]:
    """Merge gate reports into one normalized package."""
    artifact_map = {a["artifact_id"]: a for a in artifacts}

    # integrity: duplicate artifact ids
    if len(artifact_map) != len(artifacts):
        raise ValueError("duplicate artifact_id in artifacts")

    criteria: List[Dict[str, Any]] = []
    for rep in reports:
        for c in rep.get("criteria", []):
            cid = c["criterion_id"]
            if any(existing["criterion_id"] == cid for existing in criteria):
                raise ValueError(f"duplicate criterion_id: {cid}")
            for ref in c.get("evidence", []):
                if ref not in artifact_map:
                    raise ValueError(
                        f"criterion {cid} references missing artifact {ref}"
                    )
            criteria.append({**c, "evidence": [ref for ref in c.get("evidence", [])]})

    package = {
        "reviewed_revision": reviewed_revision,
        "gates_required": gates_required,
        "gates_executed": gates_executed,
        "criteria": criteria,
        "artifacts": artifact_map,
        "critical_security_issue": critical_security_issue,
        "environment_blocked": environment_blocked,
    }
    return package


def main(argv: List[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    # CLI contract (documented for the primary agent):
    #   build_review_package.py --reports reports/*.json --artifacts artifacts.json
    #     --gates-executed A,B,C,D,E --gates-required A,B,C,D,E --revision <hash>
    #     [--critical-security] [--env-blocked] [-o out.json]
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--reports", nargs="+", required=True)
    parser.add_argument("--artifacts", required=True)
    parser.add_argument("--gates-executed", required=True)
    parser.add_argument("--gates-required", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--critical-security", action="store_true")
    parser.add_argument("--env-blocked", action="store_true")
    parser.add_argument("-o", "--output", default="review-package.json")
    ns = parser.parse_args(args)

    reports = []
    for path in ns.reports:
        with open(path, "r", encoding="utf-8-sig") as fh:
            reports.append(json.load(fh))
    with open(ns.artifacts, "r", encoding="utf-8-sig") as fh:
        artifact_list = json.load(fh)

    pkg = build(
        reports=reports,
        artifacts=artifact_list,
        gates_executed=ns.gates_executed.split(","),
        gates_required=ns.gates_required.split(","),
        reviewed_revision=ns.revision,
        critical_security_issue=ns.critical_security,
        environment_blocked=ns.env_blocked,
    )
    with open(ns.output, "w", encoding="utf-8") as fh:
        json.dump(pkg, fh, indent=2, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())