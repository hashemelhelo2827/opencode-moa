import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from classify_complexity import classify, classify_paths, MAX_SCORE


def test_trivial_plain():
    r = classify(features=set(), source_file_count=2, runtime_count=1, has_db=False)
    assert r["tier"] == "trivial"
    assert r["score"] == 0


def test_standard():
    r = classify(features={"ui", "auth"}, source_file_count=2)
    assert r["score"] == 4
    assert r["tier"] == "standard"


def test_complex():
    r = classify(
        features={"ui", "auth", "untrusted_input", "external_api", "concurrency",
                  "destructive_migration", "security_sensitive"},
        source_file_count=12,
        runtime_count=2,
        has_db=True,
    )
    assert r["score"] == 7 * 2 + 3 * 1
    assert r["score"] == MAX_SCORE
    assert r["tier"] == "complex"


def test_blocking_security_forces_standard():
    r = classify(features=set(), source_file_count=1, blocking_security=True)
    assert r["tier"] == "standard"
    assert r["score"] == 0  # tier forced, score unchanged


def test_single_file_sensitive_never_trivial():
    r = classify(features=set(), source_file_count=1, is_single_file=True,
                 file_path="auth_middleware.py")
    assert r["tier"] == "standard"


def test_single_file_plain_can_be_trivial():
    r = classify(features=set(), source_file_count=1, is_single_file=True,
                 file_path="hello.py")
    assert r["tier"] == "trivial"


def test_runtime_count_detection():
    files = ["a.py", "b.py", "index.html", "app.js"]
    r = classify_paths(files, features=set())
    assert r["runtime_count"] >= 2  # python, web/node
    assert r["source_file_count"] == 4


def test_more_than_10_files_adds_point():
    r = classify(features=set(), source_file_count=11, runtime_count=1)
    assert r["score"] == 1
    assert r["tier"] == "trivial"  # 1 point still trivial


def test_threshold_boundaries():
    assert classify(features=set(), source_file_count=1)["tier"] == "trivial"  # 0
    assert classify(features={"ui"})["tier"] == "trivial"  # 2
    assert classify(features={"ui", "auth"})["tier"] == "standard"  # 4
    assert classify(features={"ui", "auth"}, source_file_count=20)["tier"] == "standard"  # 5
    assert classify(features={"ui", "auth", "concurrency"})["tier"] == "complex"  # 6
    assert classify(features={"ui", "auth", "concurrency", "untrusted_input"})["tier"] == "complex"  # 8


def test_trivial_required_policy():
    r = classify(features=set(), source_file_count=2, runtime_count=1, has_db=False)
    assert r["required_gates"] == ["A", "B", "D", "E"]
    assert r["gate_profiles"] == {"B": "light", "D": "light"}
    assert r["required_tests"] == ["pytest-functional"]
    assert r["required_tools"] == []


def test_standard_required_policy():
    r = classify(features={"ui", "auth"}, source_file_count=2)
    assert r["required_gates"] == ["A", "B", "C", "D", "E"]
    assert r["gate_profiles"] == {}
    assert "bandit-security" in r["required_tests"]
    assert "docker" in r["required_tools"]


def test_complex_required_policy():
    r = classify(features={"ui", "auth", "untrusted_input", "external_api",
                           "concurrency", "destructive_migration", "security_sensitive"},
                 source_file_count=12, runtime_count=2, has_db=True)
    assert r["required_gates"] == ["A", "B", "C", "D", "E"]
    assert "mutation" in r["required_tests"]
    assert "playwright" in r["required_tools"]


def test_blocking_security_adds_bandit():
    r = classify(features=set(), source_file_count=1, blocking_security=True)
    assert r["tier"] == "standard"
    assert "bandit-security" in r["required_tests"]


def test_ui_adds_playwright():
    r = classify(features={"ui"}, source_file_count=1)
    assert "playwright-visual" in r["required_tests"]
    assert "playwright" in r["required_tools"]


def test_required_lists_are_copies():
    r = classify(features=set(), source_file_count=1)
    r["required_gates"].append("X")
    r["required_tests"].append("X")
    r["required_tools"].append("X")
    r["gate_profiles"]["B"] = "full"
    r2 = classify(features=set(), source_file_count=1)
    assert "X" not in r2["required_gates"]
    assert "X" not in r2["required_tests"]
    assert "X" not in r2["required_tools"]
    assert r2["gate_profiles"] == {"B": "light", "D": "light"}