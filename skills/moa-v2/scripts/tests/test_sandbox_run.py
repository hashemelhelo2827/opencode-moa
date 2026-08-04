import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sandbox"))

from sandbox_run import (  # noqa: E402
    FORBIDDEN_ENV,
    SandboxError,
    hash_tree,
    run_sandbox,
    scrub_env,
    snapshot_tree,
    split_command,
    validate,
)


@pytest.fixture
def tree(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (src / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    (src / ".moa-v2").mkdir()
    (src / ".moa-v2" / "secret.md").write_text("internal", encoding="utf-8")
    return src


def test_split_command_rejects_shell_metachars():
    with pytest.raises(SandboxError):
        split_command("python -c 'x; rm -rf /'")


def test_validate_rejects_non_allowlisted():
    with pytest.raises(SandboxError):
        validate("powershell -Command whoami")


def test_validate_rejects_rm():
    with pytest.raises(SandboxError):
        validate("bash -c 'rm -rf /tmp/foo'")


def test_validate_requires_offline_npm_audit():
    with pytest.raises(SandboxError):
        validate("npm audit")
    argv = validate("npm audit --offline")
    assert argv[0] == "npm"


def test_validate_allows_pytest():
    assert validate("pytest -q")[0] == "pytest"


def test_scrub_env_blocks_secrets():
    host = {"GROQ_API_KEY": "sk-secret", "PATH": "C:/bin", "CI": "1"}
    out = scrub_env(host)
    assert "GROQ_API_KEY" not in out
    assert out.get("CI") == "1"
    assert out.get("PYTHONHASHSEED") == "0"


def test_forbidden_env_cannot_be_passed(monkeypatch, tree):
    monkeypatch.setattr("sandbox_run.subprocess.run", lambda *a, **k: None)
    with pytest.raises(SandboxError):
        run_sandbox(str(tree), command="pytest -q", extra_env={"GROQ_API_KEY": "x"})


def test_snapshot_excludes_moa_v2_and_git(tree, tmp_path):
    dst = tmp_path / "dst"
    snapshot_tree(str(tree), str(dst))
    assert (dst / "calc.py").exists()
    assert not (dst / ".moa-v2").exists()


def test_hash_tree_deterministic_and_revision(tree):
    h1 = hash_tree(str(tree))
    assert len(h1) == 64
    assert hash_tree(str(tree)) == h1


def test_run_sandbox_builds_docker_args_with_isolation(monkeypatch, tree):
    captured = {}

    def fake_run(args, capture_output, text, timeout):
        captured["args"] = args
        class P:
            returncode = 0
            stdout = "ok\n"
            stderr = ""
        return P()

    monkeypatch.setattr("sandbox_run.subprocess.run", fake_run)
    record = run_sandbox(str(tree), command="pytest -q")
    args = captured["args"]
    assert "--network" in args and "none" in args
    assert "--read-only" in args
    assert "--tmpfs" in args
    assert "--user" in args and "1000:1000" in args
    assert "-m" in args and "--cpus" in args and "--pids-limit" in args
    assert any(a.endswith("/work") for a in args)  # volume mount to /work
    assert record["exit_code"] == 0
    assert record["status"] == "completed"
    assert len(record["revision"]) == 64
    assert "GROQ_API_KEY" not in record["env"]


def test_run_sandbox_rejects_before_container(monkeypatch, tree):
    called = []

    def fake_run(*a, **k):
        called.append(True)

    monkeypatch.setattr("sandbox_run.subprocess.run", fake_run)
    with pytest.raises(SandboxError):
        run_sandbox(str(tree), command="wget http://evil")
    assert called == []


def test_run_sandbox_timeout(monkeypatch, tree):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="docker", timeout=1)

    monkeypatch.setattr("sandbox_run.subprocess.run", boom)
    record = run_sandbox(str(tree), command="pytest -q", timeout=1)
    assert record["exit_code"] == -1
    assert record["status"] == "timeout"
