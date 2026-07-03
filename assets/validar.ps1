# Validacao completa da solucao: testes backend + testes frontend + build + lint.
# Roda tudo, mostra um resumo verde/vermelho e devolve exit code != 0 se algo falhar.
$ErrorActionPreference = 'Continue'
$root = Split-Path $PSScriptRoot -Parent  # assets/ fica na raiz -> pai = raiz do projeto
$fail = @()

function Step($nome, $dir, $cmd) {
    Write-Host ""
    Write-Host "  >>> $nome ..." -ForegroundColor Cyan
    Push-Location $dir
    & cmd /c $cmd
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) {
        $script:fail += $nome
        Write-Host "  [FALHOU] $nome (exit $code)" -ForegroundColor Red
    } else {
        Write-Host "  [OK] $nome" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "  ======================================================"
Write-Host "               VALIDACAO  -  POKER ARENA"
Write-Host "  ======================================================"

Step "Testes do backend (pytest)"   "$root\backend"  "uv run pytest -q"
Step "Testes do frontend (vitest)"  "$root\frontend" "npm test"
Step "Build do frontend (tsc+vite)" "$root\frontend" "npm run build"
Step "Lint do frontend (eslint)"    "$root\frontend" "npm run lint"

Write-Host ""
Write-Host "  ======================================================"
if ($fail.Count -eq 0) {
    Write-Host "   TUDO VERDE - solucao validada com sucesso" -ForegroundColor Green
    $exit = 0
} else {
    Write-Host "   $($fail.Count) etapa(s) FALHARAM:" -ForegroundColor Red
    $fail | ForEach-Object { Write-Host "     - $_" -ForegroundColor Red }
    $exit = 1
}
Write-Host "  ======================================================"
Write-Host ""
exit $exit
