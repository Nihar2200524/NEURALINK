param([switch]$UseSavedImage)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path -LiteralPath '.env')) {
    function New-AgentraSecret {
        $bytes = New-Object byte[] 32
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
        return [Convert]::ToBase64String($bytes)
    }
    $tenantSecret = New-AgentraSecret
    $approverSecret = New-AgentraSecret
    $settings = 'AGENTRA_TOKENS={"local":"' + $tenantSecret + '"}' + "`nAGENTRA_APPROVER_TOKEN=" + $approverSecret + "`n"
    [IO.File]::WriteAllText((Join-Path (Get-Location) '.env'), $settings)
    Write-Host 'Created local credentials in .env. Keep this file private.'
}
if ($UseSavedImage) {
    docker load -i agentra-ollama.tar
    if ($LASTEXITCODE -ne 0) { throw 'Docker image import failed' }
    docker compose up -d --no-build
} else { docker compose up -d --build }
if ($LASTEXITCODE -ne 0) { throw 'Agentra startup failed. Is Docker Desktop running?' }
Write-Host 'Open .env locally and use the local API token to Connect, and the approver token to authorize a task.'
Start-Process 'http://127.0.0.1:8000/'
