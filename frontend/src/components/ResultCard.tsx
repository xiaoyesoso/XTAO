import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { OrchestratorResult } from '../types';
import { useI18n } from '../i18n';
import { G4CSummary } from './G4CSummary';
import { StepTrace } from './StepTrace';

interface Props {
  result: OrchestratorResult;
  timings?: Record<string, number>;
  totalMs?: number;
}

function fmtMs(ms?: number): string {
  if (ms == null) return '-';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function ResultCard({ result, timings, totalMs }: Props) {
  const [showG4C, setShowG4C] = useState(false);
  const { t } = useI18n();
  const statusClass = `status-${result.status}`;
  const finalOutput = result.step_records
    .filter((s) => s.output)
    .map((s) => s.output)
    .join('\n\n');

  return (
    <div className="bubble assistant-bubble result-card">
      <div className="result-head">
        <span className={`status-badge ${statusClass}`}>
          {t(`status.${result.status}`)}
        </span>
        <div className="metrics">
          <span title="replan">🔁 replan {result.replan_count}</span>
          <span title="iter">🔄 iter {result.iteration_count}</span>
          {result.verification_score != null && (
            <span title="verify">✓ verify {Math.round(result.verification_score * 100)}%</span>
          )}
          <span title="steps">📋 {result.step_records.length} {t('live.steps')}</span>
          {totalMs != null && <span title="total">⏱ {fmtMs(totalMs)}</span>}
        </div>
      </div>

      {timings && (
        <div className="timings-bar">
          <span className="timing-item">{t('timing.gen')} {fmtMs(timings.generate_ms)}</span>
          {timings.verify_ms != null && <span className="timing-item">{t('timing.verify')} {fmtMs(timings.verify_ms)}</span>}
          <span className="timing-item">{t('phase.execute')} {fmtMs(timings.execute_ms)}</span>
        </div>
      )}

      {result.clarify_message && (
        <div className="clarify-box">{t('result.clarify')}: {result.clarify_message}</div>
      )}

      {result.errors.length > 0 && (
        <div className="error-list">
          <strong>{t('result.errors')}</strong>
          <ul>
            {result.errors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </div>
      )}

      {finalOutput && (
        <div className="final-output">
          <div className="section-label">{t('result.finalOutput')}</div>
          <div className="markdown-body">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{finalOutput}</ReactMarkdown>
          </div>
        </div>
      )}

      <div className="card-actions">
        <button className="link-btn" onClick={() => setShowG4C((v) => !v)}>
          {showG4C ? t('result.hideG4C') : t('result.showG4C')}
        </button>
      </div>

      {showG4C && (
        <>
          <G4CSummary plan={result.plan} />
          <StepTrace records={result.step_records} />
        </>
      )}
    </div>
  );
}
