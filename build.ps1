# https://github.com/PowerShell/PowerShell/blob/master/docs/installing/installing-powershell-core-on-windows.md#MSI
#
# Cross-platform build script: Rust binary + C++ signal engine + TypeScript compilation + Python tests.

[CmdletBinding()]
param(
    [switch]$SkipRust,
    [switch]$SkipCpp,
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
    Write-Host "[1/4] Building Rust video-processor binary..." -ForegroundColor Yellow
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

# ── Step 2: C++ signal_engine ─────────────────────────────
if (-not $SkipCpp) {
    Write-Host "[2/4] Building C++ signal_engine..." -ForegroundColor Yellow
    $seBuild = "signal_engine/build"
    try {
        if (-not (Test-Path "$seBuild/CMakeCache.txt")) {
            cmake -S signal_engine -B $seBuild -G "Visual Studio 17 2022" -A x64
            if ($LASTEXITCODE -ne 0) { $anyError = $true }
        }
        if (-not $anyError) {
            cmake --build $seBuild --config Release -- /v:minimal
            if ($LASTEXITCODE -ne 0) { $anyError = $true }
            else {
                Write-Host "  ✓ signal_engine DLL + CLI + tests compiled" -ForegroundColor Green
                $dllPath = "$seBuild/bin/Release/signal_engine.dll"
                if (Test-Path $dllPath) {
                    $size = (Get-Item $dllPath).Length
                    Write-Host "  DLL: $('{0:N1}' -f ($size/1MB)) MB" -ForegroundColor Gray
                }
            }
        }
        if (-not $anyError) {
            & "$seBuild/bin/Release/se_tests.exe"
            if ($LASTEXITCODE -ne 0) { $anyError = $true }
            else { Write-Host "  ✓ C++ tests passed" -ForegroundColor Green }
        }
    } catch {
        Write-Host "  ✗ C++ build error: $_" -ForegroundColor Red
        $anyError = $true
    }
    Write-Host ""
}

# ── Step 3: TypeScript ────────────────────────────────────
if (-not $SkipTypeScript) {
    Write-Host "[3/4] Building TypeScript dashboard..." -ForegroundColor Yellow
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

# ── Step 4: Python tests ──────────────────────────────────
if (-not $SkipTests) {
    Write-Host "[4/4] Running Python test suite..." -ForegroundColor Yellow
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
    if (-not $SkipCpp)    { Write-Host "  - signal_engine/build/bin/Release/signal_engine.dll" -ForegroundColor Gray }
    if (-not $SkipTypeScript) { Write-Host "  - dashboard/dist/ (compiled TypeScript)" -ForegroundColor Gray }
    Write-Host ""
}
