#!/usr/bin/env python3
"""mutate_workspace.py — cost-bounded mutation testing for moa-v2 (Gate D).

Creates an immutable snapshot, applies ONE criterion-bound mutation to a copy, runs the
intended test, verifies the test FAILS (proving it is mutation-sensitive), records the
result, and destroys the temp workspace. The original tree is NEVER modified.

Mutation record schema:
  {mutation_id, target, mutation, expected_tests, observed_failure, workspace_revision,
   original_tree_unchanged}

Integration notes:
  - Prefer copy-on-write snapshots (a git worktree) for large trees; this module falls
    back to a plain copy for hermetic use.
  - One long-lived sandbox container per review loop, not one per mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional


class MutationError(Exception):
    pass


def snapshot(src: str, dst: str) -> str:
    """Copy src -> dst. Returns the dst. Common excludes applied."""
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst, symlinks=False, ignore=_ignore_dirs)
    return dst


def _ignore_dirs(dir_path: str, names: List[str]) -> List[str]:
    excluded = {".git", ".moa-v2", "node_modules", "__pycache__", ".venv", "venv"}
    return [n for n in names if n in excluded]


def hash_tree(root: str, ignore: Optional[List[str]] = None) -> str:
    ignore = set(ignore or [])
    h = hashlib.sha256()
    entries = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {"__pycache__", ".venv", "venv"}]
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            if any(rel.startswith(ig) for ig in ignore):
                continue
            with open(full, "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()
            entries.append((rel.replace("\\", "/"), digest))
    entries.sort(key=lambda e: e[0])
    for rel, digest in entries:
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        h.update(digest.encode("ascii"))
        h.update(b"\x00")
    return h.hexdigest()


def apply_mutation(
    workdir: str,
    *,
    target_file: str,
    old: str,
    new: str,
    description: str,
    mutation_id: str,
) -> Dict[str, Any]:
    """Apply a single text mutation to a target file within workdir.

    Returns a mutation record WITHOUT running tests (test run is separate so this logic
    can be unit tested hermetically). Verifies the mutation actually changed the file.
    """
    path = os.path.join(workdir, target_file)
    if not os.path.isfile(path):
        raise MutationError(f"target file not found in workdir: {target_file}")
    with open(path, "r", encoding="utf-8") as fh:
        content = fh.read()
    if old not in content:
        raise MutationError(
            f"mutation anchor not found in {target_file}: {old!r}"
        )
    new_content = content.replace(old, new, 1)
    if new_content == content:
        raise MutationError("mutation produced no change (no-op)")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(new_content)
    return {
        "mutation_id": mutation_id,
        "tree": target_file,
        "mutation": description,
        "old": old,
        "new": new,
        "applied": True,
    }


def run_tests(workdir: str, command: List[str], timeout: int = 120) -> Dict[str, Any]:
    """Run a test command in workdir. Returns run record."""
    env = dict(os.environ)
    env.pop("GROQ_API_KEY", None)
    env.pop("GROQ_BASE_URL", None)
    env.pop("GITHUB_TOKEN", None)
    try:
        proc = subprocess.run(
            command, cwd=workdir, env=env, capture_output=True, text=True, timeout=timeout
        )
        return {
            "exit_code": proc.returncode,
            "output": (proc.stdout + proc.stderr)[-8000:],
        }
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "output": "TIMEOUT"}


def is_mutation_killed(run: Dict[str, Any]) -> bool:
    """A mutation is 'killed' when the test suite FAILS (exit code non-zero)."""
    return run.get("exit_code", 0) != 0


def main(argv: Optional[List[str]] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(description="moa-v2 cost-bounded mutation tester")
    parser.add_argument("--source", required=True, help="original tree (read-only)")
    parser.add_argument("--target-file", required=True)
    parser.add_argument("--old", required=True)
    parser.add_argument("--new", required=True)
    parser.add_argument("--description", default="mutation")
    parser.add_argument("--expected-tests-glob", default="*test*")
    parser.add_argument("--test-command", nargs="+", default=["python", "-m", "pytest", "-q"])
    parser.add_argument("--keep-under", help="optional parent dir to keep the worktree under")
    parser.add_argument("--output", default="")
    ns = parser.parse_args(args)

    # 1) snapshot original revision
    source_tree_rev = hash_tree(ns.source)
    # 2) immutable copy
    temp = tempfile.mkdtemp(prefix="moav2-mut-", dir=ns.keep_under) if ns.keep_under \
        else tempfile.mkdtemp(prefix="moav2-mut-")
    workdir = os.path.join(temp, "ws")
    snapshot(src=ns.source, dst=workdir)

    mutation_id = f"m-{source_tree_rev[:8]}"

    try:
        mutate = apply_mutation(
            workdir, target_file=ns.target_file, old=ns.old, new=ns.new,
            description=ns.description, mutation_id=mutation_id,
        )
        # ensure working copy still equals source: we only mutated the snapshot copy
        original_unchanged = (hash_tree(ns.source) == source_tree_rev)
        # Run tests against the mutated snapshot (mutation must be KILLED)
        run = run_tests(workdir, ns.test_command)
        record = {**mutate, "observed_failure": is_mutation_killed(run),
                  "test_exit_code": run["exit_code"], "test_output": run["output"],
                  "workspace_revision": hash_tree(workdir),
                  "origin_source_revision": source_tree_rev,
                  "original_tree_unchanged": original_unchanged}
    except MutationError as exc:
        record = {"mutation_id": mutation_id, "error": str(exc),
                  "original_tree_unchanged": True}
    finally:
        shutil.rmtree(temp, ignore_errors=True)

    if ns.output:
        with open(ns.output, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2)
    else:
        print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())