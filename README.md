# opencode-moa — moa-v2

An **evidence-based build pipeline** for [opencode](https://opencode.ai). moa-v2 orchestrates 10 sub-agents to build complete deliverables (web / app / analysis) in the current working directory and proves correctness through a deterministic, 5-gate review pipeline.

> **Core invariant:** no model opinion can issue PASS. PASS is the output of the Python verdict engine (`verdict_engine.py`) applied to typed evidence bound to a hashed revision.

## How it works

```mermaid
flowchart TD
    A["User brief (original text preserved)"] --> B["0. Grill-me
        design-tree interview (6 rounds / 25 Q cap)"]
    B --> C["1. Optimize (prompt-optimizer)
        tag task_type + needs_frontend_synthesis"]
    C --> D["2. Plan (decompose-plan)
        tasks + measurable criteria blocking/major/minor"]
    D --> E["3. Skills (skill-finder-stacker)
        discover + vet candidates (UNTRUSTED)"]
    E -- "rejections" --> P["pause checkpoint"]
    P --> F
    E -- "no rejections" --> F
    F["4. Delegate 5 agents in parallel
        DeepSeek Nemotron North Mimo BigPickle"] --> G["5a. Plan (Gemini 3.5 → 3 → DeepSeek)
        frontend design plan only"]
    G --> H["5b. Implement (DeepSeek, unlimited)
        writes files to working tree"]
    H --> I["6. Test (test-script-maker)
        pytest / node:test / DOM, in Docker sandbox"]
    I --> J["7. Review: 5 gates
        A semantic | B static (Mistral lo/hi)
        C Docker runtime | D adversarial | E verdict (Python)"]
    J --> K["Visual gate (Playwright, frontend only)"]
    K --> L{"Verdict engine (Python)"}
    L -- "PASS" --> M["Done"]
    L -- "FAIL" --> N["fix → re-run full suite"]
    N --> I
```

## Workflow Authority (user-selectable flow)

Flow = execution preference. Policy = immutable requirement. Flow drops execution, never a requirement.

At run start the orchestrator either shows the **flow menu** (Mode 1 flowchart via Playwright, or Mode 2 terminal picker) or auto-proceeds with the default full set. A project-flow auto-detect always runs: if `<project>/.moa-v2/workflow/flow.json` exists, the user is asked whether to reuse it (with a staleness warning via `project_revision_at_creation`).

- **Five toggle panels** — Steps (0–7), Models, Tests, Tools, Gates. Every row is a toggle with a "you lose if off" line. Policy-required items are forced `selected:true + locked:true` and shown as "Locked by policy"; user-declared contradictions (`policy:"required"` + `selected:false`) are **REJECTED**.
- **Gate IDs are always A–E.** B-light/D-light are `gate_profiles` (depth floors), never gate IDs.
- **Saved-flow picker** — global saved flows in `skills/moa-v2/saved-flows/*.json` (timestamps stored inside the file, never in the filename), with SVG preview + `window.__seedFlow` hydration.

Policy is enforced by `classify_complexity.py` (emits `required_gates` / `gate_profiles` / `required_tests` / `required_tools`) and `validate_flow.py` (the only browser→run gate; schema REJECT vs policy normalize+lock). The orchestrator builds the review package with `gates_required = policy.required_gates` — NEVER from `00-flow.md`.

## Flow editor (`flow_menu.html`)

Mode 1 opens the flowchart editor in the browser (Playwright). You edit the flow live on a canvas:

- **Rename the flow** — editable name field in the header (timestamps are read-only, stored in the file).
- **Toggle steps on/off** — the power (⏻) icon on each node enables/disables it. Optional steps toggle freely; `policy:required` steps show a 🔒 **Locked by policy** badge and cannot be turned off.
- **Reorder steps** — drag a node onto another to insert it before it, or use the inspector **↑ Move up / ↓ Move down** buttons (also ArrowUp / ArrowDown keys).
- **Undo / Redo** — `↶ Undo` (Ctrl+Z) and `↷ Redo` (Ctrl+Shift+Z) against a full history stack.
- **Presets** — Full / Minimal / Security-hardened drop-down to apply a starting configuration.
- **Configure everything** — sidebar checkboxes for delegate models, tests (filtered by stack), tools, and gates; a synthesizer picker; and a frontend-synthesis toggle.
- **Canvas navigation** — pan by dragging empty space, zoom with scroll / `+` `−` / `1:1` / **Fit**, plus auto-layout and a minimap. Selecting a node opens an inspector with its policy, state, "you lose if off" line, and linked gates.
- **Export** — live SVG and JSON textareas mirror the state (`window.__flowResult`).

The editor's output is **untrusted** — every flow is validated by `validate_flow.py` before the run starts.

## Team

| Agent | Model | Role |
|---|---|---|
| @moa-v2 | opencode/deepseek-v4-flash-free | Orchestrator (primary) |
| @moa-deepseek | opencode/deepseek-v4-flash-free | Reasoning, plan synthesis, implementation (writes files) |
| @moa-nemotron | opencode/nemotron-3-ultra-free | Analysis, edge cases, optimization |
| @moa-north | opencode/mimo-v2.5-free | Code structure analysis & review |
| @moa-mimo | opencode/mimo-v2.5-free | Programming & implementation |
| @moa-bigpickle | opencode/big-pickle | Creative direction & brainstorming |
| @moa-gemini35 | google/gemini-3.5-flash | Frontend/UI/UX plan (primary, plan only) |
| @moa-gemini3 | google/gemini-3-flash | Frontend/UI/UX plan (fallback, plan only) |
| @moa-mistral-reviewer | mistral/mistral-small-2603 | Gate A + E1 + structure passes (lo tier) |
| @moa-mistral-reviewer-hi | mistral/mistral-medium-2604 | Gate B module/security passes (hi tier) |
| @moa-runtime-verifier | script (no LLM) | Gate C Docker runtime execution |

## Five-Gate Review

Gate models never write to the working tree (`edit: deny`).

- **Gate A (semantic coverage)** — @moa-mistral-reviewer. Did the criteria drop/weaken any explicit or implicit requirement in the original text?
- **Gate B (static, staged)** — structure pass (lo) then module/security passes (hi). Operates on the hashed tree.
- **Gate C (runtime)** — @moa-runtime-verifier runs commands only inside a Docker sandbox: copy-in, no network, read-only fs, env scrubbed, resource limits, non-root, teardown.
- **Gate D (adversarial)** — isolated @moa-deepseek writes negative/boundary tests before reading existing tests; mutation tests on a COW snapshot.
- **Gate E (verdict)** — E1 normalizes all reports into one JSON (evidence references artifact IDs only); E2 runs `verdict_engine.py` locally (no LLM). The model writes a summary only; it cannot override the verdict.

For **frontend / complex** tasks a **visual gate** runs via Playwright MCP: screenshots at 375x812, 768x1024, 1440x900 + interactive states, plus programmatic checks. DOM tests alone never grant frontend PASS.

## Requirements

- [opencode](https://opencode.ai)
- Python 3.14+ (for the verdict engine, unit tests, and sandbox runner)
- Docker Desktop with WSL2 backend (Gate C + mutation isolation)
- Playwright browsers (visual gate + flow menu): `npx playwright install`

## Install

1. **Copy the agents** into your opencode config:

   ```powershell
   Copy-Item -Recurse agents\* ~\.config\opencode\agents\
   ```

2. **Copy the skill family**:

   ```powershell
   Copy-Item -Recurse skills\moa-v2 ~\.config\opencode\skills\
   ```

3. **Merge the config** — take `config/opencode.jsonc.example` and merge the `mcp.playwright` block, the `provider.mistral` block, and the `moa-*` agent definitions into your existing `opencode.jsonc`.

4. **API keys** (all via env vars — no literals in the repo):

   - `MISTRAL_API_KEY` — reviewer backend ([Mistral console](https://console.mistral.ai/), free Experiment tier, no credit card):
     ```powershell
     [System.Environment]::SetEnvironmentVariable('MISTRAL_API_KEY', 'YOUR-KEY', 'User')
     ```
   - `GOOGLE_API_KEY` / Gemini — for the @moa-gemini35/3 plan authors (free tier, ~1400 RPD).
   - opencode Zen / DeepSeek — for the orchestrator, @moa-deepseek, and the 5 parallel agents.

5. **Restart opencode** so the `{env:MISTRAL_API_KEY}` reference resolves.

## Usage

Invoke the `@moa-v2` agent with your brief. Auto-mode is the default (states assumptions and proceeds); interactive checkpoints exist for the Step 0 grill-me interview (when `grill_me: true`), skill rejections, destructive commands, out-of-reach complexity, and context pressure. `grill_me: false` skips the interview only — it does not make a run fully automated.

## Rate limits & quota

- **Mistral free tier:** 50 RPM / 50K TPM per model (measured), ~1B tokens/month, resets monthly. Each reviewer pass must stay a single API call — the orchestrator pre-feeds file contents inline; batch-read via `Get-Content -Raw a,b,c` only when content was not supplied inline. On 429: `Start-Sleep -Seconds 5` then retry.
- **Gemini:** ~1400 RPD / ~10 RPM per model → **plan authoring only**; implementation always goes to @moa-deepseek (unlimited).
- **Fail-closed:** a missing required gate → `INCOMPLETE_REVIEW`, never PASS. If Mistral is down and the fallback reviewer is not benchmark-passed → `INCOMPLETE_REVIEW`, never a silent swap.

## Verification

```powershell
cd skills\moa-v2\scripts
powershell -File .\test_moa_v2.ps1        # Gate 1 harness (97 checks)
powershell -File .\gate2_dry_run.ps1      # Gate 2 (providers + Docker)
python -m pytest tests -q                 # unit tests (81 tests)
```

## Layout

```
agents/                      9 agent definitions (moa-v2 + team)
skills/moa-v2/               skill family
  grill-me/                  Step 0 — design-tree interview
  prompt-optimizer/          Step 1 — brief + task_type tags
  decompose-plan/            Step 2 — tasks + measurable criteria
  skill-finder-stacker/      Step 3 — skill discovery + vetting
  test-script-maker/         Step 6 — test matrix + scripts
  scripts/                   root-of-trust Python + PS1 scripts
    flow_menu.html           flowchart editor (Mode 1) — edit + SVG/JSON export
    validate_flow.py         browser→run gate: schema REJECT / policy normalize
    classify_complexity.py   complexity scaling + policy requirement sets
    verdict_engine.py        authoritative verdict (no LLM)
    build_review_package.py  build the typed review package
    mutate_workspace.py      COW mutation tests
    benchmark_reviewer.py    fallback-reviewer benchmark
    sandbox/                 Docker sandbox (Gate C)
  MOA_V2_MEMORY.md           budget counters + catalogs + workflow authority
  LESSONS.md                 append-only lessons
config/opencode.jsonc.example  trimmed provider + agent + Playwright MCP config
```
