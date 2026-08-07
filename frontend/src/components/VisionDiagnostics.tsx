import { canonicalPosition } from '../positions'
import type { FromImageResult } from '../types'

function visionEngineLabel(engine?: string): string {
  if (engine === 'F3-vlm') return 'F3 · proposta multimodal'
  if (engine === 'F2-onnx') return 'F2 · detector ONNX'
  if (engine === 'F1-template') return 'F1 · baseline por template'
  return engine ? `Motor não catalogado · ${engine}` : 'Motor não identificado'
}

function confidenceLabel(value: number): string {
  if (!Number.isFinite(value) || value < 0 || value > 1) return 'Indisponível'
  return `${Math.round(value * 100)}%`
}

function latencyLabel(value: number | null): string {
  if (value === null || !Number.isFinite(value) || value < 0) return 'Não medida'
  return `${Math.round(value)} ms`
}

function detectedCards(result: FromImageResult): string {
  const sections = [
    result.detected.hole.length ? `Mão ${result.detected.hole.join(' ')}` : null,
    result.detected.board.length ? `Board ${result.detected.board.join(' ')}` : null,
  ].filter(Boolean)
  return sections.join(' · ') || 'Nenhuma carta detectada'
}

export default function VisionDiagnostics({
  result,
  latencyMs,
}: {
  result: FromImageResult
  latencyMs: number | null
}) {
  const abstained = !result.sanity.ok
  const status = abstained
    ? 'Abstenção ativa'
    : result.decision
      ? 'Leitura aceita pelo gate'
      : 'Leitura válida, sem recomendação'
  const failureReasons = abstained
    ? result.sanity.problems.length
      ? result.sanity.problems
      : ['O backend bloqueou a decisão sem retornar um motivo estruturado.']
    : []
  const stacks = Object.values(result.detected.stacks ?? {})

  return (
    <section
      className={`vision-diagnostics ${abstained ? 'is-abstain' : 'is-accepted'}`}
      aria-label="Diagnóstico verificável da leitura de imagem"
    >
      <header className="vision-diag-head">
        <div>
          <span className="vision-diag-kicker">Reconhecimento de imagem</span>
          <h2>Estado proposto e gate de segurança</h2>
        </div>
        <span className="vision-diag-status" role="status">
          {status}
        </span>
      </header>

      <dl className="vision-diag-metrics">
        <div>
          <dt>Motor executado</dt>
          <dd>{visionEngineLabel(result.engine)}</dd>
        </div>
        <div>
          <dt>Confiança reportada</dt>
          <dd>{confidenceLabel(result.detected.confidence)}</dd>
          <small>Sinal interno; não equivale a acurácia ou calibração.</small>
        </div>
        <div>
          <dt>Latência da chamada</dt>
          <dd>{latencyLabel(latencyMs)}</dd>
          <small>Navegador → backend → resposta; não é benchmark.</small>
        </div>
        <div>
          <dt>Decisão</dt>
          <dd>{abstained ? 'Bloqueada' : result.decision ? 'Disponível' : 'Não produzida'}</dd>
        </div>
      </dl>

      <div className="vision-state" aria-label="Estado detectado">
        <h3>Estado detectado</h3>
        <p className="vision-state-cards">{detectedCards(result)}</p>
        <ul>
          <li>Pote: {result.detected.pot ?? 'não detectado'}</li>
          <li>
            Jogadores: {result.detected.n_players > 0 ? result.detected.n_players : 'não detectados'}
          </li>
          <li>
            Posição:{' '}
            {result.detected.position
              ? canonicalPosition(result.detected.position)
              : 'não detectada'}
          </li>
          <li>Stacks: {stacks.length ? stacks.join(', ') : 'não detectados'}</li>
          <li>Fonte do pote: {result.detected.pot_source || 'não informada'}</li>
        </ul>
      </div>

      {failureReasons.length > 0 && (
        <div className="vision-failures" role="alert">
          <h3>Por que a decisão foi bloqueada</h3>
          <ul>
            {failureReasons.map((reason) => <li key={reason}>{reason}</li>)}
          </ul>
        </div>
      )}

      {result.sanity.warnings.length > 0 && (
        <div className="vision-warnings">
          <h3>Avisos da leitura</h3>
          <ul>
            {result.sanity.warnings.map((warning) => <li key={warning}>{warning}</li>)}
          </ul>
        </div>
      )}

      <p className="vision-diag-evidence">
        Esta tela relata uma tentativa individual. Ela não demonstra generalização,
        desempenho em dataset externo nem superioridade entre modelos.
      </p>
    </section>
  )
}
