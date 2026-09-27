param(
    [int]$Port = $(if ($env:VOICE_STUDIO_PORT) { [int]$env:VOICE_STUDIO_PORT } else { 8766 }),
    [string]$HostAddress = $(if ($env:VOICE_STUDIO_HOST) { $env:VOICE_STUDIO_HOST } else { '127.0.0.1' })
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($HostAddress -notin @('127.0.0.1', 'localhost', '::1')) {
    throw 'Voice Studio may bind only to a local loopback address.'
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    $owners = ($listener | Select-Object -ExpandProperty OwningProcess -Unique) -join ', '
    throw "Port $Port is already used by PID $owners. No existing process was stopped; choose another port."
}

$env:VOICE_STUDIO_HOST = $HostAddress
$env:VOICE_STUDIO_PORT = [string]$Port
$env:PYTHONUTF8 = '1'

$exitCode = 1
Push-Location $Root
try {
    & python -B -m app.main --host $HostAddress --port $Port
    $exitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $exitCode
