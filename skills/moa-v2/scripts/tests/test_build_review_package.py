import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from build_review_package import build, hash_tree, sha256_file


def _artifact(aid, path):
    return {
        "artifact_id": aid,
        "type": "STATIC",
        "sha256": sha256_file(path),
        "created_by": "gate-b",
        "revision": "abc123",
        "criterion_ids": ["C-01"],
    }


def test_build_merges_reports(tmp_path):
    src = tmp_path / "src.txt"
    src.write_text("content", encoding="utf-8")
    art = _artifact("a1", str(src))
    reports = [{
        "criteria": [
            {"criterion_id": "C-01", "severity": "blocking",
             "status": "VERIFIED", "evidence": ["a1"]}
        ]
    }]
    pkg = build(
        reports=reports, artifacts=[art],
        gates_executed=["A", "B", "C", "D", "E"],
        gates_required=["A", "B", "C", "D", "E"],
        reviewed_revision="abc123",
    )
    assert pkg["criteria"][0]["criterion_id"] == "C-01"
    assert "a1" in pkg["artifacts"]


def test_build_rejects_missing_artifact(tmp_path):
    src = tmp_path / "src.txt"
    src.write_text("x", encoding="utf-8")
    reports = [{
        "criteria": [
            {"criterion_id": "C-01", "severity": "blocking",
             "status": "VERIFIED", "evidence": ["missing"]}
        ]
    }]
    with pytest.raises(ValueError):
        build(
            reports=reports, artifacts=[_artifact("a1", str(src))],
            gates_executed=[], gates_required=[],
            reviewed_revision="abc123",
        )


def test_build_rejects_duplicate_artifact_ids(tmp_path):
    src = tmp_path / "src.txt"
    src.write_text("x", encoding="utf-8")
    a = _artifact("a1", str(src))
    with pytest.raises(ValueError):
        build(
            reports=[], artifacts=[a, {**a}],
            gates_executed=[], gates_required=[],
            reviewed_revision="abc123",
        )


def test_hash_tree_deterministic(tmp_path):
    (tmp_path / "b.txt").write_text("bb", encoding="utf-8")
    (tmp_path / "a.txt").write_text("aa", encoding="utf-8")
    h1 = hash_tree(str(tmp_path), ignore=[])
    h2 = hash_tree(str(tmp_path), ignore=[])
    assert h1 == h2
    assert len(h1) == 64


def test_hash_tree_changes_on_content(tmp_path):
    (tmp_path / "a.txt").write_text("aa", encoding="utf-8")
    h1 = hash_tree(str(tmp_path), ignore=[])
    (tmp_path / "a.txt").write_text("zz", encoding="utf-8")
    h2 = hash_tree(str(tmp_path), ignore=[])
    assert h1 != h2


def test_hash_tree_respects_ignore(tmp_path):
    (tmp_path / "keep.txt").write_text("k", encoding="utf-8")
    (tmp_path / ".moa-v2").mkdir()
    (tmp_path / ".moa-v2" / "junk.txt").write_text("j", encoding="utf-8")
    h1 = hash_tree(str(tmp_path), ignore=[".moa-v2"])
    (tmp_path / ".moa-v2" / "junk.txt").write_text("J2", encoding="utf-8")
    h2 = hash_tree(str(tmp_path), ignore=[".moa-v2"])
    assert h1 == h2


def test_build_roundtrip_json(tmp_path):
    src = tmp_path / "src.txt"
    src.write_text("content", encoding="utf-8")
    art = _artifact("a1", str(src))
    pkg = build(
        reports=[{"criteria": [
            {"criterion_id": "C-01", "severity": "major",
             "status": "VERIFIED", "evidence": ["a1"]}
        ]}],
        artifacts=[art], gates_executed=["E"], gates_required=["E"],
        reviewed_revision="rev1",
    )
    dumped = json.dumps(pkg)
    reloaded = json.loads(dumped)
    assert reloaded["reviewed_revision"] == "rev1"