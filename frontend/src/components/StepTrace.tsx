import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { StepExecutionRecord } from '../types';
import { useI18n } from '../i18n';

interface Props {
  records: StepExecutionRecord[];
}

const STEP_STATUS_KEY: Record<string, string> = {
  pending: 'step.pending',
  running: 'step.running',
  done: 'step.done',
  failed: 'step.failed',
};

export function StepTrace({ records }: Props) {
  const { t, lang } = useI18n();
  if (records.length === 0) {
    return (
      <div className="step-trace">
        <div className="section-label">{lang === 'zh' ? '步骤轨迹' : 'Step Trace'}</div>
        <span className="muted">{t('trace.noRecords')}</span>
      </div>
    );
  }
  return (
    <div className="step-trace">
      <div className="section-label">{lang === 'zh' ? '步骤轨迹' : 'Step Trace'}</div>
      <ol className="step-list">
        {records.map((r, i) => (
          <li key={r.step_id ?? i} className={`step-item step-${r.status}`}>
            <div className="step-head">
              <span className="step-index">#{i + 1}</span>
              <code className="step-id">{r.step_id}</code>
              <span className={`step-status status-${r.status}`}>
                {STEP_STATUS_KEY[r.status] ? t(STEP_STATUS_KEY[r.status]) : r.status}
              </span>
              {r.checkpoint_passed != null && (
                <span className={`tag ${r.checkpoint_passed ? 'tag-ok' : 'tag-bad'}`}>
                  checkpoint {r.checkpoint_passed ? t('trace.ckPassed') : t('trace.ckFailed')}
                </span>
              )}
              {r.correction_applied && <span className="tag tag-warn">{t('trace.replanTrigger')}: {r.correction_applied}</span>}
              {r.replan_triggered && <span className="tag tag-warn">{t('trace.replanTriggered')}</span>}
              {r.tao_used && <span className="tag tag-info">TAO ×{r.tao_loops}</span>}
            </div>
            <div className="step-objective">{r.step_objective}</div>
            {r.output && (
              <div className="markdown-body step-output">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{r.output}</ReactMarkdown>
              </div>
            )}
            {r.root_cause_step_id && (
              <div className="step-cause">{t('trace.rootCause')} <code>{r.root_cause_step_id}</code></div>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
