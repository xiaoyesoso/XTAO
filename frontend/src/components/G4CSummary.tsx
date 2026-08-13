import type { ReactNode } from 'react';
import type { Plan } from '../types';
import { useI18n } from '../i18n';

interface Props {
  plan: Plan;
}

function Chip({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <span className={`chip ${className}`}>{children}</span>;
}

export function G4CSummary({ plan }: Props) {
  const g = plan.goal;
  const c = plan.context;
  const ch = plan.choice;
  const { t } = useI18n();

  return (
    <div className="g4c-summary">
      <div className="g4c-block">
        <div className="g4c-label">{t('g4c.goal')}</div>
        <div className="g4c-content">
          <div className="goal-text">{g.user_goal}</div>
          {g.success_criteria.length > 0 && (
            <>
              <div className="sub-label">{t('g4c.successCriteria')}</div>
              <ul>
                {g.success_criteria.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      </div>

      <div className="g4c-block">
        <div className="g4c-label">{t('g4c.context')}</div>
        <div className="g4c-content">
          {c.known_facts.length > 0 && (
            <>
              <div className="sub-label">{t('g4c.known')}</div>
              <div className="chip-row">
                {c.known_facts.map((f, i) => (
                  <Chip key={i}>{f}</Chip>
                ))}
              </div>
            </>
          )}
          {c.missing_info.length > 0 && (
            <>
              <div className="sub-label">{t('g4c.missing')}</div>
              <div className="chip-row">
                {c.missing_info.map((f, i) => (
                  <Chip key={i}>{f}</Chip>
                ))}
              </div>
            </>
          )}
          {c.constraints.hard.length > 0 && (
            <>
              <div className="sub-label">{t('g4c.hardConstraints')}</div>
              <div className="chip-row">
                {c.constraints.hard.map((f, i) => (
                  <Chip key={i} className="hard">
                    {f}
                  </Chip>
                ))}
              </div>
            </>
          )}
          {c.constraints.soft.length > 0 && (
            <>
              <div className="sub-label">{t('g4c.softConstraints')}</div>
              <div className="chip-row">
                {c.constraints.soft.map((f, i) => (
                  <Chip key={i}>{f}</Chip>
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      <div className="g4c-block">
        <div className="g4c-label">{t('g4c.choice')}</div>
        <div className="g4c-content">
          <div className="path-text">{ch.selected_path}</div>
          <div className="reason-text"><span className="sub-label">{t('g4c.reason')}</span>{ch.reason}</div>
        </div>
      </div>

      <div className="g4c-block">
        <div className="g4c-label">{t('g4c.checkpoint')}</div>
        <div className="g4c-content">
          {plan.checkpoint.length === 0 ? (
            <span className="muted">{t('g4c.none')}</span>
          ) : (
            <ul>
              {plan.checkpoint.map((cp, i) => (
                <li key={i}>
                  <code>{cp.step_id}</code>: {cp.checks.join(' / ')}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="g4c-block">
        <div className="g4c-label">{t('g4c.correction')}</div>
        <div className="g4c-content">
          {plan.correction.length === 0 ? (
            <span className="muted">{t('g4c.none')}</span>
          ) : (
            <ul>
              {plan.correction.map((co, i) => (
                <li key={i}>
                  <Chip>{co.action.type}</Chip> {co.condition}
                  {co.action.message && <span className="muted"> — {co.action.message}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
