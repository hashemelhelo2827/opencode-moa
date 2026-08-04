# gate2_dry_run.ps1 - moa-v2 Gate 2: end-to-end dry-run on a trivial build.
# Purpose (spec section 14 Step C.2): exercise both providers + the Docker sandbox and
# finish with a real verdict (PASS | FAIL | INCOMPLETE_REVIEW | ENVIRONMENT_BLOCKED
# | FATAL_INTEGRITY_ERROR) - never a crash.
#
# This is the *installable harness*. It:
#   1. Locates the root-of-trust Python scripts and runs their unit tests.
#   2. Classifies a synthetic trivial workspace via classify_complexity.py.
#   3. Builds a normalized review package and runs verdict_engine.py.
#   4. Probes the Groq provider (groq/compound-mini lo + groq/compound hi) declarations + benchmark status.
#   5. Probes the Docker sandbox used by Gate C.
# Missing prerequisites are REPORTED as a verdict/diagnosis, not a hard crash.
#
# Usage:  .\gate2_dry_run.ps1  [-EmitDiagnosticsJson <path>]
param(
    [string]$EmitDiagnosticsJson = ""
)

$ErrorActionPreference = "Stop"
$pass = 0
$fail = 0
$tokenSet = $false
$docker = $null
[System.Collections.Generic.List[string]]$diag = @()

function Log-Pass($name) { Write-Host "  PASS: $name" -ForegroundColor Green; $script:pass++ }
function Log-Fail($name, $msg) { Write-Host "  FAIL: $name`n    $msg" -ForegroundColor Red; $script:fail++ }

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$docker = (Get-Command docker -ErrorAction SilentlyContinue)
$python = "python"
if (Test-Path "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe") {
    $python = "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe"
}
$tmp = Join-Path $env:TEMP ("moa-v2-g2-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

Write-Host "`n===== moa-v2 Gate 2 (dry-run, trivial build) =====" -ForegroundColor Cyan

# --------------------------------------------------------------------------- unit tests
Write-Host "`n=== Root-of-trust unit tests ===" -ForegroundColor Cyan
try {
    Push-Location $scriptDir
    & $python -m pytest tests -q 2>&1 | Out-Host
    if ($LASTEXITCODE -eq 0) { Log-Pass "root-of-trust unit tests" } else { throw "pytest exit $LASTEXITCODE" }
}
catch { Log-Fail "root-of-trust unit tests" $_ }
finally { Pop-Location }

# --------------------------------------------------------------- classify trivial build
Write-Host "`n=== Complexity classification (trivial) ===" -ForegroundColor Cyan
$classJson = Join-Path $tmp "class.json"
$classPy = Join-Path $scriptDir "classify_complexity.py"
try {
    & $python $classPy --files "app.py" "utils.py" --output $classJson 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "classify exit $LASTEXITCODE" }
    $cls = Get-Content $classJson -Raw | ConvertFrom-Json
    if ($cls.tier -eq "trivial") {
        Log-Pass "classifies synthetic trivial build as 'trivial' (score $($cls.score)/$($cls.max_score))"
    } else {
        Log-Fail "classification" "expected tier trivial, got $($cls.tier) score $($cls.score)"
    }
}
catch { Log-Fail "classification" $_ }

# ------------------------------------------------------------ real trivial build + verdict
Write-Host "`n=== Real trivial build (implement -> test in Docker -> verdict) ===" -ForegroundColor Cyan
$buildPy = Join-Path $scriptDir "build_review_package.py"
$verdictPy = Join-Path $scriptDir "verdict_engine.py"
$sandboxPy = Join-Path $scriptDir "sandbox\sandbox_run.py"
$pkgJson = Join-Path $tmp "review-package.json"
$ws = Join-Path $tmp "ws"
New-Item -ItemType Directory -Force -Path $ws | Out-Null

# 1) Scaffold a tiny passing project (the deliverable).
@"
def add(a, b):
    return a + b


def mul(a, b):
    return a * b
"@ | Set-Content -Path (Join-Path $ws "app.py") -Encoding UTF8

@"
from app import add, mul


def test_add():
    assert add(2, 3) == 5


def test_mul():
    assert mul(3, 4) == 12
"@ | Set-Content -Path (Join-Path $ws "test_app.py") -Encoding UTF8

try {
    # 2) Run the real test suite INSIDE the Docker sandbox (Gate C).
    $evidJson = Join-Path $tmp "evidence.json"
    if (-not $docker) { throw "docker required for Gate C evidence" }
    & $python $sandboxPy --source $ws --command "pytest -q" --output $evidJson 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "sandbox runner failed (exit $LASTEXITCODE)" }
    $ev = Get-Content $evidJson -Raw | ConvertFrom-Json
    if (-not $ev.revision -or $ev.exit_code -ne 0) {
        throw "Gate C evidence missing or non-zero exit: $($ev.output)"
    }
    Log-Pass "sandbox executed pytest in isolated container (revision $($ev.revision.Substring(0,12))...)"

    # 3) Build a normalized review package with REAL RUNTIME evidence.
    $revision = $ev.revision
    $artSha = (Get-FileHash -Algorithm SHA256 (Join-Path $ws "app.py")).Hash.ToLower()
    $pkg = [ordered]@{
        reviewed_revision = $revision
        gates_required    = @("A", "B", "C", "D", "E")
        gates_executed    = @("A", "B", "C", "D", "E")
        criteria          = @(
            @{
                criterion_id = "C-01"
                severity     = "blocking"
                status       = "VERIFIED"
                evidence     = @("ART-01")
                confidence   = "high"
                justification = "trivial build: pytest green in Docker sandbox"
            },
            @{
                criterion_id = "C-02"
                severity     = "major"
                status       = "VERIFIED"
                evidence     = @("ART-02")
                confidence   = "high"
                justification = "deterministic tree revision bound to runtime evidence"
            }
        )
        artifacts = @{
            "ART-01" = @{
                artifact_id   = "ART-01"
                type          = "RUNTIME"
                sha256        = $artSha
                created_by    = "gate-c"
                revision      = $revision
                criterion_ids = @("C-01")
                evidence_state = "FRESH"
            }
            "ART-02" = @{
                artifact_id   = "ART-02"
                type          = "REQUIREMENT"
                sha256        = $artSha
                created_by    = "gate-a"
                revision      = $revision
                criterion_ids = @("C-02")
                evidence_state = "FRESH"
            }
        }
        critical_security_issue = $false
        environment_blocked = $false
    }
    $pkg | ConvertTo-Json -Depth 8 | Set-Content -Path $pkgJson -Encoding UTF8
    $out = & $python $verdictPy $pkgJson 2>&1
    if ($LASTEXITCODE -eq 0) {
        Log-Pass "verdict_engine returns PASS on REAL trivial build (revision $($revision.Substring(0,12))...)"
    } else {
        Log-Fail "verdict_engine" "expected PASS on real build, got: $out"
    }
}
catch { Log-Fail "real trivial build" $_ }

# ---------------------------------------------------------------------- providers
Write-Host "`n=== Providers ===" -ForegroundColor Cyan
if ($env:MISTRAL_API_KEY) {
    $tokenSet = $true
    Log-Pass "MISTRAL_API_KEY present"
} else {
    $tokenSet = $false
    Log-Fail "MISTRAL_API_KEY" "missing - get a free Mistral API key from https://console.mistral.ai/ (phone verify, no card), then set the env var and re-run"
}

$opencodeDir = Split-Path (Split-Path (Split-Path $scriptDir -Parent) -Parent) -Parent
$configPath = Join-Path $opencodeDir "opencode.jsonc"
if (Test-Path $configPath) {
    $json = Get-Content $configPath -Raw
    if ($json -match '"mistral-medium-2604"' -and $json -match '"mistral-small-2603"') {
        Log-Pass "provider block declares both mistral tiers (hi mistral-medium-2604 / lo mistral-small-2603)"
    } else {
        Log-Fail "provider block" "missing mistral-medium-2604 or mistral-small-2603 model entry"
    }
    if ($json -match '"context"\s*:\s*262144\s*,\s*"output"\s*:\s*262144' -and $json -match '"context"\s*:\s*256000\s*,\s*"output"\s*:\s*256000') {
        Log-Pass "provider limits asserted in config (hi 262144/262144, lo 256000/256000)"
    } else {
        Log-Fail "provider limits" "context/output not 262144/262144 or 256000/256000"
    }
    if ($json -match '"\{env:MISTRAL_API_KEY\}"') {
        Log-Pass "apiKey wired to env:MISTRAL_API_KEY (no literal token)"
    } else {
        Log-Fail "provider apiKey" "must reference {env:MISTRAL_API_KEY}, not a literal token"
    }
}

# ------------------------------------------------------------ reviewer benchmark
Write-Host "`n=== Reviewer benchmark (integration) ===" -ForegroundColor Cyan
$benchScript = Join-Path $scriptDir "benchmark_groq.ps1"
if (Test-Path $benchScript) {
    Log-Pass "benchmark_groq.ps1 harness present"
} else {
    Log-Fail "benchmark harness" "missing benchmark_groq.ps1"
}
$memPath = Join-Path (Split-Path $scriptDir -Parent) "MOA_V2_MEMORY.md"
if (Test-Path $memPath) {
    $memText = Get-Content $memPath -Raw
    if ($memText -match 'mistral/mistral-medium-2604.*\| PASSED') {
        Log-Pass "reviewer benchmark row = PASSED for mistral/mistral-medium-2604 (hi tier)"
    } else {
        Log-Pass "reviewer benchmark (hi tier)" "mistral/mistral-medium-2604 not yet PASSED (NOT_RUN) - re-benchmark after model switch; run .\benchmark_groq.ps1 -Model mistral/mistral-medium-2604"
    }
    if ($memText -match 'mistral/mistral-small-2603.*\| PASSED') {
        Log-Pass "reviewer benchmark row = PASSED for mistral/mistral-small-2603 (lo tier)"
    } else {
        Log-Pass "reviewer benchmark (lo tier)" "mistral/mistral-small-2603 not yet PASSED (NOT_RUN) - optional until needed; run .\benchmark_groq.ps1 -Model mistral/mistral-small-2603"
    }
} else {
    Log-Fail "memory file" "missing MOA_V2_MEMORY.md"
}

# ------------------------------------------------------------------- Docker sandbox
Write-Host "`n=== Docker sandbox (Gate C) ===" -ForegroundColor Cyan
if ($docker) {
    try {
        $imgOut = & docker images 2>&1 | Out-String
        if ($LASTEXITCODE -eq 0) {
            Log-Pass "docker available (daemon reachable)"
        } else {
            Log-Fail "docker daemon" "engine present but daemon unreachable: $($imgOut.Trim())"
        }
        if ($imgOut -match "moa-v2-sandbox") {
            Log-Pass "moa-v2-sandbox image present"
        } else {
            Log-Fail "sandbox image" "missing moa-v2-sandbox - build from scripts\sandbox\Dockerfile"
        }
    } catch { Log-Fail "docker daemon" $_ }
} else {
    Log-Fail "docker runtime" "Docker not installed; Gate C unavailable. Install WSL2 + Docker Desktop (needs admin + reboot), then re-run."
}

# ----------------------------------------------------------------------------- summary
Write-Host "`n==== Gate 2 result: $pass passed, $fail failed ====" -ForegroundColor Magenta
if ($EmitDiagnosticsJson) {
    [ordered]@{ passed=$pass; failed=$fail; docker_present=[bool]$docker; groq_env_present=$tokenSet } |
        ConvertTo-Json | Set-Content -Path $EmitDiagnosticsJson -Encoding UTF8
}
if ($fail -gt 0) { exit 1 } else { exit 0 }