import type { StepExecutionRecord } from '../types';

interface Props {
  records: StepExecutionRecord[];
}

const STEP_STATUS_LABEL: Record<string, string> = {
  pending: '待执行',
  running: '执行中',
  done: '完成',
  failed: '失败',
};

export function StepTrace({ records }: Props) {
  if (records.length === 0) {
    return (
      <div className="step-trace">
        <div className="section-label">步骤轨迹</div>
        <span className="muted">无步骤记录</span>
      </div>
    );
  }
  return (
    <div className="step-trace">
      <div className="section-label">步骤轨迹</div>
      <ol className="step-list">
        {records.map((r, i) => (
          <li key={r.step_id ?? i} className={`step-item step-${r.status}`}>
            <div className="step-head">
              <span className="step-index">#{i + 1}</span>
              <code className="step-id">{r.step_id}</code>
              <span className={`step-status status-${r.status}`}>
                {STEP_STATUS_LABEL[r.status] ?? r.status}
              </span>
              {r.checkpoint_passed != null && (
                <span className={`tag ${r.checkpoint_passed ? 'tag-ok' : 'tag-bad'}`}>
                  checkpoint {r.checkpoint_passed ? '通过' : '未通过'}
                </span>
              )}
              {r.correction_applied && <span className="tag tag-warn">纠偏: {r.correction_applied}</span>}
              {r.replan_triggered && <span className="tag tag-warn">触发 replan</span>}
              {r.tao_used && <span className="tag tag-info">TAO ×{r.tao_loops}</span>}
            </div>
            <div className="step-objective">{r.step_objective}</div>
            {r.output && <pre className="step-output">{r.output}</pre>}
            {r.root_cause_step_id && (
              <div className="step-cause">根因步骤: <code>{r.root_cause_step_id}</code></div>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
