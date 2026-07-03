@echo off
setlocal enableextensions
title POKER ARENA
cd /d "%~dp0"

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
echo      [0]  Sair
echo(
set "opt="
set /p "opt=   Escolha e tecle ENTER: "
if "%opt%"=="1" goto start
if "%opt%"=="2" goto stop
if "%opt%"=="3" goto open
if "%opt%"=="4" goto validate
if "%opt%"=="0" goto end
goto menu

:start
echo(
where uv >nul 2>nul
if errorlevel 1 (
  echo   [ERRO] 'uv' nao encontrado no PATH. Instale: https://docs.astral.sh/uv/
  echo(
  pause
  goto menu
)
where npm >nul 2>nul
if errorlevel 1 (
  echo   [ERRO] 'npm' nao encontrado ^(precisa do Node.js^): https://nodejs.org/
  echo(
  pause
  goto menu
)
echo   [1/2] Subindo BACKEND   ^> http://127.0.0.1:8000/docs
start "Poker Arena - BACKEND" /d "%~dp0backend" cmd /k "uv run uvicorn poker_arena.api.app:app --port 8000"
echo   [2/2] Subindo FRONTEND  ^> http://localhost:5173
if exist "%~dp0frontend\node_modules" (
  start "Poker Arena - FRONTEND" /d "%~dp0frontend" cmd /k "npm run dev -- --open"
) else (
  echo         ^(primeira vez: instalando dependencias, pode demorar^)
  start "Poker Arena - FRONTEND" /d "%~dp0frontend" cmd /k "npm install ^&^& npm run dev -- --open"
)
echo(
echo   Pronto! Duas janelas abriram. O navegador abre sozinho ao subir o frontend.
timeout /t 5 >nul
goto menu

:stop
echo(
echo   Encerrando os servidores...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0assets\stop.ps1"
timeout /t 2 >nul
goto menu

:open
start "" "http://localhost:5173"
goto menu

:validate
echo(
echo   Rodando a validacao completa (pode levar 1-2 min)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0assets\validar.ps1"
echo(
pause
goto menu

:end
endlocal
exit /b 0
