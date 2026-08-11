import contextlib
import io
import json

import pytest

from validate_flow import FlowRejected, main, validate


def _policy(**overrides):
    base = {
        "score": 0,
        "tier": "trivial",
        "required_gates": ["A", "B", "D", "E"],
        "gate_profiles": {"B": "light", "D": "light"},
        "required_tests": ["pytest-functional"],
        "required_tools": [],
    }
    base.update(overrides)
    return base


def _flow(**overrides):
    base = {
        "schema_version": 1,
        "flow_version": 1,
        "name": "test",
        "createdAt": "",
        "updatedAt": "",
        "project_revision_at_creation": "",
        "steps": [
            {"id": 0, "name": "Grill-me", "policy": "optional", "selected": True, "lose": "x"},
            {"id": 1, "name": "Optimize", "policy": "required", "selected": True, "lose": "x"},
            {"id": 2, "name": "Plan", "policy": "required", "selected": True, "lose": "x"},
            {"id": 3, "name": "Skills", "policy": "optional", "selected": True, "lose": "x"},
            {"id": 4, "name": "Delegate", "policy": "optional", "selected": True, "lose": "x"},
            {"id": 5, "name": "Synthesize", "policy": "required", "selected": True, "lose": "x"},
            {"id": 6, "name": "Test", "policy": "required", "selected": True, "lose": "x"},
            {"id": 7, "name": "Review", "policy": "required", "selected": True, "lose": "x"},
        ],
        "delegateModels": {"deepseek": True, "nemotron": True, "north": True,
                           "mimo": True, "bigpickle": True},
        "roles": {"deepseek": "reasoning/synthesis", "nemotron": "analysis",
                  "north": "structure", "mimo": "implementation", "bigpickle": "creative"},
        "synthesizer": "gemini35",
        "frontendSynthesis": True,
        "tests": [
            {"id": "pytest-functional", "stack": "python", "policy": "optional",
             "selected": True, "lose": "x", "locked": False},
        ],
        "tools": {"playwright": True, "docker": True, "mistral": True},
        "gates": {"A": True, "B": True, "C": True, "D": True, "E": True},
    }
    base.update(overrides)
    return base


def _step(flow, sid):
    return next(s for s in flow["steps"] if s["id"] == sid)


def test_valid_trivial_normalizes_and_locks_required():
    out = validate(_flow(), _policy())
    assert out["schema_version"] == 1
    for g in ["A", "B", "D", "E"]:
        assert out["gates"][g]["selected"] is True
        assert out["gates"][g]["locked"] is True
    assert out["gates"]["C"]["selected"] is True
    assert out["gates"]["C"]["locked"] is False


def test_required_gate_off_is_forced_on():
    flow = _flow()
    flow["gates"]["C"] = False
    out = validate(flow, _policy(required_gates=["A", "B", "C", "D", "E"]))
    assert out["gates"]["C"]["selected"] is True
    assert out["gates"]["C"]["locked"] is True


def test_user_required_selected_false_rejected():
    flow = _flow()
    _step(flow, 1)["selected"] = False  # Optimize: required + off
    with pytest.raises(FlowRejected):
        validate(flow, _policy())


def test_unknown_schema_version_rejected():
    flow = _flow()
    flow["schema_version"] = 2
    with pytest.raises(FlowRejected):
        validate(flow, _policy())


def test_malformed_json_rejected(tmp_path):
    raw = tmp_path / "raw.json"
    raw.write_text("{not json", encoding="utf-8")
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps(_policy()), encoding="utf-8")
    out = tmp_path / "out.json"
    rc = main([str(raw), str(policy), "-o", str(out)])
    assert rc == 2
    assert not out.exists()


def test_unknown_model_rejected():
    flow = _flow()
    flow["delegateModels"]["chatgpt"] = True
    with pytest.raises(FlowRejected):
        validate(flow, _policy())


def test_unknown_test_rejected():
    flow = _flow()
    flow["tests"].append({"id": "made-up", "selected": True})
    with pytest.raises(FlowRejected):
        validate(flow, _policy())


def test_unknown_gate_rejected():
    flow = _flow()
    flow["gates"]["F"] = True
    with pytest.raises(FlowRejected):
        validate(flow, _policy())


def test_duplicate_step_rejected():
    flow = _flow()
    flow["steps"].append(dict(flow["steps"][0]))
    with pytest.raises(FlowRejected):
        validate(flow, _policy())


def test_missing_required_gate_inserted():
    flow = _flow()
    del flow["gates"]["B"]
    out = validate(flow, _policy())  # trivial requires B
    assert out["gates"]["B"]["selected"] is True
    assert out["gates"]["B"]["locked"] is True


def test_two_plus_models_auto_include_delegate():
    flow = _flow()
    _step(flow, 4)["selected"] = False
    flow["delegateModels"] = {"deepseek": True, "nemotron": True, "north": False,
                              "mimo": False, "bigpickle": False}
    out = validate(flow, _policy())
    assert _step(out, 4)["selected"] is True


def test_single_model_drops_delegate():
    flow = _flow()
    flow["delegateModels"] = {"deepseek": True, "nemotron": False, "north": False,
                              "mimo": False, "bigpickle": False}
    out = validate(flow, _policy())
    assert _step(out, 4)["selected"] is False


def test_forbidden_step_selected_true_normalized_off():
    flow = _flow()
    flow["steps"][3] = {"id": 3, "name": "Skills", "policy": "forbidden",
                        "selected": True, "lose": "x"}
    out = validate(flow, _policy())
    assert _step(out, 3)["selected"] is False
    assert _step(out, 3)["locked"] is True


def test_input_not_mutated_after_normalize():
    flow = _flow()
    flow["gates"]["C"] = False
    before = json.dumps(flow, sort_keys=True)
    validate(flow, _policy(required_gates=["A", "B", "C", "D", "E"]))
    assert json.dumps(flow, sort_keys=True) == before
    assert flow["gates"]["C"] is False
