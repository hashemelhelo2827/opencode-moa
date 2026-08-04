#!/usr/bin/env python3
"""sandbox_run.py - Gate C runtime verifier for moa-v2.

Executes a whitelisted project command INSIDE an isolated Docker container and
returns RUNTIME evidence. Enforces the isolation contract from spec section 8:

    - copy-in:      project tree is COPIED into a temp dir; host tree is never run
    - no network:   `--network none`
    - read-only fs: `--read-only` + `--tmpfs /tmp`; only the copy is mounted rw at /work
    - env scrub:    only an allowlisted env subset is passed; secrets blocked
    - limits:       `--memory`, `--cpus`, `--pids-limit`, non-root `--user`
    - teardown:     container auto-removed (`--rm`) + temp copy deleted (finally)

The command string is validated against a strict allowlist BEFORE any container
starts. The `docker` executable is the ONLY execution path; this script is
"script, no LLM" and never reasons about pass/fail.

RUNTIME evidence schema (written to --output):
  {run_id, revision, command, exit_code, status, output, env}
  revision = deterministic sha256 over the copied tree.
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
import time
import uuid
from typing import Any, Dict, List, Optional

IMAGE = "moa-v2-sandbox"
WORKDIR = "/work"
CONTAINER_USER = "1000:1000"  # low-priv; image also declares a non-root user

# Secrets that must NEVER reach the container environment, even if inherited.
FORBIDDEN_ENV = {
    "GROQ_API_KEY", "GROQ_BASE_URL", "GITHUB_TOKEN", "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "AZURE_OPENAI_KEY",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
    "REPLICATE_API_TOKEN", "HF_TOKEN",
}
# Env vars that are SAFE to pass through verbatim. PATH is intentionally NOT
# passed: the Linux container has its own PATH and inheriting the Windows host
# PATH breaks exec lookups.
ALLOWED_ENV = {"LANG", "LC_ALL", "TZ", "NO_COLOR", "CI", "TERM"}

# Strict command allowlist (leading token).
ALLOWED_COMMANDS = (
    "python", "python3", "pytest", "bandit", "node", "npm",
    "pip", "pip3", "sh", "bash", "./",
)
# npm may only run OFFLINE (spec: npm audit MUST run --offline).
DISALLOWED_SUBSTRINGS = (
    "--registry ", "npm publish", "npm audit fix", " curl ", "wget ",
    " git clone ", "sudo ",
)
# Shell metacharacters are never permitted.
FORBIDDEN_TOKENS = (";", "&&", "||", ">", "<", "`", "$(", "${", "rm ", "|")

# Fixed seed / reproducibility flags the harness always sets.
NORMALISED_ENV = {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0", "HOME": WORKDIR}


class SandboxError(Exception):
    pass


def _ignore_dirs(dir_path: str, names: List[str]) -> List[str]:
    excluded = {".git", ".moa-v2", "node_modules", "__pycache__", ".venv", "venv",
                ".pytest_cache"}
    return [n for n in names if n in excluded]


def snapshot_tree(src: str, dst: str) -> str:
    """Copy src -> dst with common excludes. Returns dst."""
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst, symlinks=False, ignore=_ignore_dirs)
    return dst


def hash_tree(root: str) -> str:
    """Deterministic tree hash: sha256 over sorted rel paths + file digests."""
    h = hashlib.sha256()
    entries = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {"__pycache__", ".venv", "venv"}]
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
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


def scrub_env(host_env: Dict[str, str]) -> Dict[str, str]:
    """Return only the safe env subset to pass into the container."""
    out: Dict[str, str] = {}
    for key in ALLOWED_ENV:
        if key in host_env:
            out[key] = host_env[key]
    out.update(NORMALISED_ENV)
    return out


def split_command(command: str) -> List[str]:
    """Shlex-free split that rejects shell metacharacters outright."""
    argv = command.split()
    if not argv:
        raise SandboxError("empty command")
    for tok in argv:
        for bad in FORBIDDEN_TOKENS:
            if bad in tok:
                raise SandboxError(f"forbidden shell construct in command: {tok!r}")
        bare = tok.strip("'\"")
        if bare in ("rm", "del", "rmdir") or bare.startswith("rm -"):
            raise SandboxError(f"forbidden destructive command: {tok!r}")
    return argv


def validate(command: str) -> List[str]:
    """Pre-flight validation. Returns split argv. Raises SandboxError on rejection."""
    argv = split_command(command)
    first = argv[0]
    if first in ("python", "python3", "pytest", "bandit", "node", "npm", "pip", "pip3",
                 "sh", "bash", "./"):
        pass
    else:
        raise SandboxError(f"command not on the allowlist: {first!r}")
    for bad in DISALLOWED_SUBSTRINGS:
        if bad in command:
            raise SandboxError(f"command denied: forbidden substring {bad!r}")
    if first in ("npm",) and "--offline" not in command and "audit" in command:
        raise SandboxError("npm audit MUST run with --offline")
    return argv


def run_sandbox(
    source: str,
    *,
    command: str,
    image: str = IMAGE,
    memory: str = "512m",
    cpus: str = "2",
    pids_limit: str = "128",
    timeout: int = 600,
    keep_tree: bool = False,
    extra_env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Copy-in -> docker run -> capture evidence -> teardown."""
    argv = validate(command)
    extra_env = extra_env or {}
    for key in extra_env:
        if key in FORBIDDEN_ENV:
            raise SandboxError(f"refusing to pass forbidden env {key!r} into container")

    revision = hash_tree(source)
    run_id = f"{time.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    temp = tempfile.mkdtemp(prefix="moav2-sb-")
    copy_dir = os.path.join(temp, "ws")
    snapshot_tree(source, copy_dir)

    # Docker Desktop on Windows needs a Windows-style volume path.
    host_mount = os.path.abspath(copy_dir).replace("\\", "/")
    volume = f"{host_mount}:{WORKDIR}"

    # Pass the validated command to the container as a single argv element.
    inside = ["bash", "-c", "exec " + " ".join(f'"{a}"' for a in argv)]

    docker_args = [
        "docker", "run", "--rm",
        "--network", "none",
        "--read-only",
        "--tmpfs", "/tmp:rw,size=64m",
        "--user", CONTAINER_USER,
        "-m", memory,
        "--cpus", cpus,
        "--pids-limit", pids_limit,
        "-v", volume,
        "-w", WORKDIR,
    ]
    scrubbed = scrub_env(os.environ)
    scrubbed.update(extra_env)
    for key, val in scrubbed.items():
        docker_args.extend(["-e", f"{key}={val}"])
    docker_args.append(image)
    docker_args.extend(inside)

    joined = " ".join(docker_args)
    try:
        proc = subprocess.run(
            docker_args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "run_id": run_id,
            "revision": revision,
            "command": joined,
            "exit_code": proc.returncode,
            "status": "completed" if proc.returncode == 0 else "failed",
            "output": (proc.stdout + proc.stderr)[-20000:],
            "env": scrubbed,
        }
    except subprocess.TimeoutExpired:
        return {
            "run_id": run_id,
            "revision": revision,
            "command": joined,
            "exit_code": -1,
            "status": "timeout",
            "output": f"TIMEOUT after {timeout}s",
            "env": scrubbed,
        }
    finally:
        if not keep_tree:
            shutil.rmtree(temp, ignore_errors=True)


def main(argv: Optional[List[str]] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(description="moa-v2 Gate C sandbox runner")
    parser.add_argument("--source", required=True, help="project tree to copy in")
    parser.add_argument("--command", required=True, help="whitelisted command to run inside")
    parser.add_argument("--output", default="", help="write RUNTIME evidence JSON here")
    parser.add_argument("--image", default=IMAGE)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--keep-tree", action="store_true",
                        help="keep the temp copy (debug only; teardown=deleted)")
    ns = parser.parse_args(args)

    if not os.path.isdir(ns.source):
        raise SystemExit(f"source is not a directory: {ns.source}")

    try:
        record = run_sandbox(
            os.path.abspath(ns.source),
            command=ns.command,
            image=ns.image,
            timeout=ns.timeout,
            keep_tree=ns.keep_tree,
        )
    except SandboxError as exc:
        record = {"error": str(exc), "exit_code": 2, "command": ns.command,
                  "status": "rejected"}
    except Exception as exc:  # noqa: BLE001
        record = {"error": str(exc), "exit_code": 1, "command": ns.command,
                  "status": "error"}

    if ns.output:
        with open(ns.output, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2)
    else:
        print(json.dumps(record, indent=2))
    code = record.get("exit_code", 0)
    if code in (None, 0):
        return 0
    if isinstance(code, int) and code > 0:
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())