# https://github.com/PowerShell/PowerShell/blob/master/docs/installing/installing-powershell-core-on-windows.md#MSI
#
# Cross-platform build script: Rust binary + TypeScript compilation + Python tests.

[CmdletBinding()]
param(
    [switch]$SkipRust,
    [switch]$SkipTypeScript,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "╔═══════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║   Tuncay-Klip Polyglot Build Pipeline              ║" -ForegroundColor Cyan
Write-Host "╚═══════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$anyError = $false

# ── Step 1: Rust ──────────────────────────────────────────
if (-not $SkipRust) {
    Write-Host "[1/3] Building Rust video-processor binary..." -ForegroundColor Yellow
    Push-Location "tools/video-processor"
    try {
        cargo build --release
        if ($LASTEXITCODE -ne 0) { $anyError = $true }
        else {
            Write-Host "  ✓ Rust binary compiled" -ForegroundColor Green
            $binPath = "target/release/tuncay-video-processor.exe"
            if (Test-Path $binPath) {
                $size = (Get-Item $binPath).Length
                Write-Host "  Binary: $('{0:N1}' -f ($size/1MB)) MB" -ForegroundColor Gray
            }
        }
    } finally {
        Pop-Location
    }
    Write-Host ""
}

# ── Step 2: TypeScript ────────────────────────────────────
if (-not $SkipTypeScript) {
    Write-Host "[2/3] Building TypeScript dashboard..." -ForegroundColor Yellow
    Push-Location "dashboard"
    try {
        if (-not (Test-Path "node_modules")) {
            npm install
            if ($LASTEXITCODE -ne 0) { $anyError = $true }
        }
        if (-not $anyError) {
            npx tsc
            if ($LASTEXITCODE -ne 0) { $anyError = $true }
            else { Write-Host "  ✓ TypeScript compiled" -ForegroundColor Green }
        }
    } finally {
        Pop-Location
    }
    Write-Host ""
}

# ── Step 3: Python tests ──────────────────────────────────
if (-not $SkipTests) {
    Write-Host "[3/3] Running Python test suite..." -ForegroundColor Yellow
    python -m pytest tests/test_zero_bandwidth.py tests/test_kick_archive.py tests/test_api.py tests/test_advanced_features.py::TestCostTracker tests/test_advanced_features.py::TestQualityDashboard tests/test_advanced_features.py::TestMultiPlatformPublisher tests/test_advanced_features.py::TestUserFeedback tests/test_advanced_features.py::TestThumbnailABTest tests/test_ai_critic.py -v --tb=short
    if ($LASTEXITCODE -ne 0) { $anyError = $true }
    else { Write-Host "  ✓ All tests passed" -ForegroundColor Green }
    Write-Host ""
}

$stopwatch.Stop()
Write-Host "─────────────────────────────────────────────────────" -ForegroundColor Cyan
if ($anyError) {
    Write-Host "BUILD FAILED ($([math]::Round($stopwatch.Elapsed.TotalSeconds, 1))s)" -ForegroundColor Red
    exit 1
} else {
    Write-Host "BUILD SUCCESSFUL ($([math]::Round($stopwatch.Elapsed.TotalSeconds, 1))s)" -ForegroundColor Green
    Write-Host ""
    Write-Host "Artifacts:" -ForegroundColor Gray
    if (-not $SkipRust)   { Write-Host "  - tools/video-processor/target/release/tuncay-video-processor.exe" -ForegroundColor Gray }
    if (-not $SkipTypeScript) { Write-Host "  - dashboard/dist/ (compiled TypeScript)" -ForegroundColor Gray }
    Write-Host ""
}
