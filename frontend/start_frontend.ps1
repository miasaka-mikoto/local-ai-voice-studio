[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 5173,

    [string]$ApiBaseUrl = $(
        if ($env:VITE_API_BASE_URL) { $env:VITE_API_BASE_URL }
        else { 'http://127.0.0.1:8766' }
    ),

    [ValidateSet('auto', 'api', 'mock')]
    [string]$DataMode = $(
        if ($env:VITE_DATA_MODE) { $env:VITE_DATA_MODE }
        else { 'auto' }
    ),

    [ValidateSet('true', 'false')]
    [string]$EnableMock = $(
        if ($env:VITE_ENABLE_MOCK) { $env:VITE_ENABLE_MOCK.ToLowerInvariant() }
        else { 'true' }
    )
)

$ErrorActionPreference = 'Stop'
$frontendRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($Port -in @(7860, 8765, 8766)) {
    throw "Frontend port $Port is reserved for Gradio, another local service, or the Voice Studio API. Choose a port such as 5173 or 5174."
}

try {
    $apiUri = [Uri]$ApiBaseUrl
} catch {
    throw "ApiBaseUrl is not a valid absolute URL: $ApiBaseUrl"
}

if (-not $apiUri.IsAbsoluteUri -or $apiUri.Scheme -notin @('http', 'https')) {
    throw 'ApiBaseUrl must be an absolute HTTP or HTTPS URL.'
}

if ($apiUri.Host -notin @('127.0.0.1', 'localhost', '::1')) {
    throw "ApiBaseUrl must use a loopback host; received $($apiUri.Host)."
}

$listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($listener) {
    throw "127.0.0.1:$Port is already used by PID $($listener.OwningProcess). This script will not stop it."
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw 'node was not found. Install or repair the local Node.js runtime first.'
}

if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw 'npm.cmd was not found. Install or repair the local npm runtime first.'
}

$viteCommand = Join-Path $frontendRoot 'node_modules\.bin\vite.cmd'
if (-not (Test-Path -LiteralPath $viteCommand)) {
    throw "Frontend dependencies are missing. Run npm.cmd ci in $frontendRoot first. This script will not download dependencies."
}

$env:VITE_API_BASE_URL = $ApiBaseUrl.TrimEnd('/')
$env:VITE_DATA_MODE = $DataMode
$env:VITE_ENABLE_MOCK = $EnableMock

Write-Host "Local AI Voice Studio frontend: http://127.0.0.1:$Port"
Write-Host "API base URL: $($env:VITE_API_BASE_URL)"
Write-Host "Data mode: $DataMode; mock enabled: $EnableMock"
Write-Host 'This does not start the backend, port 7860, models, or downloads. Ctrl+C stops only this frontend server.'

Push-Location $frontendRoot
try {
    & npm.cmd run dev -- --host 127.0.0.1 --port $Port --strictPort
    if ($LASTEXITCODE -ne 0) {
        throw "Vite exited with code $LASTEXITCODE."
    }
} finally {
    Pop-Location
}
