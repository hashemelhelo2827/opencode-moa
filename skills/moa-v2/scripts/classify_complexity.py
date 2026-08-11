#!/usr/bin/env python3
"""classify_complexity.py — authoritative complexity scoring for moa-v2.

Scoring:
  +2  ui / frontend
  +2  auth / authz
  +2  untrusted input / file handling
  +2  destructive / data migration
  +2  external API / network
  +2  concurrency / background jobs
  +2  security-sensitive logic
  +1  >10 source files
  +1  >1 runtime
  +1  persistent database

Tier:  0-2 trivial, 3-5 standard, 6+ complex (max 17).
Any blocking security criterion forces tier >= standard.
The primary agent cannot self-downgrade past this.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Set

FEATURE_FLAGS = {
    "ui": 2,
    "auth": 2,
    "untrusted_input": 2,
    "destructive_migration": 2,
    "external_api": 2,
    "concurrency": 2,
    "security_sensitive": 2,
}
MAX_SCORE = 7 * 2 + 3 * 1  # 17

SENSITIVE_SINGLE_FILE_KEYWORDS = {
    "auth", "crypto", "crypt", "migration", "migrate", "webhook", "deploy",
    "payment", "stripe", "checkout", "login", "signin", "signup", "oauth",
    "jwt", "session", "upload", "sanitiz", "validate",
}

REQUIRED_GATES = {
    "trivial":  ["A", "B", "D", "E"],          # gate IDs always A–E
    "standard": ["A", "B", "C", "D", "E"],
    "complex":  ["A", "B", "C", "D", "E"],
}
GATE_PROFILES = {
    "trivial":  {"B": "light", "D": "light"},
    "standard": {},
    "complex":  {},
}
REQUIRED_TESTS = {
    "trivial":  ["pytest-functional"],
    "standard": ["pytest-functional", "bandit-security"],
    "complex":  ["pytest-functional", "bandit-security", "mutation"],
}
REQUIRED_TOOLS = {
    "trivial":  [],
    "standard": ["docker"],
    "complex":  ["docker", "playwright"],  # playwright only for frontend
}


def classify(
    *,
    features: Set[str],
    source_file_count: int = 0,
    runtime_count: int = 1,
    has_db: bool = False,
    blocking_security: bool = False,
    is_single_file: bool = False,
    file_path: str = "",
) -> Dict[str, Any]:
    score = 0
    reasons: List[str] = []
    for k, v in FEATURE_FLAGS.items():
        if k in features:
            score += v
            reasons.append(f"{k}: +{v}")
    if source_file_count > 10:
        score += 1
        reasons.append(f"source_file_count={source_file_count} > 10: +1")
    if runtime_count > 1:
        score += 1
        reasons.append(f"runtime_count={runtime_count} > 1: +1")
    if has_db:
        score += 1
        reasons.append("persistent_db: +1")

    tier = _tier(score)

    # Any blocking security criterion forces >= standard.
    if blocking_security and tier == "trivial":
        tier = "standard"
        reasons.append("blocking_security: forced >= standard")

    # Single-file sensitive logic is never trivial.
    if is_single_file and tier == "trivial" and _sensitive_single_file(file_path):
        tier = "standard"
        reasons.append("single-file sensitive logic: forced >= standard")

    required_gates = list(REQUIRED_GATES[tier])
    gate_profiles = dict(GATE_PROFILES[tier])
    required_tests = list(REQUIRED_TESTS[tier])
    required_tools = list(REQUIRED_TOOLS[tier])
    if blocking_security and "bandit-security" not in required_tests:
        required_tests.append("bandit-security")
    if "ui" in features and "playwright-visual" not in required_tests:
        required_tests.append("playwright-visual")
    if "ui" in features and "playwright" not in required_tools:
        required_tools.append("playwright")

    return {
        "score": score,
        "tier": tier,
        "reasons": reasons,
        "max_score": MAX_SCORE,
        "source_file_count": source_file_count,
        "runtime_count": runtime_count,
        "has_db": has_db,
        "blocking_security": blocking_security,
        "required_gates": required_gates,
        "gate_profiles": gate_profiles,
        "required_tests": required_tests,
        "required_tools": required_tools,
    }


def _tier(score: int) -> str:
    if score <= 2:
        return "trivial"
    if score <= 5:
        return "standard"
    return "complex"


def _sensitive_single_file(file_path: str) -> bool:
    lowered = file_path.lower()
    return any(kw in lowered for kw in SENSITIVE_SINGLE_FILE_KEYWORDS)


def classify_paths(
    source_files: List[str],
    *,
    features: Set[str],
    has_db: bool = False,
    blocking_security: bool = False,
) -> Dict[str, Any]:
    """classify() from a list of source file paths (deterministic, no stat I/O)."""
    runtime_count = len({_runtime_hint(f) for f in source_files if _runtime_hint(f)})
    runtime_count = max(1, runtime_count)
    return classify(
        features=features,
        source_file_count=len(source_files),
        runtime_count=runtime_count,
        has_db=has_db,
        blocking_security=blocking_security,
        is_single_file=len(source_files) == 1,
        file_path=source_files[0] if source_files else "",
    )


_RUNTIME_HINTS = {
    ".py": "python", ".pyw": "python",
    ".js": "node", ".mjs": "node", ".cjs": "node", ".ts": "node",
    ".html": "web", ".css": "web", ".jsx": "web", ".tsx": "web",
}


def _runtime_hint(path: str) -> str:
    dot = path.rfind(".")
    if dot < 0:
        return ""
    ext = path[dot:]
    return _RUNTIME_HINTS.get(ext, "")


def main(argv: List[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(description="moa-v2 complexity classifier")
    for flag in FEATURE_FLAGS:
        parser.add_argument(f"--{flag}", action="store_true")
    parser.add_argument("--has-db", action="store_true")
    parser.add_argument("--blocking-security", action="store_true")
    parser.add_argument("--files", nargs="*", default=[])
    parser.add_argument("--source-file-count", type=int, default=0)
    parser.add_argument("--runtime-count", type=int, default=1)
    parser.add_argument("--output", default="")
    ns = parser.parse_args(args)

    features = {k for k in FEATURE_FLAGS if getattr(ns, k)}

    if ns.files:
        result = classify_paths(
            ns.files, features=features, has_db=ns.has_db,
            blocking_security=ns.blocking_security,
        )
    else:
        result = classify(
            features=features,
            source_file_count=ns.source_file_count,
            runtime_count=ns.runtime_count,
            has_db=ns.has_db,
            blocking_security=ns.blocking_security,
        )

    if ns.output:
        with open(ns.output, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
    else:
        print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())