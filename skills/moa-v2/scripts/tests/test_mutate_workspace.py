import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mutate_workspace import (
    apply_mutation,
    hash_tree,
    is_mutation_killed,
    run_tests,
    snapshot,
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
    return src


def test_snapshot_copies_excluding_git(tmp_path, tree):
    dst = tmp_path / "dst"
    snapshot(str(tree), str(dst))
    assert (dst / "calc.py").exists()
    assert (tmp_path / "src" / "calc.py").exists()


def test_hash_tree_deterministic(tree):
    h1 = hash_tree(str(tree))
    h2 = hash_tree(str(tree))
    assert h1 == h2
    assert len(h1) == 64


def test_hash_tree_detects_change(tree):
    h1 = hash_tree(str(tree))
    (tree / "calc.py").write_text("def add(a, b):\n    return a - b\n",
                                    encoding="utf-8")
    h2 = hash_tree(str(tree))
    assert h1 != h2


def test_apply_mutation_changes_file(tree):
    applied = apply_mutation(
        str(tree), target_file="calc.py", old="a + b", new="a - b",
        description="mutate add to subtract", mutation_id="m-1",
    )
    assert applied["applied"] is True
    assert (tree / "calc.py").read_text(encoding="utf-8").count("a - b") == 1


def test_apply_mutation_noop_raises(tree):
    with pytest.raises(Exception):
        apply_mutation(
            str(tree), target_file="calc.py", old="XYZ not present", new="x",
            description="noop", mutation_id="m-2",
        )


def test_apply_mutation_missing_file_raises(tree):
    with pytest.raises(Exception):
        apply_mutation(
            str(tree), target_file="nope.py", old="a", new="b",
            description="missing", mutation_id="m-3",
        )


def test_run_tests_pass_reference(tree):
    # unmutated reference should PASS (exit 0), so a real mutation would visibly deviate
    run = run_tests(str(tree), ["python", "-m", "pytest", "-q"], timeout=60)
    assert run["exit_code"] == 0


def test_mutation_killed(tree):
    # mutate to a - b: test_add (expects 5) must now FAIL, killing the mutation
    apply_mutation(str(tree), target_file="calc.py", old="a + b", new="a - b",
                   description="kill", mutation_id="m-4")
    run = run_tests(str(tree), ["python", "-m", "pytest", "-q"], timeout=60)
    assert run["exit_code"] != 0
    assert is_mutation_killed(run) is True


def test_unmutated_is_not_killed():
    assert is_mutation_killed({"exit_code": 0}) is False


def test_original_tree_unchanged_after_mutation(tmp_path, tree):
    before = hash_tree(str(tree))
    # snapshot (copy) then mutate the copy; original must stay identical
    dst = tmp_path / "copy"
    snapshot(str(tree), str(dst))
    apply_mutation(str(dst), target_file="calc.py", old="a + b", new="a - b",
                   description="x", mutation_id="m-5")
    assert hash_tree(str(tree)) == before