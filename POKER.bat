@echo off
setlocal enableextensions
title POKER ARENA
cd /d "%~dp0"
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%POWERSHELL_EXE%" (
  echo [ERRO] Windows PowerShell nao foi encontrado no caminho seguro do sistema.
  exit /b 1
)

if /i "%~1"=="start" goto cli_start
if /i "%~1"=="iniciar" goto cli_start
if /i "%~1"=="stop" goto cli_stop
if /i "%~1"=="parar" goto cli_stop
if /i "%~1"=="urls" goto cli_urls
if /i "%~1"=="open" goto cli_open
if /i "%~1"=="abrir" goto cli_open
if not "%~1"=="" goto cli_usage

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
echo      [3]  Mostrar URLs e abrir no navegador
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
"%POWERSHELL_EXE%" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0assets\start.ps1" -ShowUrlsOnly -OpenBrowser
if errorlevel 1 (
  echo   [ERRO] Nao foi possivel listar/abrir as URLs.
  pause
)
goto menu

:cli_start
if "%~2"=="" goto cli_start_browser
if /i "%~2"=="--no-browser" goto cli_start_no_browser
goto cli_usage

:cli_start_browser
"%POWERSHELL_EXE%" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0assets\start.ps1" -OpenBrowser
exit /b %errorlevel%

:cli_start_no_browser
"%POWERSHELL_EXE%" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0assets\start.ps1"
exit /b %errorlevel%

:cli_stop
if not "%~2"=="" goto cli_usage
"%POWERSHELL_EXE%" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0assets\stop.ps1"
exit /b %errorlevel%

:cli_urls
if not "%~2"=="" goto cli_usage
"%POWERSHELL_EXE%" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0assets\start.ps1" -ShowUrlsOnly
exit /b %errorlevel%

:cli_open
if not "%~2"=="" goto cli_usage
"%POWERSHELL_EXE%" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0assets\start.ps1" -ShowUrlsOnly -OpenBrowser
exit /b %errorlevel%

:cli_usage
echo Uso:
echo   POKER.bat start [--no-browser]
echo   POKER.bat stop
echo   POKER.bat urls
echo   POKER.bat open
exit /b 2

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
