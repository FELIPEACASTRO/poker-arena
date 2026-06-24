# Encerra o Poker Arena (backend :8000 + frontend :5173) de forma robusta.
# Mata a ARVORE (janela cmd + servidor) por linha de comando e libera as portas.
$ErrorActionPreference = 'SilentlyContinue'

function Kill-Tree($procid) { & cmd /c "taskkill /PID $procid /T /F" 2>$null | Out-Null }

$root = 'POKER\CLAUDE'

# 1) por linha de comando: fecha a janela cmd + a arvore do servidor
Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -and (
    $_.CommandLine -match 'poker_arena\.api\.app' -or
    ($_.CommandLine -match [regex]::Escape($root) -and $_.CommandLine -match 'vite') -or
    $_.CommandLine -match 'npm run dev'
  )
} | ForEach-Object { Kill-Tree $_.ProcessId }

# 2) fallback: libera quem ainda estiver ouvindo nas portas
Get-NetTCPConnection -LocalPort 8000, 5173 -State Listen |
  Select-Object -ExpandProperty OwningProcess -Unique |
  ForEach-Object { Kill-Tree $_ }

Start-Sleep -Milliseconds 700
$b = [bool](Get-NetTCPConnection -LocalPort 8000 -State Listen)
$f = [bool](Get-NetTCPConnection -LocalPort 5173 -State Listen)
if ($b -or $f) {
  Write-Host "  [aviso] ainda em uso -> 8000=$b 5173=$f"
} else {
  Write-Host "  Servidores encerrados (portas 8000 e 5173 livres)."
}
exit 0
