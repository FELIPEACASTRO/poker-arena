@echo off
setlocal enableextensions
title POKER ARENA
cd /d "%~dp0"
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%POWERSHELL_EXE%" (
  echo [ERRO] Windows PowerShell nao foi encontrado no caminho seguro do sistema.
  exit /b 1
)

:menu
cls
echo(
echo   =====================================================
echo                   P O K E R   A R E N A
echo                 solucao local - launcher
echo   =====================================================
echo(
echo      [1]  Iniciar   (backend + frontend + navegador)
echo      [2]  Parar     (encerra os servidores)
echo      [3]  Abrir no navegador
echo      [4]  Validar   (testes + build + lint)
echo      [5]  Preflight banca (offline + visao + seguranca)
echo      [0]  Sair
echo(
choice /c 123450 /n /m "   Escolha uma opcao: "
if errorlevel 6 goto end
if errorlevel 5 goto preflight
if errorlevel 4 goto validate
if errorlevel 3 goto open
if errorlevel 2 goto stop
if errorlevel 1 goto start
goto menu

:start
echo(
"%POWERSHELL_EXE%" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0assets\start.ps1" -OpenBrowser
if errorlevel 1 (
  echo   [ERRO] Falha ao iniciar. Veja a mensagem acima.
  pause
)
goto menu

:stop
echo(
echo   Encerrando os servidores...
"%POWERSHELL_EXE%" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0assets\stop.ps1"
if errorlevel 1 (
  echo   [ERRO] Falha ao encerrar com seguranca. Veja a mensagem acima.
  pause
  exit /b 1
)
timeout /t 2 >nul
goto menu

:open
start "" "http://127.0.0.1:5173/?view=capture"
goto menu

:validate
echo(
echo   Rodando a validacao completa (pode levar varios minutos)...
"%POWERSHELL_EXE%" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0assets\validar.ps1"
echo(
pause
goto menu

:preflight
echo(
"%POWERSHELL_EXE%" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0assets\preflight_banca.ps1"
if errorlevel 1 (
  echo   [ERRO] A solucao ainda nao esta pronta para a banca.
)
echo(
pause
goto menu

:end
endlocal
exit /b 0
