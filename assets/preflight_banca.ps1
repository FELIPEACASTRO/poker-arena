[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$python = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
$script = Join-Path $projectRoot 'backend\scripts\demo_preflight.py'

foreach ($path in @($python, $script)) {
    $item = Get-Item -LiteralPath $path -Force -ErrorAction Stop
    if ($item.PSIsContainer -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Preflight recusou executavel/script nao regular: $path"
    }
}

Write-Host ''
Write-Host '=== PREFLIGHT OFFLINE DA BANCA ==='
& $python -B $script
if ($LASTEXITCODE -ne 0) {
    throw 'Solucao NAO esta pronta para a banca; corrija o motivo acima.'
}
Write-Host 'RELEASE_DECISION=GO; SCOPE=LOCAL_MASTER_DEFENSE'
Write-Host 'READY_FOR_LOCAL_DEFENSE: solucao pronta para apresentacao local.'
