@echo off
setlocal
cd /d "%~dp0"
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%POWERSHELL_EXE%" (
  echo [ERRO] Windows PowerShell nao foi encontrado no caminho seguro do sistema.
  exit /b 1
)
"%POWERSHELL_EXE%" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0assets\start.ps1" -OpenBrowser
if errorlevel 1 (
  echo [ERRO] Nao foi possivel iniciar o Poker Arena.
  exit /b 1
)
echo Poker Arena iniciado. Use assets\stop.ps1 para encerrar somente estes processos.
exit /b 0
