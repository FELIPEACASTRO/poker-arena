# Guia seguro — leitor experimental F3-VLM

O F3-VLM é uma trilha **experimental de leitura**, não um leitor universal e não um
oráculo de decisão. Uma resposta sintaticamente válida do modelo remoto continua com
confiança `0.0`; por isso, o backend devolve `sanity.ok=false` e `decision=null` para a
proposta F3. F1/F2/OCR locais permanecem o caminho principal e também podem abster.

Não use captura ou assistência em partidas de terceiros, com dinheiro real ou onde os
termos da plataforma proíbam RTA. Screenshots reais só podem ser processados com base
legal, consentimento e corpus próprios/autorizados.

## Opção reproduzível: notebook 10

[`ml/notebooks/10_vlm_server_colab.ipynb`](../../ml/notebooks/10_vlm_server_colab.ipynb)
fixa o commit do `llama.cpp`, a revisão e os nomes dos arquivos Qwen3-VL, os SHA-256 dos
pesos e `mmproj`, e a versão/hash do `cloudflared`. O notebook:

- exige um túnel Cloudflare **nomeado**, hostname estável e TLS;
- não aceita `trycloudflare`, `releases/latest` nem aliases de modelo mutáveis;
- recebe tokens somente por variáveis/Secrets, nunca pelo notebook ou pela linha de comando;
- faz apenas um smoke test sem screenshots reais; e
- não promove o modelo nem produz uma métrica de qualidade.

Antes de executar, o operador deve criar e revisar o túnel/hostname e fornecer no cofre do
ambiente:

- `POKER_CLOUDFLARE_TUNNEL_TOKEN`;
- `POKER_VLM_API_TOKEN`, segredo ASCII de 32–512 caracteres; e
- `POKER_VLM_PUBLIC_BASE_URL`, uma origem HTTPS estável sem path, query ou credenciais.

## Configuração do backend

Para um endpoint remoto, configure na sessão do processo — sem gravar segredos no Git,
notebook, URL, log ou screenshot:

```powershell
$env:POKER_VLM_URL = "https://vlm.seu-dominio.example/v1/chat/completions"
$env:POKER_VLM_ALLOWED_HOSTS = "vlm.seu-dominio.example"
$env:POKER_VLM_API_TOKEN = "<segredo gerenciado com pelo menos 32 caracteres>"
$env:POKER_VLM_MODEL = "qwen3-vl-4b-instruct-q4-k-m-00c00da"
$env:POKER_VLM_TIMEOUT = "20"
$env:POKER_VLM_REDACT_REGIONS = "0.00,0.00,1.00,0.12;0.00,0.88,1.00,1.00"
```

`POKER_VLM_REDACT_REGIONS` usa retângulos normalizados `x0,y0,x1,y1`, separados por
`;`. O exemplo é apenas ilustrativo: determine as regiões a partir da UI autorizada e
inclua nomes, chat, notificações, saldo/conta e qualquer outro identificador. Uma máscara
ausente ou inválida bloqueia o envio.

O cliente aceita HTTP apenas em loopback (`localhost`/IP de loopback). Fora da máquina,
exige HTTPS, host exato na allowlist e Bearer token; bloqueia redirects, quick tunnels,
credenciais na URL e respostas/requisições acima dos limites. O timeout aceito é de
`0.5` a `30` segundos.

## Consentimentos independentes

O “Copiloto ao Vivo” possui dois consentimentos distintos:

1. compartilhar os quadros com o backend configurado; e
2. autorizar, somente naquela sessão, o envio da versão redigida ao VLM remoto.

O segundo fica desligado por padrão. Cada requisição remota precisa trazer
`remote_vlm_consent=true` e um `remote_vlm_session_id` efêmero. O backend envia somente o
SHA-256 desse identificador e solicita `no-store`; a retenção real do provedor/túnel ainda
precisa ser auditada pelo operador.

## Avaliação autorizada e fail-closed

Execute a partir de `backend`, somente sobre imagens próprias/autorizadas:

```powershell
.\.venv\Scripts\python.exe scripts\vlm_eval.py --consent-authorized C:\corpus-autorizado
```

O flag confirma apenas que o operador verificou a autorização do corpus; não substitui o
manifesto, a política de retenção ou a revisão dos termos. Cada imagem precisa de um
gabarito adjacente `<nome>.truth.json` (preferido) ou `<nome>.json`, com pelo menos
`hole`, `board` e `pot`; `n_players` e `position` podem ampliar o estado exato. Sidecar
inválido, imagem sem gabarito ou inferência que falha tornam o gate **INCOMPLETE** (exit
`2`), nunca uma amostra artificialmente rápida. Estado inexato, estrutura inválida ou
latência acima de 4 s tornam o gate **FAIL** (exit `1`). Cartas extras e duplicadas reduzem
a precisão; não basta recuperar as cartas verdadeiras.

Um exit `0` significa somente que a **extração bruta** foi exata e ficou no orçamento em
todo o corpus rotulado daquela execução. Não altera `confidence=0.0`, não transforma a
proposta em decisão e não promove modelo. O script também falha se endpoint, token,
allowlist, timeout ou redação estiverem incompletos.

Para qualquer hipótese de promoção futura, congele modelo/revisão/hashes, crie um holdout
cego agrupado por cliente/sessão/tema, meça exact-state, calibração, risco-cobertura e
latência, e compare com os leitores locais. Até esse protocolo existir e passar, F3 é
somente uma proposta inspecionável e nunca autoriza uma jogada.
