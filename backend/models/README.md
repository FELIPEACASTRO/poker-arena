# Artefatos de modelo

## Promoção científica do detector de mesa

Estados `approved`/`promoted` do artefato `vision` exigem agora um
`promotion_receipt` local, hash-pinado e válido no perfil
`poker-arena-external-vision-v2-2026-08-07`. O receipt inclui o ambiente de execução
(SO, arquitetura, Python, Pillow, ONNX Runtime, provider, CPU lógico e escopo da medição)
e é produzido somente pelo
runner que executa o candidato e o pipeline F2 real sobre holdout autorizado;
predictions importadas não autorizam promoção. Ele liga modelo, dataset,
protocolo de anotação, código/configuração do pipeline, lock de dependências,
exact-state, IC, falso aceite, calibração, subgrupos e latência.

O loader revalida o receipt inclusive em cache hit. Evidência ausente, alterada,
`fail`, de outro SHA ou de pipeline antigo bloqueia o runtime. Esse perfil não
pode autorizar `expert` nem `card_reader`, cujas tarefas exigem protocolos
próprios. `scripts/promote_model.py` cria uma proposta nova e nunca sobrescreve
o manifesto ativo.

## Limite de confianca do manifesto v1

O objeto raiz e fechado: aceita exatamente `schema_version`, `artifacts` e, quando
presente, `snapshot_date` no formato de data civil `YYYY-MM-DD`. Entradas tambem sao
fechadas por ciclo de vida e tipo de modelo; campos desconhecidos, contratos de tensor
com campos extras e payloads sem limite sao rejeitados sem ecoar seus valores no erro.

Todo `path` e relativo ao diretorio real de `MANIFEST.json`, usa sintaxe POSIX canonica
e portavel e nao pode conter `.`, `..`, barra invertida, ADS (`:`), nomes reservados do
Windows ou aliases de normalizacao. Depois da resolucao de symlink/junction, o arquivo
precisa continuar fisicamente dentro desse diretorio. Caminhos duplicados tambem
invalidam o manifesto inteiro.

Estados materializados (`approved`, `promoted`, `candidate` e `quarantined`) exigem
`installed=true`, SHA-256 minusculo e contrato declarado. O estado `missing` usa um
schema de inventario separado, com `installed=false`, `sha256=null` e contratos
`expected_*`. Metadados embutidos, contexto de treino e politica de inferencia possuem
allowlists e limites proprios; `size_bytes`, quando declarado, e comparado ao arquivo
antes do hashing.

Esta pasta contém artefatos locais ignorados pelo Git. A presença de um `.onnx` não é
prova de qualidade, linhagem ou compatibilidade. O backend só o disponibiliza quando a
entrada correspondente do `MANIFEST.json` está `approved`/`promoted`, o SHA-256 confere,
licença e linhagem estão resolvidas e o contrato de tensores é compatível.

O schema v1 é estrito: `schema_version` precisa ser o inteiro `1`, chaves JSON duplicadas
são rejeitadas e cada entrada usa governança estruturada. `status` só pode ser `verified`
ou `unresolved`; uma entrada verificada exige `id` e `reference` (HTTPS ou URN) fornecidos
pelo responsável pelo artefato. Os antigos campos textuais `license_status` e
`lineage_status` não são aceitos.
Referências HTTPS precisam usar host público, porta padrão e caminho específico, sem
userinfo, query ou fragmento; URNs precisam ser canônicas. Assim, tokens, URLs assinadas
e fragmentos sensíveis não entram no manifesto governado.

Um artefato `candidate` tem uma via separada, exclusivamente para avaliação offline por
`EvaluationMLBot`. Ele continua indisponível em `MLBot`, `available_levels()` e
`BotFactory`; somente revisão independente e mudança explícita para `approved`/`promoted`
podem habilitar o runtime. A avaliação também exige SHA-256, contrato, licença e linhagem
verificados — não completa nem infere esses dados.

Verificações bem-sucedidas são cacheadas em memória pela combinação de caminhos, uso e
tipo, vinculadas à identidade `device/inode/size/mtime_ns` do modelo e do manifesto. Uma
mudança invalida o recibo e força nova verificação criptográfica; falhas nunca são
cacheadas. Os loaders revalidam a identidade depois de abrir a sessão ONNX para fechar a
janela de troca entre verificação e uso.

| Artefato | Estado local | Estado de runtime | Contrato | Evidência/linhagem |
|---|---|---|---|---|
| `poker_expert.onnx` | instalado | **quarentena** | `obs` `(batch,121)` → `logits` `(batch,5)` | linhagem e licença do peso não resolvidas |
| `poker_expert_v1_backup.onnx` | instalado | **quarentena** | mesmo contrato | backup; relação de treino não comprovada |
| `poker_vision.onnx` | instalado | **quarentena** | `images` `(1,3,640,640)` → `(1,58,8400)` | metadados YOLO11n/AGPL-3.0; linhagem parcial |
| `card_reader.onnx` | **ausente** | indisponível | esperado `(1,3,96,64)` → rank/suit | gate incompleto; o fallback ZNCC não é equivalente |

O inventário verificável está em [`MANIFEST.json`](MANIFEST.json). Detalhes e limitações:

- [`MODEL_CARD_POKER_EXPERT.md`](MODEL_CARD_POKER_EXPERT.md)
- [`MODEL_CARD_POKER_EXPERT_V1_BACKUP.md`](MODEL_CARD_POKER_EXPERT_V1_BACKUP.md)
- [`MODEL_CARD_POKER_VISION.md`](MODEL_CARD_POKER_VISION.md)
- [`MODEL_CARD_CARD_READER.md`](MODEL_CARD_CARD_READER.md)

Importante: a correção do parser compacto PokerBench ocorreu depois dos pesos atuais.
Sem um manifesto de treino que ligue dataset/código/checkpoint ao hash, não se pode afirmar
que estes pesos foram treinados com a versão corrigida. Re-treino e novas métricas não foram
fabricados nesta revisão.

Os antigos pós-processamentos do Expert (`temperature=0.75`, `min_prob_ratio=0.15`,
`sizing_jitter=0.12`) estão registrados como `unapproved` e não são aplicados. Sem uma
configuração `inference_policy` aprovada no manifesto, o runtime usa `1.0/0.0/0.0`,
preservando a distribuição legal e o tamanho discreto produzidos pela política.
