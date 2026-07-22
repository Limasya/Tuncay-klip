# ─── Tuncay-Klip — Hizli Baslatici ────────
# Kullanim:  powershell -ExecutionPolicy Bypass -File start.ps1

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "  Tuncay-Klip baslatiliyor..." -ForegroundColor Cyan
Write-Host ""

# data klasörlerini oluştur
@("data", "logs", "clips", "models_store") | ForEach-Object {
    $dir = Join-Path $Root $_
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
}

# uvicorn calistir
Write-Host "  http://localhost:8000 adresinde baslatiliyor..." -ForegroundColor Green
Write-Host ""

Set-Location $Root
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
