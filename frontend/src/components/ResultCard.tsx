import { useState } from 'react';
import type { OrchestratorResult } from '../types';
import { G4CSummary } from './G4CSummary';
import { StepTrace } from './StepTrace';

interface Props {
  result: OrchestratorResult;
}

const STATUS_LABEL: Record<string, string> = {
  completed: '已完成',
  failed: '失败',
  aborted: '中止',
  clarify_needed: '需澄清',
};

export function ResultCard({ result }: Props) {
  const [showG4C, setShowG4C] = useState(false);
  const statusClass = `status-${result.status}`;
  const finalOutput = result.step_records
    .filter((s) => s.output)
    .map((s) => s.output)
    .join('\n\n');

  return (
    <div className="bubble assistant-bubble result-card">
      <div className="result-head">
        <span className={`status-badge ${statusClass}`}>
          {STATUS_LABEL[result.status] ?? result.status}
        </span>
        <div className="metrics">
          <span title="Replan 次数">🔁 replan {result.replan_count}</span>
          <span title="生成迭代次数">🔄 iter {result.iteration_count}</span>
          {result.verification_score != null && (
            <span title="验证分数">✓ verify {Math.round(result.verification_score * 100)}%</span>
          )}
          <span title="步骤数">📋 {result.step_records.length} 步</span>
        </div>
      </div>

      {result.clarify_message && (
        <div className="clarify-box">需要澄清：{result.clarify_message}</div>
      )}

      {result.errors.length > 0 && (
        <div className="error-list">
          <strong>错误：</strong>
          <ul>
            {result.errors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </div>
      )}

      {finalOutput && (
        <div className="final-output">
          <div className="section-label">最终输出</div>
          <pre>{finalOutput}</pre>
        </div>
      )}

      <div className="card-actions">
        <button className="link-btn" onClick={() => setShowG4C((v) => !v)}>
          {showG4C ? '收起 G4C 与步骤轨迹' : '展开 G4C 与步骤轨迹'}
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
