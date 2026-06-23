# Poker Arena — Frontend

Mesa de poker em **React + TypeScript (Vite)** que consome a API do backend.
Estética *cassino premium*: feltro verde profundo, acentos dourados, cartas creme,
tipografia editorial (Cormorant Garamond + Outfit) e brilho no jogador da vez.

## Como rodar

1. **Suba o backend** (noutro terminal):
   ```bash
   cd ../backend && uv run uvicorn poker_arena.api.app:app
   ```
2. **Rode o frontend:**
   ```bash
   npm install
   npm run dev          # http://localhost:5173
   ```
   API noutra URL? `VITE_API=http://host:porta npm run dev`

## Arquitetura
| Arquivo | Papel |
|---|---|
| `src/types.ts` | tipos espelhando os schemas do backend |
| `src/api.ts` | cliente HTTP tipado (createTable / act / nextHand) |
| `src/App.tsx` | estado + orquestração das telas |
| `src/components/SetupScreen` | escolher os cérebros de cada cadeira |
| `src/components/PokerTable` + `Seat` + `Card` | a mesa visual |
| `src/components/ActionBar` | suas ações (desistir / pagar / aumentar / all-in) |
| `src/styles.css` | tema visual (feltro, dourado, animações) |

> Fluxo: `SetupScreen` → `POST /tables` → render da mesa → `ActionBar` → `POST /actions` → re-render.
