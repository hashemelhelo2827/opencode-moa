# benchmark_groq.ps1 - moa-v2 reviewer benchmark harness (Groq / Mistral backend).
# Drives the fallback-reviewer benchmark against a Groq or Mistral model:
#   1. Loads the fixed CORPUS of review tasks from benchmark_reviewer.py.
#   2. For each task, invokes the model (Groq chat / Mistral chat) to review the
#      package and emit {task_id, criteria:[{criterion_id, status}]}.
#   3. Writes responses.json and runs:
#        benchmark_reviewer.py run --responses ... --model <model> --memory MOA_V2_MEMORY.md
#      which deterministically scores the responses and patches the verdict into
#      MOA_V2_MEMORY.md (PENDING -> PASSED / FAILED).
#
# Provider is auto-detected from -Model: a 'mistral/*' or 'groq/*' prefix selects the
# matching env pair (MISTRAL_API_KEY + https://api.mistral.ai/v1, or GROQ_API_KEY +
# GROQ_BASE_URL). Bare model ids default to Groq.
#
# The model review is run here because benchmark_reviewer.py is a deterministic
# adjudicator only - it never calls a model. Exits 0 on overall PASS, 1 otherwise.
param(
    [string]$BaseUrl = "",          # default per provider (Mistral / Groq env / https://api.groq.com/openai/v1)
    [string]$Model = "mistral/mistral-small-2603",
    [string]$Memory = ""            # MOA_V2_MEMORY.md path (default: scripts\..\MOA_V2_MEMORY.md)
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$skillRoot = Split-Path $scriptDir -Parent
if (-not $Memory) { $Memory = Join-Path $skillRoot "MOA_V2_MEMORY.md" }

$python = "python"
if (Test-Path "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe") {
    $python = "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe"
}

# --- provider detection + API key + base URL ---
$provider = "groq"
if ($Model -like 'mistral/*') { $provider = "mistral" }
elseif ($Model -like 'groq/*') { $provider = "groq" }

$apiKey = $null
$base = $null
if ($provider -eq "mistral") {
    $apiKey = $env:MISTRAL_API_KEY
    if (-not $apiKey) { $apiKey = [System.Environment]::GetEnvironmentVariable('MISTRAL_API_KEY', 'User') }
    $base = "https://api.mistral.ai/v1"
} else {
    $apiKey = $env:GROQ_API_KEY
    if (-not $apiKey) { $apiKey = [System.Environment]::GetEnvironmentVariable('GROQ_API_KEY', 'User') }
    $base = $env:GROQ_BASE_URL
    if (-not $base) { $base = [System.Environment]::GetEnvironmentVariable('GROQ_BASE_URL', 'User') }
    if (-not $base) { $base = "https://api.groq.com/openai/v1" }
}
if (-not $apiKey) { throw "$($provider.ToUpper())_API_KEY not found in process env or user store" }
if ($BaseUrl) { $base = $BaseUrl }
$base = $base.TrimEnd('/')
$endpoint = "$base/chat/completions"

# opencode-qualified label (used for the MEMORY row) vs raw API model id used by the backend
$ApiModel = $Model
if ($ApiModel -like 'mistral/*') { $ApiModel = $ApiModel.Substring(8) }
elseif ($ApiModel -like 'groq/*') { $ApiModel = $ApiModel.Substring(5) }

$tmp = Join-Path $env:TEMP ("moa-v2-bench-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

Write-Host "`n===== moa-v2 reviewer benchmark ($provider / $Model) =====" -ForegroundColor Cyan
Write-Host "Memory: $Memory" -ForegroundColor Gray

# --- 1. dump corpus tasks (id + expected) from benchmark_reviewer.py ---
$corpusJson = Join-Path $tmp "corpus.json"
$dumpPyFile = Join-Path $tmp "dump_corpus.py"
$dumpPy = @'
import json
import sys
sys.path.insert(0, r"SCRIPTDIR")
from benchmark_reviewer import CORPUS
print(json.dumps([{"id": c["id"], "name": c.get("name", ""), "expected": c.get("expected", {}), "package": c["package"]} for c in CORPUS]))
'@
$dumpPy = $dumpPy.Replace('SCRIPTDIR', $scriptDir)
Set-Content -Path $dumpPyFile -Value $dumpPy -Encoding UTF8
& $python $dumpPyFile 2>$null | Set-Content -Path $corpusJson -Encoding UTF8

$corpus = Get-Content $corpusJson -Raw | ConvertFrom-Json
if (-not $corpus) { throw "failed to read CORPUS from benchmark_reviewer.py" }

$responses = [System.Collections.Generic.List[object]]::new()
$allPassed = $true

foreach ($task in $corpus) {
    Write-Host "`n--- Task $($task.id): $($task.name) ---" -ForegroundColor Yellow

    $package = @($task.package) | ConvertTo-Json -Depth 20 -Compress
    $prompt = @(
        "You are a moa-v2 reviewer. Review the following review-package and report the",
        "current status of each criterion exactly as recorded in the package. Do NOT",
        "invent criteria, do NOT invent statuses, do NOT add commentary.",
        "",
        "Return STRICT JSON with this exact shape (no markdown fences):",
        "{`"task_id`": `"$($task.id)`", `"criteria`": [ {`"criterion_id`": `"C-01`", `"status`": `"VERIFIED`"} ] }",
        "",
        "Package:",
        $package
    ) -join "`n"

    $bodyObj = @{
        model = $ApiModel
        temperature = 0
        max_tokens = 8192
        response_format = @{ type = "json_object" }
        messages = @(
            @{ role="system"; content="You are a deterministic moa-v2 reviewer evidence reporter. You read a package and report per-criterion status. JSON only." },
            @{ role="user"; content=$prompt }
        )
    }
    $body = $bodyObj | ConvertTo-Json -Depth 10

    $lastErr = $null
    $attempt = 0
    $maxAttempts = 6
    $resp = $null
    while ($attempt -lt $maxAttempts) {
        $attempt++
        try {
            $resp = Invoke-RestMethod -Uri $endpoint -Method Post `
                -Headers @{ "Authorization" = "Bearer $apiKey"; "Content-Type" = "application/json" } `
                -Body $body -TimeoutSec 90
            break
        } catch {
            $errText = $_.ErrorDetails.Message
            $lastErr = $_
            if ($errText -match 'model_not_found|invalid_request_error|invalid_api_key|auth_error|403') {
                Write-Host "  FATAL API error: $errText" -ForegroundColor Red
                break
            }
            if ($errText -match 'rate_limit_exceeded' -or $errText -match 'TPM|RPM|429') {
                $wait = 12
                $m = [regex]::Match($errText, 'in (\d+(?:\.\d+)?)s')
                if ($m.Success) { $wait = [math]::Max(3, [int][math]::Ceiling([double]$m.Groups[1].Value)) }
                Write-Host "  rate limit on attempt $attempt/$maxAttempts; waiting $wait s..." -ForegroundColor DarkYellow
                Start-Sleep -Seconds $wait
            } elseif ($attempt -lt $maxAttempts) {
                Write-Host "  transient error on attempt $attempt/$maxAttempts; retrying..." -ForegroundColor DarkYellow
                Start-Sleep -Seconds 5
            }
        }
    }

    try {
        if (-not $resp) { throw "API call failed after $maxAttempts attempts: $lastErr" }
        $content = $resp.choices[0].message.content
        # strip triple-backtick fences if the model wrapped JSON anyway
        $content = $content -replace '```json','' -replace '```','' -replace '(?s)^\s*','' -replace '(\s*)$',''
        $parsed = $content | ConvertFrom-Json
        if (-not $parsed.criteria) { throw "response missing criteria" }
        $parsed.task_id = $task.id   # pin to the harness-known task id (model may echo empty)
        $responses.Add($parsed)
    } catch {
        Write-Host "  FAIL: API call / parse error for $($task.id): $_" -ForegroundColor Red
        $allPassed = $false
        # record an empty response so scoring still covers the task
        $responses.Add(@{ task_id = $task.id; criteria = @() })
    }

    # space out calls so the two package-sized requests stay under the TPM budget
    if ($corpus.IndexOf($task) -lt $corpus.Count - 1) {
        Start-Sleep -Seconds 20
    }
}

# --- 2. collect responses -> responses.json ---
$responsesJson = Join-Path $tmp "responses.json"
$responses | ConvertTo-Json -Depth 10 | Set-Content -Path $responsesJson -Encoding UTF8
Write-Host "`nResponses written: $responsesJson" -ForegroundColor Gray

# --- 3. score + patch memory ---
Push-Location $scriptDir
try {
    $out = & $python .\benchmark_reviewer.py run `
        --responses $responsesJson `
        --model $Model `
        --memory $Memory 2>&1
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}
$out | ForEach-Object { $_ }

if ($code -eq 0) {
    Write-Host "`n===== BENCHMARK PASSED ($Model) =====" -ForegroundColor Green
} else {
    $allPassed = $false
    Write-Host "`n===== BENCHMARK FAILED ($Model) =====" -ForegroundColor Red
}

if (-not $allPassed -and $code -eq 0) { $code = 1 }
exit $code