# moa-v2 Gate 1 — install-time compliance harness
# Verifies the moa-v2 implementation matches the final spec, clause by clause.
# Usage:  .\test_moa_v2.ps1  [-Unit] [-Config] [-Integration] [-All]
param(
    [switch]$Unit,
    [switch]$Config,
    [switch]$Integration,
    [switch]$All
)

$pass = 0
$fail = 0
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$skillRoot = Split-Path $scriptDir -Parent           # skills\moa-v2
$skillsDir = Split-Path $skillRoot -Parent          # skills
$opencodeDir = Split-Path $skillsDir -Parent        # .config\opencode
$configDir = $opencodeDir

# Prefer the Windows MSI python (has pytest); fall back to any `python`.
$python = "python"
if (Test-Path "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe") {
    $python = "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe"
}

if (-not ($Unit -or $Config -or $Integration -or $All)) { $All = $true }

function Test-Step($name, $scriptBlock) {
    try {
        & $scriptBlock
        Write-Host "  PASS: $name" -ForegroundColor Green
        $script:pass++
        return $true
    } catch {
        Write-Host "  FAIL: $name`n    $_" -ForegroundColor Red
        $script:fail++
        return $false
    }
}

Write-Host "`n===== moa-v2 Gate 1 =====" -ForegroundColor Cyan

# ---------------------------------------------------------------
# Config checks
# ---------------------------------------------------------------
if ($Config -or $All) {
    Write-Host "`n=== Config ===" -ForegroundColor Cyan
    $configPath = Join-Path $opencodeDir "opencode.jsonc"

    Test-Step "opencode.jsonc exists" {
        if (-not (Test-Path $configPath)) { throw "Missing opencode.jsonc" }
    }

    if (Test-Path $configPath) {
        $json = Get-Content $configPath -Raw

        Test-Step "mistral provider declared" {
            if ($json -notmatch '"mistral"') { throw "provider mistral missing" }
            if ($json -notmatch 'MISTRAL_API_KEY') { throw "bad apiKey (must use env:MISTRAL_API_KEY)" }
        }

    Test-Step "mistral-medium-2604 limit is 262144/262144 (hi tier)" {
        if ($json -notmatch '"mistral-medium-2604"\s*:\s*\{\s*"limit"\s*:\s*\{\s*"context"\s*:\s*262144\s*,\s*"output"\s*:\s*262144') {
            throw "mistral-medium-2604 must be context 262144 / output 262144"
        }
    }

    Test-Step "mistral-small-2603 limit is 256000/256000 (lo tier)" {
        if ($json -notmatch '"mistral-small-2603"\s*:\s*\{\s*"limit"\s*:\s*\{\s*"context"\s*:\s*256000\s*,\s*"output"\s*:\s*256000') {
            throw "mistral-small-2603 must be context 256000 / output 256000"
        }
    }

        Test-Step "apiKey uses env MISTRAL_API_KEY" {
            if ($json -notmatch '"apiKey"\s*:\s*"\{env:MISTRAL_API_KEY\}"') {
                throw "must not contain a literal token"
            }
        }

        Test-Step "two-tier reviewers on Mistral (lo mistral-small-2603 / hi mistral-medium-2604)" {
            if ($json -notmatch '"mistral-medium-2604"') { throw "provider missing mistral-medium-2604 (hi tier)" }
            if ($json -notmatch '"mistral-small-2603"') { throw "provider missing mistral-small-2603 (lo tier)" }
            if ($json -notmatch '"moa-mistral-reviewer"\s*:\s*\{\s*"model"\s*:\s*"mistral/mistral-small-2603"') {
                throw "moa-mistral-reviewer (lo) must use mistral/mistral-small-2603"
            }
            if ($json -notmatch '"moa-mistral-reviewer-hi"\s*:\s*\{\s*"model"\s*:\s*"mistral/mistral-medium-2604"') {
                throw "moa-mistral-reviewer-hi (hi) must use mistral/mistral-medium-2604"
            }
        }

        Test-Step "Playwright MCP declared" {
            if ($json -notmatch '"playwright"') { throw "Playwright MCP missing" }
        }

        Test-Step "existing providers preserved" {
            if ($json -notmatch '"opencode"' -or $json -notmatch 'deepseek-v4-flash-free') {
                throw "existing opencode provider removed"
            }
        }
    }
}

# ---------------------------------------------------------------
# Unit: agents
# ---------------------------------------------------------------
if ($Unit -or $All) {
    Write-Host "`n=== Agents ===" -ForegroundColor Cyan

    Test-Step "moa-v2 primary agent exists" {
        $p = Join-Path $opencodeDir "agents\moa-v2.md"
        if (-not (Test-Path $p)) { throw "missing moa-v2.md" }
    }

    Test-Step "moa-v2 modes + permissions correct" {
        $p = Join-Path $opencodeDir "agents\moa-v2.md"
        $c = Get-Content $p -Raw
        if ($c -notmatch 'mode: primary') { throw "not primary" }
        if ($c -notmatch 'edit: allow') { throw "edit must be allow" }
        foreach ($perm in @('"rm *": ask', '"del *": ask', '"git push*": ask')) {
            if ($c -notmatch [regex]::Escape($perm)) { throw "missing bash rule: $perm" }
        }
    }

    Test-Step "lo reviewer agent is deny / deny + mistral-small-2603" {
        $p = Join-Path $opencodeDir "agents\moa-mistral-reviewer.md"
        if (-not (Test-Path $p)) { throw "missing moa-mistral-reviewer.md" }
        $c = Get-Content $p -Raw
        if ($c -notmatch 'mistral-small-2603') { throw "wrong model" }
        if ($c -notmatch 'edit: deny') { throw "reviewer must deny edit" }
        if ($c -notmatch '"\*Start-Sleep\*"\s*:\s*allow' -or $c -notmatch '"\*Get-Content\*"\s*:\s*allow' -or $c -notmatch '"\*"\s*:\s*deny') { throw "reviewer bash must be deny-by-default with Start-Sleep + Get-Content exceptions" }
    }

    Test-Step "high-tier reviewer + mistral-medium-2604 deny" {
        $p = Join-Path $opencodeDir "agents\moa-mistral-reviewer-hi.md"
        if (-not (Test-Path $p)) { throw "missing moa-mistral-reviewer-hi.md" }
        $c = Get-Content $p -Raw
        if ($c -notmatch 'mistral-medium-2604') { throw "wrong model" }
        if ($c -notmatch 'edit: deny') { throw "deny expected" }
        if ($c -notmatch '"\*Start-Sleep\*"\s*:\s*allow' -or $c -notmatch '"\*Get-Content\*"\s*:\s*allow' -or $c -notmatch '"\*"\s*:\s*deny') { throw "reviewer bash must be deny-by-default with Start-Sleep + Get-Content exceptions" }
    }

    Test-Step "runtime verifier is script-only + whitelist" {
        $p = Join-Path $opencodeDir "agents\moa-runtime-verifier.md"
        if (-not (Test-Path $p)) { throw "missing moa-runtime-verifier.md" }
        $c = Get-Content $p -Raw
        if ($c -notmatch 'whitelist' -and $c -notmatch 'not a reasoning agent') { throw "not script-only" }
        if ($c -match 'mistral-medium-2604|mistral-small-2603') { throw "runtime verifier must not use an LLM model" }
    }
}

# ---------------------------------------------------------------
# Unit: skills + memory
# ---------------------------------------------------------------
if ($Unit -or $All) {
    Write-Host "`n=== Skills & Memory ===" -ForegroundColor Cyan
    foreach ($skill in @('prompt-optimizer', 'decompose-plan', 'skill-finder-stacker', 'test-script-maker')) {
        Test-Step "$skill SKILL.md exists" {
            $p = Join-Path $skillRoot "$skill\SKILL.md"
            if (-not (Test-Path $p)) { throw "missing $skill\SKILL.md" }
        }
    }

    Test-Step "MOA_V2_MEMORY.md has required sections" {
        $p = Join-Path $skillRoot "MOA_V2_MEMORY.md"
        if (-not (Test-Path $p)) { throw "missing MOA_V2_MEMORY.md" }
        $c = Get-Content $p -Raw
        foreach ($sec in @('Skills Registry', 'Rate-Limit State', 'Reviewer Benchmark', 'Rejected Skills', 'Interactive Mode')) {
            if ($c -notmatch [regex]::Escape("## $sec")) { throw "missing section: $sec" }
        }
    }

    Test-Step "counters named per spec" {
        $p = Join-Path $skillRoot "MOA_V2_MEMORY.md"
        $c = Get-Content $p -Raw
        foreach ($counter in @('mistral_lo_calls_today', 'mistral_hi_calls_today', 'gemini35_calls_today', 'gemini3_calls_today', 'deepseek_synthesis_calls_today')) {
            if ($c -notmatch $counter) { throw "missing counter: $counter" }
        }
    }

    Test-Step "LESSONS.md exists and is append-only oriented" {
        $p = Join-Path $skillRoot "LESSONS.md"
        if (-not (Test-Path $p)) { throw "missing LESSONS.md" }
    }
}

# ---------------------------------------------------------------
# Unit: root-of-trust scripts + pytest
# ---------------------------------------------------------------
if ($Unit -or $All) {
    Write-Host "`n=== Python Scripts (root of trust) ===" -ForegroundColor Cyan
    foreach ($script in @('verdict_engine.py', 'build_review_package.py', 'classify_complexity.py', 'mutate_workspace.py', 'benchmark_reviewer.py')) {
        Test-Step "$script exists" {
            $p = Join-Path $scriptDir $script
            if (-not (Test-Path $p)) { throw "missing $script" }
            if ((Get-Item $p).Length -eq 0) { throw "$script is empty" }
        }
    }

    Test-Step "sandbox runner + Dockerfile exist" {
        $sb = Join-Path $scriptDir "sandbox\sandbox_run.py"
        $df = Join-Path $scriptDir "sandbox\Dockerfile"
        if (-not (Test-Path $sb)) { throw "missing sandbox\sandbox_run.py" }
        if (-not (Test-Path $df)) { throw "missing sandbox\Dockerfile" }
    }

    Test-Step "pytest test files exist for all scripts" {
        $testsDir = Join-Path $scriptDir "tests"
        if (-not (Test-Path $testsDir)) { throw "no tests dir" }
        $expect = @('test_verdict_engine.py', 'test_build_review_package.py', 'test_classify_complexity.py', 'test_mutate_workspace.py', 'test_benchmark_reviewer.py', 'test_sandbox_run.py')
        foreach ($t in $expect) {
            if (-not (Test-Path (Join-Path $testsDir $t))) { throw "missing $t" }
        }
    }

    Test-Step "pytest installed" {
        $null = & $python -m pytest --version 2>&1
        if ($LASTEXITCODE -ne 0) { throw "pytest not available" }
    }

    Test-Step "run full pytest suite" {
        Push-Location $scriptDir
        try {
            & $python -m pytest tests -q 2>&1 | Out-Host
            if ($LASTEXITCODE -ne 0) { throw "pytest suite failed" }
        } finally { Pop-Location }
    }
}

# ---------------------------------------------------------------
# Integration: spec keyword presence in primary agent
# ---------------------------------------------------------------
if ($Integration -or $All) {
    Write-Host "`n=== Integration (spec clauses in moa-v2.md) ===" -ForegroundColor Cyan
    $p = Join-Path $opencodeDir "agents\moa-v2.md"
    if (Test-Path $p) {
        $c = Get-Content $p -Raw
        foreach ($clause in @(
            'Five-Gate Review', 'Gate A', 'Gate B', 'Gate C', 'Gate D', 'Gate E',
            'visual gate', 'verdict_engine.py', 'build_review_package.py',
            'classify_complexity.py', 'mutate_workspace.py', 'FATAL_INTEGRITY_ERROR',
            'ENVIRONMENT_BLOCKED', 'INCOMPLETE_REVIEW', 'major_coverage', 'NOT_TESTED',
            'FRESH', 'STALE', 'SUPERSEDED', 'INVALID', 'flaky', 'artifacts.json',
            'COW', 'MutationError',
            'reserved_high_calls', 'remaining_global', 'minimum_calls_to_finish',
            'TIMEOUT', 'all-models', 'find the error', 'Mistral outage',
            'NOT_RUN_OFFLINE', 'npm audit', 'artifact_id', 'sha256', 'created_by',
            'criterion_ids', 'lesson can never change', 'times_confirmed',
            'append-only', '.lock', '60s', 'major_coverage = ', 'no rounding',
            '10 cycles', 'project-doc', 'sandbox', 'Dockerfile',
            'mistral/mistral-medium-2604', 'mistral/mistral-small-2603', 'lo tier', 'hi tier', 'mistral_lo_calls_today', 'mistral_hi_calls_today', '1B tokens/month',
            'E1', 'E2', 'Bandit', 'OWASP', 'provenance', 'quarantine', 'suspicious',
            'severity', 'justification'
        )) {
            Test-Step "mentions '${clause}'" {
                if ($c -notmatch [regex]::Escape($clause)) { throw "missing clause: $clause" }
            }
        }
    } else {
        Test-Step "integration root exists" { throw "moa-v2.md missing" }
    }
}

Write-Host "`n==== Gate 1 result: $pass passed, $fail failed ====" -ForegroundColor Magenta
if ($fail -gt 0) { exit 1 } else { exit 0 }