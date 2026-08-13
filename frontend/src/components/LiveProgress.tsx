import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { StreamState } from '../App';
import { useI18n } from '../i18n';

interface Props {
  stream: StreamState;
}

function fmtMs(ms?: number): string {
  if (ms == null) return '';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function LiveProgress({ stream }: Props) {
  const { t } = useI18n();
  const phaseLabel = t(`phase.${stream.phase}`);
  const done = stream.steps.filter((s) => s.status === 'done').length;
  const total = stream.totalSteps ?? stream.steps.length;

  return (
    <div className="bubble assistant-bubble live-progress">
      <div className="live-head">
        <span className="live-dot" />
        <span className="live-phase">{phaseLabel}</span>
        {stream.phaseMessage && <span className="live-msg">{stream.phaseMessage}</span>}
        {stream.phase === 'execute' && (
          <span className="live-counter">{done}/{total} {t('live.steps')}</span>
        )}
        {stream.generateMs != null && stream.phase !== 'generate' && (
          <span className="tag tag-info">{t('timing.gen')} {fmtMs(stream.generateMs)}</span>
        )}
        {stream.verifyMs != null && stream.phase !== 'verify' && (
          <span className="tag tag-info">{t('timing.verify')} {fmtMs(stream.verifyMs)}</span>
        )}
      </div>

      {stream.verifyScore != null && (
        <div className="live-verify">
          {t('live.verifyScore')} {Math.round((stream.verifyScore ?? 0) * 100)}%
          {stream.verifyPassed != null && (
            <span className={`tag ${stream.verifyPassed ? 'tag-ok' : 'tag-bad'}`}>
              {stream.verifyPassed ? t('live.passed') : t('live.notPassed')}
            </span>
          )}
        </div>
      )}

      {stream.planReasoning && !stream.plan && (
        <pre className="reasoning-delta">{stream.planReasoning}<span className="cursor">▋</span></pre>
      )}

      {stream.planDelta && !stream.plan && (
        <pre className="plan-delta">{stream.planDelta}<span className="cursor">▋</span></pre>
      )}

      {stream.steps.length > 0 && (
        <ol className="step-list">
          {stream.steps.map((s, i) => (
            <li key={s.step_id ?? i} className={`step-item step-${s.status}`}>
              <div className="step-head">
                <span className="step-index">#{i + 1}</span>
                <code className="step-id">{s.step_id}</code>
                <span className={`step-status status-${s.status}`}>
                  {s.status === 'running' ? t('step.running') : s.status === 'done' ? t('step.done') : t('step.failed')}
                </span>
                {s.exec_ms != null && <span className="tag tag-info">{t('timing.llm')} {fmtMs(s.exec_ms)}</span>}
                {s.checkpoint_ms != null && <span className="tag tag-info">{t('timing.ck')} {fmtMs(s.checkpoint_ms)}</span>}
                {s.total_ms != null && <span className="tag tag-info">{t('timing.total')} {fmtMs(s.total_ms)}</span>}
                {s.checkpoint_passed != null && (
                  <span className={`tag ${s.checkpoint_passed ? 'tag-ok' : 'tag-bad'}`}>
                    checkpoint {s.checkpoint_passed ? t('live.passed') : t('live.notPassed')}
                  </span>
                )}
                {s.replan && <span className="tag tag-warn">replan #{s.replan.count}</span>}
                {s.tao && <span className="tag tag-info">TAO{s.tao_loops ? ` ×${s.tao_loops}` : ''}</span>}
              </div>
              <div className="step-objective">{s.objective}</div>
              {s.reasoning && <pre className="reasoning-delta">{s.reasoning}<span className="cursor">▋</span></pre>}
              {s.output && (
                <div className="markdown-body step-output">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{s.output}</ReactMarkdown>
                </div>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
