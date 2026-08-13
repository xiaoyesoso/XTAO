import type { OrchestratorConfig } from '../types';

interface Props {
  config: Partial<OrchestratorConfig>;
  onChange: (c: Partial<OrchestratorConfig>) => void;
}

export function SettingsPanel({ config, onChange }: Props) {
  const update = (patch: Partial<OrchestratorConfig>) => onChange({ ...config, ...patch });

  return (
    <aside className="settings-panel">
      <h2>运行配置</h2>
      <p className="settings-hint">这些参数会作为 <code>config</code> 传入 <code>/api/plan/run</code>。</p>

      <label className="field toggle">
        <input
          type="checkbox"
          checked={!!config.use_tao}
          onChange={(e) => update({ use_tao: e.target.checked })}
        />
        <span>启用 TAO 步骤级执行</span>
      </label>

      <label className="field toggle">
        <input
          type="checkbox"
          checked={!!config.enable_tcc_replan}
          onChange={(e) => update({ enable_tcc_replan: e.target.checked })}
        />
        <span>启用 TCC Replan（高风险场景）</span>
      </label>

      <label className="field">
        <span>最大 Replan 次数</span>
        <input
          type="number"
          min={0}
          max={10}
          value={config.max_replan_count ?? 3}
          onChange={(e) => update({ max_replan_count: Number(e.target.value) })}
        />
      </label>

      <label className="field">
        <span>验证阈值</span>
        <input
          type="number"
          min={0}
          max={1}
          step={0.05}
          value={config.verification_threshold ?? 0.8}
          onChange={(e) => update({ verification_threshold: Number(e.target.value) })}
        />
      </label>

      <label className="field">
        <span>TAO 最大循环数</span>
        <input
          type="number"
          min={1}
          max={50}
          value={config.tao_max_loops ?? 10}
          onChange={(e) => update({ tao_max_loops: Number(e.target.value) })}
        />
      </label>
    </aside>
  );
}
