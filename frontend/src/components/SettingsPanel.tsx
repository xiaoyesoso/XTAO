import type { OrchestratorConfig } from '../types';
import { useI18n } from '../i18n';

interface Props {
  config: Partial<OrchestratorConfig>;
  onChange: (c: Partial<OrchestratorConfig>) => void;
}

export function SettingsPanel({ config, onChange }: Props) {
  const update = (patch: Partial<OrchestratorConfig>) => onChange({ ...config, ...patch });
  const { t, lang } = useI18n();

  return (
    <aside className="settings-panel">
      <h2>{t('settings.title')}</h2>
      <p className="settings-hint">
        {lang === 'zh'
          ? '这些参数会作为 config 传入 /api/plan/run。'
          : 'These parameters are passed as config to /api/plan/run.'}
      </p>

      <label className="field toggle">
        <input
          type="checkbox"
          checked={!!config.use_tao}
          onChange={(e) => update({ use_tao: e.target.checked })}
        />
        <span>{t('settings.useTao')}</span>
      </label>

      <label className="field toggle">
        <input
          type="checkbox"
          checked={!!config.skip_checkpoint}
          onChange={(e) => update({ skip_checkpoint: e.target.checked })}
        />
        <span>{t('settings.skipCheckpoint')}</span>
      </label>

      <label className="field toggle">
        <input
          type="checkbox"
          checked={!!config.enable_tcc_replan}
          onChange={(e) => update({ enable_tcc_replan: e.target.checked })}
        />
        <span>{t('settings.tccReplan')}</span>
      </label>

      <label className="field">
        <span>{t('settings.maxReplan')}</span>
        <input
          type="number"
          min={0}
          max={10}
          value={config.max_replan_count ?? 3}
          onChange={(e) => update({ max_replan_count: Number(e.target.value) })}
        />
      </label>

      <label className="field">
        <span>{t('settings.verifyThreshold')}</span>
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
        <span>{t('settings.taoMaxLoops')}</span>
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
