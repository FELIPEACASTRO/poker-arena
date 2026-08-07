# Governança de datasets de ML

O Poker Arena só deve treinar, avaliar ou comparar modelos com um manifesto que
passe integralmente pelo validador fail-closed. O verificador é somente leitura:
ele não baixa, corrige, move ou publica dados.

## Contrato v1

O schema normativo está em
[`schemas/dataset-manifest-v1.schema.json`](schemas/dataset-manifest-v1.schema.json)
e um modelo preenchível em
[`examples/dataset-manifest.example.json`](examples/dataset-manifest.example.json).
A versão do dataset identifica o snapshot lógico; `source_version` fixa a versão
de origem de cada amostra.

Além de `schema_version: 1`, todo manifesto deve declarar exatamente
`profile_revision: poker-arena-dataset-manifest-v1-2026-07-18`. Esse valor é
imutável: ele identifica o conjunto concreto de restrições executáveis, sem
depender de um alias móvel como `latest`. Um manifesto com revisão ausente ou
diferente falha antes de qualquer arquivo de amostra ser lido.

O contrato v1 modela **uma entidade/jogador por arquivo-amostra**. Ele serve para
capturas, imagens e registros já materializados dessa forma; um hand history com
vários jogadores não pode ser forçado nesse formato escolhendo arbitrariamente
um único `hashed_player_id`. Esse tipo de corpus exige um contrato específico de
hand history ou uma transformação autorizada, documentada e sem perda de
linhagem antes de usar este validador.

Cada amostra deve registrar:

- identidade e caminho relativo únicos;
- SHA-256 do conteúdo;
- fonte e versão da fonte, sessão, cliente, tema e baralho;
- `hashed_player_id` pseudonimizado, `event_time` com fuso horário e
  `split_group` estável;
- `player_pseudonym` somente quando existir um alias sintético não reversível;
- split; e
- licença explicitamente aprovada pela política.

Os campos usados para identidade, agrupamento ou detecção de leakage (`id`,
`session`, `client`, `theme`, `deck`, `split_group`, `split` e, quando presente,
`player_pseudonym`) usam apenas ASCII minúsculo, dígitos, `.`, `_` e `-`, devem
começar e terminar em letra ou dígito e têm no máximo 128 caracteres. `source`
segue o mesmo princípio, permitindo `/` apenas entre segmentos canônicos de um
registro hierárquico. Formas Unicode visualmente equivalentes, caixa diferente,
segmentos vazios e separadores finais são rejeitados em vez de normalizados.

`path` é sempre uma forma lexical POSIX, relativa, ASCII minúscula e canônica.
Não são aceitos `\\`, `:`, Alternate Data Streams do Windows, caminho absoluto,
segmentos vazios, `.`/`..`, nomes reservados do Windows (`con`, `nul`, `com1`,
etc.), arquivo oculto iniciado por ponto ou segmento terminado por ponto. Os
caminhos devem ser únicos em três níveis: texto lexical, destino resolvido e
identidade do arquivo (`device` + `inode`/FileId). Isso bloqueia hard links,
symlinks e aliases que tentem fazer duas amostras apontarem para o mesmo objeto.

`hashed_player_id` não pode ser nome de usuário, e-mail, account ID ou hash
simples de identificador de baixa entropia. Gere-o fora do manifesto com HMAC
SHA-256 e segredo gerenciado, usando a mesma versão de chave em todos os splits;
grave no manifesto apenas o digest hexadecimal canônico. O bloco obrigatório
`policy.player_identity` torna esse contrato verificável: `scheme` deve ser
`hmac-sha256`, `key_version` deve ser um ID opaco iniciado por `kv-`,
`separation_context` deve declarar o rótulo público de separação de domínio e
`purpose` deve ser `split-leakage-prevention`.

O segredo HMAC e qualquer material de chave nunca devem aparecer no manifesto.
Campos extras são rejeitados pelo contrato fechado, referências aceitam apenas
IDs opacos e valores ou nomes de campos não reconhecidos não são ecoados no
relatório. Isso reduz vazamentos acidentais, mas nenhum padrão sintático consegue
provar que um texto alfanumérico não é um segredo; revisão humana e secret
scanning continuam obrigatórios. O validador não recebe nem revela a chave.
`player_pseudonym` é opcional e não substitui o hash obrigatório.

`allowed_licenses` é uma allowlist revisada, não uma inferência automática de
compatibilidade jurídica. Campo ausente, marcador como `UNKNOWN`, ou licença que
não esteja nessa lista bloqueia o dataset. Antes de adicionar uma licença à
allowlist, registre a revisão de direitos de uso, redistribuição e treinamento.

`group_disjoint_keys` define as chaves que não podem cruzar splits. A política do
exemplo impede simultaneamente vazamento de uma mesma fonte/sessão e do mesmo
conjunto cliente/tema/baralho. O mesmo SHA-256 em splits diferentes sempre
bloqueia; duplicatas dentro de um split são bloqueadas quando
`reject_duplicates_within_split` é `true`.

Independentemente de `group_disjoint_keys`, o validador bloqueia o mesmo
`hashed_player_id`, `player_pseudonym` (quando presente), `session` ou
`split_group` em splits diferentes. Repetições dentro de um mesmo split são
permitidas para representar vários eventos da mesma entidade, desde que os
demais controles de ID, arquivo, hash e grupos sejam satisfeitos.

### Consumo por notebooks de visão

O notebook 09 não trata a aprovação do manifesto como aprovação implícita de
rótulos YOLO externos. Para um corpus real, ele exige checkout local em commit
imutável, chama `validate_manifest(..., requested_use="model-training")`, liga
exatamente cada amostra aprovada a uma imagem e a um label, e rejeita arquivos
extras, ausentes, classes desconhecidas, coordenadas não finitas ou fora dos
limites. O split e o grupo vêm do manifesto validado, nunca do nome do arquivo.

Antes do treino, o notebook também grava um receipt lateral com SHA-256 de imagem
e label e hash perceptual dHash, bloqueando pares entre splits com distância de
Hamming pequena. Esse receipt é ligado por hash ao manifesto do candidato. Ele é
um controle adicional do consumidor: não amplia a licença, não prova ausência de
leakage semântico e não transforma o bundle em modelo promovido. O notebook 08 e
o notebook 11 geram apenas dados sintéticos e bundles candidatos; validação em
screenshots reais, governança e promoção continuam sendo etapas independentes.

Quando `policy.temporal_order` é declarado, `split_order` deve listar exatamente
todos os splits permitidos. O maior `event_time` de cada split anterior precisa
ser menor que o menor timestamp de cada split posterior. A igualdade na
fronteira só é aceita quando `allow_equal_boundary` for explicitamente `true`.
Sem `temporal_order`, timestamps continuam obrigatórios e validados, mas não se
infere uma cronologia que o responsável pelo dataset não declarou.
Um `event_time` mais de cinco minutos à frente do relógio de validação é sempre
rejeitado, independentemente de `temporal_order`; a pequena tolerância cobre
somente deriva operacional de relógio.

Todos os timestamps (`event_time` e `retention.expires_at`) usam a única forma
canônica RFC 3339 UTC com precisão de segundos: `YYYY-MM-DDTHH:MM:SSZ`. Espaço
no lugar de `T`, offset `+00:00`, frações de segundo, timezone ausente e datas
impossíveis são rejeitados; o validador não normaliza representações alternativas.

## Política machine-readable

O bloco `policy` também exige:

- `consent.status` (`obtained` ou `not-required`) e referência de evidência;
- `legal_basis.basis` em enumeração fechada e referência da revisão;
- `redaction` com remoção de identificadores, screen names e revisão de texto
  livre explicitamente verdadeiras, além do modo de verificação;
- `permitted_use` em allowlist fechada;
- `real_money: false`; qualquer outro valor bloqueia o corpus;
- status e referência da revisão de `platform_terms`;
- uma ou mais jurisdições ISO 3166-1 alpha-2 em allowlist fechada;
- `player_identity` com algoritmo HMAC, versão opaca de chave, contexto público
  de separação e finalidade fechada, sem nenhum segredo;
- `retention.expires_at` com timezone, estritamente posterior ao relógio da
  validação, e intervalo de revisão; e
- `deletion` com remoção por solicitação, por expiração, procedimento
  versionado e verificação obrigatória.

Referências como `consent-batch-2026-01` devem ser IDs internos opacos de 3 a 128
caracteres (`A-Z`, `a-z`, dígitos, `.`, `_` e `-`), nunca URL, path, PII,
credencial ou texto de consentimento. `source` também é apenas um identificador
de registro canônico, não uma URL; a URL e sua eventual credencial ficam no
sistema autorizado de procedência. O validador verifica a presença e a
coerência do contrato; a validade jurídica da evidência continua exigindo
revisão humana autorizada.

### Compatibilidade segura

O identificador `schema_version: 1` foi preservado, mas a revisão reproduzível
acima é obrigatória porque o perfil foi endurecido. Não existe upgrade silencioso.
Para migrar um manifesto v1 antigo:

1. adicione a revisão exata `poker-arena-dataset-manifest-v1-2026-07-18`;
2. inclua todos os blocos de governança e os campos obrigatórios
   `player_identity`, `hashed_player_id`, `event_time` e `split_group`;
3. converta IDs, fontes, paths e timestamps para as formas canônicas descritas
   acima e elimine aliases lexicais, resolvidos ou por FileId;
4. preserve e confira os SHA-256 dos arquivos; a migração de metadados não deve
   alterar silenciosamente o conteúdo das amostras; e
5. grave o novo manifesto, registre seu novo SHA-256 e execute novamente a
   validação check-only antes de autorizar qualquer consumo.

O digest do manifesto necessariamente muda quando a revisão ou qualquer
metadado muda. Apenas `player_pseudonym` e `temporal_order` são opcionais:
omiti-los não reduz os gates obrigatórios.

## Verificação check-only

Execute a partir de `backend`:

```powershell
.\.venv\Scripts\python.exe -m poker_arena.ml.data_manifest `
  --manifest C:\caminho\dataset\manifest.json `
  --root C:\caminho\dataset `
  --purpose model-training `
  --pretty
```

Substitua `C:\caminho\dataset` pelo diretório autorizado. O pacote não contém um corpus
`datasets/` pronto, e o validador não cria nem baixa esse diretório.

O processo retorna `0` apenas quando todos os campos, arquivos e hashes passam;
retorna `1` para qualquer reprovação. O JSON de saída contém somente códigos,
índices e nomes de campos conhecidos: valores de fonte, cliente, paths absolutos
e conteúdo de arquivos não são ecoados. Quando o manifesto pôde ser capturado,
`manifest_receipt` identifica exatamente os bytes observados por SHA-256,
tamanho, identidade do arquivo e timestamps de metadata, sem expor o path. Guarde
esse recibo junto ao artefato de treinamento para rastreabilidade.

`--purpose` é opcional para uma auditoria neutra do manifesto. Em qualquer job
que efetivamente consuma dados, informe a finalidade concreta; o processo falha
com `use_not_permitted` se ela não estiver em `policy.permitted_use`. A API
Python oferece o mesmo gate por `validate_manifest(..., requested_use=...)`.
Para testes determinísticos e auditorias reproduzíveis, a API Python aceita um
`now` timezone-aware injetado; produção deve omiti-lo para usar UTC atual.

## Controles de segurança e integridade

- JSON ambíguo com chaves duplicadas, versões desconhecidas, inteiros
  patologicamente grandes, números não finitos ou tokens numéricos além do
  perfil limitado é rejeitado sem ecoar o token ofensivo.
- Campos extras são rejeitados, evitando aceitar metadados ignorados.
- Caminhos não canônicos, ADS, nomes reservados, travessia e links que resolvam
  fora do root são rejeitados; aliases lexical, resolvido e por FileId também.
- Arquivo ausente, não regular, ilegível, maior que 1 GiB, alterado durante a
  leitura ou com hash divergente é rejeitado.
- IDs, hashes e grupos são comparados globalmente, antes de autorizar o uso.
- Player, pseudônimo, sessão e `split_group` não podem cruzar splits.
- Timestamps sem timezone, datas impossíveis, eventos materialmente futuros,
  retenção já expirada, retenção anterior ao evento e sobreposição temporal
  declarada são rejeitados.
- Política incompleta, marcadores desconhecidos, `real_money: true` ou controles
  de redação/deleção falsos são rejeitados.
- A identidade pseudonimizada exige HMAC SHA-256 e metadados públicos exatos;
  o contrato fechado e os padrões restritos reduzem, mas não substituem, a
  detecção independente de segredos.
- O manifesto é limitado a 10 MiB e 1.000.000 de amostras para reduzir abuso de
  recursos. Cada arquivo é limitado a 1 GiB; um dataset validável é limitado a
  100.000 arquivos e 100 GiB agregados. Esses números limitam o trabalho do
  verificador, não demonstram qualidade, licença ou adequação científica.
- A validação ocorre em duas fases: política, estrutura, paths, aliases, grupos,
  timestamps e limites agregados precisam passar globalmente antes do primeiro
  byte de amostra ser hasheado. Um erro em qualquer amostra bloqueia o hashing
  de todas elas.
- Cada arquivo tem identidade, tamanho e timestamps de metadata comparados
  antes/depois do hashing em streaming para detectar substituição observável.
  O relatório é limitado a 256 erros, com sentinela explícita quando há
  supressão, sem reproduzir chaves ou valores adversariais.

O manifesto também é lido por descritor em um snapshot limitado, com comparação
entre descritor e path antes/depois da leitura. Ao terminar, o validador captura
o path novamente e compara identidade, metadata e SHA-256 com o recibo inicial;
qualquer divergência produz `manifest_changed_during_validation`. Isso fecha
trocas observáveis durante a execução, mas não torna um path gravável imutável.

A validação comprova o snapshot observado naquele instante; ela não mantém o
arquivo imutável depois do retorno. O consumidor deve trabalhar sobre storage
read-only/content-addressed ou revalidar imediatamente antes do uso. Não use o
mesmo path gravável para validar e depois treinar sem esse controle.

O JSON Schema documenta a forma estrutural. As invariantes cruzadas — arquivo,
hash, allowlists, duplicatas, grupos entre splits, relações de consentimento e
ordem temporal, comparação com o relógio atual e validade da retenção — são
aplicadas pelo validador Python e não podem ser comprovadas apenas com JSON
Schema.
