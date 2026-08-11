#!/usr/bin/env python3
"""validate_flow.py — policy-aware flow validator.

Input : raw flow JSON (from flow_menu.html or a saved flow; UNTRUSTED)
      + policy JSON (classify_complexity.py output; trusted)
Output: normalized effective flow (flow.json) that 00-flow.md is derived from.

STAGE 1 — SCHEMA REJECT (exit 2), reserved for malformed/invalid explicit user data:
  - malformed JSON
  - unknown schema_version (never silently migrate; only 1 accepted)
  - unknown step/model/test/tool/gate id
  - duplicate step ids
  - user-declared contradiction: policy:"required" + selected:false  → REJECT

STAGE 2 — POLICY NORMALIZE (never rejects, only upgrades):
  - policy-required gate/test/tool set to false or absent → forced selected:true + locked:true
  - policy-forbidden item user-selected true → forced selected:false + locked:true
    (forbidden user selections can never become executable)
  - delegate auto-include: >=2 models => step "4" on; <=1 => step "4" off (if optional)
  - required steps forced selected:true; forbidden steps forced selected:false

REJECT != best-effort. Missing policy-required items are INSERTED (not rejected),
so old saved flows upgrade when policy gains requirements — but always visible as locked.

Normalization decision table (normative):
  user explicitly declares {policy:"required", selected:false}  → REJECT (schema contradiction, Stage 1)
  policy-required but absent/false (stale/default flow)         → normalize → selected:true, locked:true
  user explicitly selects a policy:"forbidden" step             → normalize → selected:false, locked:true
  policy-forbidden absent                                       → stays off (no action)
  malformed JSON / unknown ids / duplicates / unknown schema    → REJECT

CLI: validate_flow.py <raw_flow.json> <policy.json> -o <effective.json>;
     exit 0 normalized, 2 rejected (message to stderr).

Known sets: steps {0..7}; models {deepseek,nemotron,north,mimo,bigpickle};
gates {A,B,C,D,E}; gate_profiles values in {light,full} (validated in policy, not in flow);
tools {playwright,docker,mistral}; tests from policy/Test Catalog.

Implementation note: deep-copy the input dict before normalizing (mutation-safety, tested in F13).
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from typing import Any, Dict, List

STEPS = {0, 1, 2, 3, 4, 5, 6, 7}
MODELS = {"deepseek", "nemotron", "north", "mimo", "bigpickle"}
TOOLS = {"playwright", "docker", "mistral"}
GATES = {"A", "B", "C", "D", "E"}
SYNTHESIZERS = {"gemini35", "gemini3", "deepseek", "none"}
TEST_CATALOG = {
    "pytest-functional", "bandit-security", "mutation",
    "node:test-functional", "npm-audit", "dom-behavior",
    "owasp-checklist", "playwright-visual",
}


class FlowRejected(Exception):
    """Stage 1 schema rejection — exit 2. Never a best-effort downgrade."""


def _step_id(value: Any) -> int:
    if isinstance(value, bool):
        raise FlowRejected(f"invalid step id: {value!r}")
    if isinstance(value, int):
        ival = value
    elif isinstance(value, str) and value.strip().isdigit():
        ival = int(value)
    else:
        raise FlowRejected(f"invalid step id: {value!r}")
    if ival not in STEPS:
        raise FlowRejected(f"unknown step id: {ival}")
    return ival


def _get_selected(entry: Any) -> bool:
    if isinstance(entry, bool):
        return entry
    if isinstance(entry, dict):
        val = entry.get("selected")
        if val is None:
            return False
        return bool(val)
    return bool(entry)


def _stage1_schema(flow: Dict[str, Any]) -> None:
    if flow.get("schema_version") != 1:
        raise FlowRejected(
            f"unknown schema_version: {flow.get('schema_version')!r} (only 1 accepted; never migrate)"
        )

    steps = flow.get("steps")
    if not isinstance(steps, list):
        raise FlowRejected("flow.steps must be a list")
    seen: List[int] = []
    for entry in steps:
        if not isinstance(entry, dict):
            raise FlowRejected(f"step entry must be an object: {entry!r}")
        sid = _step_id(entry.get("id"))
        if sid in seen:
            raise FlowRejected(f"duplicate step id: {sid}")
        seen.append(sid)
        policy = entry.get("policy", "optional")
        if policy not in ("required", "optional", "forbidden"):
            raise FlowRejected(f"step {sid}: unknown policy {policy!r}")
        if policy == "required" and _get_selected(entry) is False:
            raise FlowRejected(
                f"step {sid}: user-declared contradiction — policy:required + selected:false"
            )

    models = flow.get("delegateModels")
    if not isinstance(models, dict):
        raise FlowRejected("flow.delegateModels must be an object")
    for mid in models:
        if mid not in MODELS:
            raise FlowRejected(f"unknown model: {mid}")

    synth = flow.get("synthesizer")
    if synth is not None and synth not in SYNTHESIZERS:
        raise FlowRejected(f"unknown synthesizer: {synth!r}")

    tools = flow.get("tools")
    if not isinstance(tools, dict):
        raise FlowRejected("flow.tools must be an object")
    for tid in tools:
        if tid not in TOOLS:
            raise FlowRejected(f"unknown tool: {tid}")

    gates = flow.get("gates")
    if not isinstance(gates, dict):
        raise FlowRejected("flow.gates must be an object")
    for gid in gates:
        if gid not in GATES:
            raise FlowRejected(f"unknown gate: {gid}")

    tests = flow.get("tests")
    if not isinstance(tests, list):
        raise FlowRejected("flow.tests must be a list")
    for entry in tests:
        if not isinstance(entry, dict):
            raise FlowRejected(f"test entry must be an object: {entry!r}")
        tid = entry.get("id")
        if tid not in TEST_CATALOG:
            raise FlowRejected(f"unknown test: {tid!r}")
        policy = entry.get("policy", "optional")
        if policy == "required" and _get_selected(entry) is False:
            raise FlowRejected(
                f"test {tid}: user-declared contradiction — policy:required + selected:false"
            )


def _lock_gate(gates: Dict[str, Any], gid: str, required: bool) -> None:
    if gid not in gates:
        gates[gid] = {"selected": True, "locked": required}
        return
    gates[gid] = {
        "selected": True if required else bool(_get_selected(gates[gid])),
        "locked": required,
    }


def _lock_tool(tools: Dict[str, Any], tid: str, required: bool) -> None:
    if tid not in tools:
        tools[tid] = {"selected": True, "locked": required}
        return
    tools[tid] = {
        "selected": True if required else bool(_get_selected(tools[tid])),
        "locked": required,
    }


def _lock_test(tests: List[Dict[str, Any]], tid: str, required: bool) -> None:
    for entry in tests:
        if entry.get("id") == tid:
            entry["selected"] = True if required else bool(_get_selected(entry))
            entry["locked"] = required
            if required:
                entry["policy"] = "required"
            return
    tests.append({"id": tid, "selected": True, "locked": required,
                  "policy": "required" if required else "optional"})


def _stage2_policy(flow: Dict[str, Any], policy: Dict[str, Any]) -> None:
    required_gates = list(policy.get("required_gates") or [])
    required_tests = list(policy.get("required_tests") or [])
    required_tools = list(policy.get("required_tools") or [])

    for entry in flow["steps"]:
        sid = _step_id(entry.get("id"))
        p = entry.get("policy", "optional")
        if p == "required":
            entry["selected"] = True
            entry["locked"] = True
        elif p == "forbidden":
            entry["selected"] = False
            entry["locked"] = True
        else:
            entry["selected"] = bool(entry.get("selected", False))
            entry.setdefault("locked", False)

    model_count = sum(1 for mid in MODELS if flow["delegateModels"].get(mid))
    step4 = next((e for e in flow["steps"] if _step_id(e.get("id")) == 4), None)
    if model_count >= 2:
        if step4 is None:
            flow["steps"].append({"id": 4, "name": "Delegate", "policy": "optional",
                                  "selected": True, "locked": False})
        elif step4.get("policy") != "forbidden" and step4["selected"] is False:
            step4["selected"] = True
    elif model_count <= 1 and step4 is not None:
        if step4.get("policy") == "optional" and step4["selected"] is True:
            step4["selected"] = False

    gates = flow["gates"]
    for gid in GATES:
        _lock_gate(gates, gid, required=(gid in required_gates))

    tools = flow["tools"]
    for tid in TOOLS:
        _lock_tool(tools, tid, required=(tid in required_tools))

    tests = flow["tests"]
    for tid in required_tests:
        _lock_test(tests, tid, required=True)


def validate(raw: Dict[str, Any], policy: Dict[str, Any]) -> Dict[str, Any]:
    """Validate + normalize a raw flow against policy. Raises FlowRejected."""
    flow = copy.deepcopy(raw)
    _stage1_schema(flow)
    _stage2_policy(flow, policy)
    return flow


def _load_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise FlowRejected(f"malformed JSON in {path}: {exc}")
    if not isinstance(data, dict):
        raise FlowRejected(f"{path}: expected a JSON object")
    return data


def main(argv: List[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(description="moa-v2 policy-aware flow validator")
    parser.add_argument("raw_flow")
    parser.add_argument("policy")
    parser.add_argument("-o", "--output", required=True)
    ns = parser.parse_args(args)

    try:
        raw = _load_json(ns.raw_flow)
        policy = _load_json(ns.policy)
        effective = validate(raw, policy)
    except FlowRejected as exc:
        print(f"REJECTED: {exc}", file=sys.stderr)
        return 2

    with open(ns.output, "w", encoding="utf-8") as fh:
        json.dump(effective, fh, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
