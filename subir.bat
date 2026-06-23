@echo off
title Poker Arena - launcher
echo(
echo   ==================================================
echo    POKER ARENA  -  subindo a solucao
echo   ==================================================
echo(

REM --- pre-requisitos ---
where uv >nul 2>nul
if errorlevel 1 (
  echo  [ERRO] 'uv' nao encontrado no PATH.
  echo         Instale o uv: https://docs.astral.sh/uv/
  echo.
  pause
  exit /b 1
)
where npm >nul 2>nul
if errorlevel 1 (
  echo  [ERRO] 'npm' nao encontrado no PATH ^(precisa do Node.js^).
  echo         Instale o Node.js: https://nodejs.org/
  echo.
  pause
  exit /b 1
)

REM --- 1) Backend (FastAPI) numa nova janela ---
echo  [1/2] BACKEND  (FastAPI)   ^>  http://127.0.0.1:8000/docs
start "Poker Arena - BACKEND" /d "%~dp0backend" cmd /k "uv run uvicorn poker_arena.api.app:app --port 8000 --reload"

REM --- 2) Frontend (React/Vite) noutra janela; abre o navegador sozinho ---
echo  [2/2] FRONTEND (React)     ^>  http://localhost:5173
start "Poker Arena - FRONTEND" /d "%~dp0frontend" cmd /k "npm install && npm run dev -- --open"

echo(
echo   Pronto! Duas janelas foram abertas (BACKEND e FRONTEND).
echo   - O navegador abre sozinho quando o frontend terminar de subir.
echo   - Na 1a vez, o 'npm install' pode demorar um pouco.
echo   - Para PARAR: feche as duas janelas (ou Ctrl+C em cada uma).
echo(
pause
