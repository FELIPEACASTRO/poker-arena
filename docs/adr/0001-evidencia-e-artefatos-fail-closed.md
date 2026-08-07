# ADR 0001: evidência e artefatos científicos fail-closed

- Estado: aceita
- Data: 2026-07-18

## Contexto

O projeto combina jogo, visão computacional, modelos de decisão e notebooks de pesquisa.
Metadados de arquivo (`mtime` e tamanho), resultados brutos de notebook e descrições de
catálogo externo não provam que bytes, dados ou métricas permanecem os mesmos. Aceitar
essas aproximações como evidência permitiria troca silenciosa de pesos, vazamento entre
splits ou promoção de um modelo sem calibração externa.

## Decisão

1. A identidade de pesos, datasets e recibos é o SHA-256 dos bytes. Metadados do sistema
   de arquivos podem ajudar desempenho, mas nunca substituem a revalidação do conteúdo.
2. Recibos retornados ao chamador são snapshots defensivos e não permitem alterar o
   estado interno do verificador por referências mutáveis aninhadas.
3. Um artefato só entra no runtime quando manifesto, status aprovado, licença, linhagem,
   contrato de tensores e hash instalado forem todos compatíveis. Ausência ou ambiguidade
   bloqueia a ativação.
4. Fontes remotas são apenas candidatas até que revisão, licença, revisão imutável e
   proveniência sejam verificadas. Endereços locais, privados, de metadados ou redirects
   para essas redes não são fontes públicas válidas.
5. Extração bruta, acurácia em corpus sintético e execução bem-sucedida de notebook não
   promovem modelo. Promoção exige split agrupado sem vazamento, holdout temporal/humano,
   métricas pré-registradas, calibração e comparação reproduzível com o baseline.
6. Avaliadores e notebooks falham fechados: amostra ausente, truth inválida, inferência
   que cai em fallback ou execução parcial produzem estado incompleto/reprovado, nunca
   aprovação implícita.

## Consequências

- Verificar um artefato pode reler seus bytes; o custo é aceito em troca da integridade.
- Descobertas em Kaggle, Hugging Face, artigos ou outras plataformas alimentam uma fila
  de experimentos, não o runtime de produção.
- GPU/CPU remota só é usada quando existe candidato governado e experimento capaz de
  mudar uma decisão. Resultados negativos e incompletos permanecem registrados.

