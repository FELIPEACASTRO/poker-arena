# Guia — ativar o leitor F3-VLM (Qwen3-VL) para ler QUALQUER tela real

O F2 (YOLO treinado em sintético) é *keyed a pixels* e **não generaliza** para UIs inéditas
(leu 0/2 cartas no PokerTH real). A solução é trocar a CLASSE de modelo: um **Vision-Language
Model** lê carta e dígito **semanticamente**, então uma UI nunca vista já é "in-distribution".
Este guia sobe o Qwen3-VL local e liga o backend nele.

O backend já está pronto: `poker_arena/vision/vlm_reader.py` fala com um endpoint
OpenAI-compatível via `POKER_VLM_URL`. Sem a var, tudo funciona como antes (F1/F2). Com a var,
o VLM entra como **fallback do abstain**: o caminho rápido (F1/F2/OCR em CPU) decide o comum;
quando abstém (UI inédita), o VLM lê — e a saída passa pela **mesma rede "100%-ou-abstém"**.

## Passo 1 — Subir o Qwen3-VL na sua GPU (llama.cpp)

O jeito mais direto é o `llama-server` do llama.cpp (suporte a Qwen3-VL GGUF desde out/2025).
Baixe um build com CUDA (releases do `ggml-org/llama.cpp`) e rode:

```bash
# Q4_K_M ~2.5-3.3 GB, roda folgado em 8 GB de VRAM. -hf baixa o modelo + o mmproj (visão).
llama-server -hf unsloth/Qwen3-VL-4B-Instruct-GGUF:Q4_K_M --port 8080 -ngl 99 --jinja
```

- Use a variante **Instruct** (não *Thinking*) — Thinking "pensa" tokens demais e estoura os 4s.
- `-ngl 99` joga as camadas pra GPU; `--jinja` habilita o template de chat correto.
- Se o `-hf` não puxar o `--mmproj` (projetor de visão) sozinho, baixe o arquivo `mmproj-*.gguf`
  do mesmo repo no HF e passe `--mmproj <caminho>`.

Confirme que subiu: abra `http://localhost:8080` no navegador (UI do llama.cpp) e mande uma
imagem de teste.

## Passo 2 — Apontar o backend pro VLM

```powershell
# PowerShell (sessão atual)
$env:POKER_VLM_URL = "http://localhost:8080/v1/chat/completions"
# ou persistente:  setx POKER_VLM_URL "http://localhost:8080/v1/chat/completions"
```

Opcionais: `POKER_VLM_MODEL` (default `qwen3-vl`), `POKER_VLM_TIMEOUT` (segundos, default 20 —
generoso pra teste; aperte depois de medir).

## Passo 3 — MEDIR a leitura e a latência em telas reais (obrigatório antes da banca)

```bash
uv run python scripts/vlm_eval.py scripts/real_eval/imgs
```

Ele reporta, por tela: o que o VLM leu, se o sanity **aceita ou abstém**, e a **latência vs 4s**.
Se você tiver o gabarito num `.json` ao lado (mesmo nome, com `hole`/`board`/`pot`), ele também
mede acurácia. **Só prometa ≤4s à banca depois de ver o número aqui** — a latência é o único
risco real e depende da sua GPU + tamanho da imagem.

Se estourar 4s: confirme Instruct (não Thinking), a imagem é redimensionada pra ≤1280px no
`vlm_reader` (`_MAX_SIDE`) e o output é travado em 256 tokens (`_MAX_TOKENS`) — pode baixar
esse teto. Em último caso, use a variante 2B ou o fallback de API (Gemini 2.5 Flash-Lite).

## Passo 4 — Demo ao vivo (as 2 janelas)

Com o `POKER_VLM_URL` setado, o `/copilot/from-image` (e o "Copiloto ao Vivo") passam a
resgatar telas que antes só abstiam. O campo `engine` da resposta mostra `F3-vlm` quando foi
o VLM que leu. Janela 1 = jogo (247freepoker/PokerTH); Janela 2 = app → "Ao Vivo".

## Passo 5 — Fechar o gap no caminho rápido (offline, opcional)

Use o VLM (ou o Gemini como oráculo) + **Autodistill/Grounding DINO** pra auto-rotular
~100-300 screenshots reais → rode o **nb09** (fine-tune do YOLO11n a partir do F2). Isso deixa
o caminho rápido (CPU, dezenas de ms) cada vez mais preciso nos clientes que você coleta, e o
VLM dispara menos. O VLM continua sendo a camada agnóstica pra cauda de UIs inéditas.

## Arquitetura em camadas (o que a banca valida)

```
screenshot → F1/F2/OCR (CPU, ~dezenas de ms) ── confiante? → decide
                        └── ABSTÉM (UI inédita) → Qwen3-VL (GPU) lê → JSON
                                                   └── treys valida cartas + OCR confere números
                                                   └── tudo concorda? decide : ABSTÉM
```

Rápido/local pro comum, VLM agnóstico pra cauda, **abstenção sempre na frente** — nunca
entrega leitura errada ao copiloto.
