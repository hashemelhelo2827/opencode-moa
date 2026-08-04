# moa-v2 — Step B (you run, needs ADMIN + REBOOT)

Everything non-privileged (Step A) is built and green: Gate 1 44/44, unit tests 49/49,
Gate 2 code-side 3/3. These four steps require an **elevated (Admin) PowerShell** and, for
step 1, a **reboot** before proceeding.

> Note: this is the compliance drive. The Gates will re-check these; they cannot be faked
> from a non-elevated session. Open each shell below AS ADMINISTRATOR.

---

## 1. WSL2 (Admin shell + reboot)

In an **Admin PowerShell**:

```powershell
wsl --install
```

- Rebooting is required.
- Verify after reboot:

```powershell
wsl --status
wsl --list --online   # should list Linux distros
```

---

## 2. Docker Desktop (WSL2 backend)

1. Download from https://desktop.docker.com (Windows amd64, latest).
2. Run the installer; check **"Use WSL 2 instead of Hyper-V"** when prompted.
3. Restart Docker Desktop / Windows if asked (Settings → General → "Use the WSL 2 based engine").
4. Verify:

```powershell
docker version
docker run --rm hello-world
```

Gate C (runtime sandbox) and the mutation COW-isolation tests run on this Docker engine.
The `moa-runtime-verifier` agent runs only `docker run/exec/cp/rm/ps/images` inside a scoped
container; the spec requires copy-in, no network, RO fs, env scrubbing, and limits (enforced
by the sandbox wrapper, not this box).

---

## 3. Playwright browsers (for the Visual Gate)

```powershell
npx playwright install
npx playwright install-deps   # Windows: usually not needed; run if browser launch fails
```

`opencode.jsonc` already declares the Playwright MCP server:

```json
"mcp": { "playwright": { "type": "local", "command": ["npx", "@playwright/mcp@latest"] } }
```

---

## 4. Mistral API key (reviewer backend)

GitHub Models was **retired on 2026-07-30**, so the reviewer gates moved to **Mistral**
(`https://api.mistral.ai/v1`) — a hosted, OpenAI-compatible, permanently-free-no-credit-card
backend (Experiment tier, ~1B tokens/month per model). The high tier runs on
**mistral/mistral-medium-2604** (Mistral Medium 3.5) and the low tier on
**mistral/mistral-small-2603** (Mistral Small 4) (256k context / 256k output).

1. Create a free account at the [Mistral Console](https://console.mistral.ai/) (phone
   verification, no credit card).
2. Go to **API Keys** and generate a key.
3. Set the user env var:

```powershell
[System.Environment]::SetEnvironmentVariable('MISTRAL_API_KEY', 'YOUR-KEY', 'User')
```

Then **restart opencode** so the already-wired `{env:MISTRAL_API_KEY}` in `opencode.jsonc`
resolves. Verify the key with a live 1-token call against `mistral/mistral-small-2603`
before first use.

> The free tier caps at 50 RPM / 50K TPM per model (measured) and ~1B tokens/month, resetting monthly.
> Each reviewer pass must stay a single API call — the orchestrator pre-feeds file contents inline;
> batch-read via `Get-Content -Raw a,b,c` only when content was not supplied inline. If the reviewer
> hits the cap, the pipeline returns INCOMPLETE_REVIEW — never a silent model swap.

---

## 5. Final verification

After the above, in a NORMAL (non-admin) shell, re-run:

```powershell
cd ~\.config\opencode\skills\moa-v2\scripts
powershell -File .\test_moa_v2.ps1          # Gate 1 (44 checks)
powershell -File .\gate2_dry_run.ps1        # Gate 2 (providers + Docker)
```

Expected once WSL + Docker + Mistral key are live: **Gate 1 44/44, Gate 2 all code + Docker + the
Mistral provider probe PASS**, plus a successful live 1-token call against `mistral/mistral-small-2603`.
Then run the fallback benchmark `benchmark_reviewer.py run ... --memory ...` before first live use.