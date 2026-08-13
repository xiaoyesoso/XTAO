import { useState, useCallback, useRef } from 'react';
import type { OrchestratorConfig, OrchestratorResult, Plan } from './types';
import { runPlanStream, ApiError, type StreamEvent } from './api';
import { useI18n } from './i18n';
import { ChatPanel } from './components/ChatPanel';
import { SettingsPanel } from './components/SettingsPanel';

export interface LiveStep {
  step_id: string;
  objective: string;
  status: 'running' | 'done' | 'failed';
  output?: string;
  reasoning?: string;
  checkpoint_passed?: boolean | null;
  replan?: { count: number; correction: string };
  tao?: boolean;
  tao_loops?: number;
  exec_ms?: number;
  checkpoint_ms?: number;
  total_ms?: number;
}

export interface StreamState {
  phase: string;
  phaseMessage?: string;
  totalSteps?: number;
  plan?: Plan;
  planDelta?: string;
  planReasoning?: string;
  generateMs?: number;
  verifyMs?: number;
  verifyScore?: number;
  verifyPassed?: boolean;
  steps: LiveStep[];
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  error?: string;
  result?: OrchestratorResult;
  loading?: boolean;
  stream?: StreamState;
  timings?: Record<string, number>;
  totalMs?: number;
}

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [config, setConfig] = useState<Partial<OrchestratorConfig>>({
    use_tao: false,
    use_iteration: false,
    verify_before_execute: false,
    skip_checkpoint: true,
    max_replan_count: 3,
    verification_threshold: 0.8,
    enable_tcc_replan: false,
  });
  const abortRef = useRef<AbortController | null>(null);

  const send = useCallback(
    async (text: string) => {
      const userMsg: ChatMessage = { id: crypto.randomUUID(), role: 'user', content: text };
      const pendingId = crypto.randomUUID();
      const pendingMsg: ChatMessage = {
        id: pendingId,
        role: 'assistant',
        content: '',
        loading: true,
        stream: { phase: 'generate', steps: [] },
      };
      const history = messages
        .filter((m) => m.role === 'user')
        .map((m) => m.content)
        .join('\n');

      setMessages((prev) => [...prev, userMsg, pendingMsg]);

      const controller = new AbortController();
      abortRef.current = controller;

      const patch = (updater: (m: ChatMessage) => ChatMessage) =>
        setMessages((prev) => prev.map((m) => (m.id === pendingId ? updater(m) : m)));

      try {
        await runPlanStream(
          text,
          config,
          (ev: StreamEvent) => {
            patch((m) => {
              const s: StreamState = { ...(m.stream ?? { phase: 'generate', steps: [] }) };
              const steps = [...s.steps];
              const findIdx = (sid: string) => steps.findIndex((x) => x.step_id === sid);

              switch (ev.type) {
                case 'phase':
                  s.phase = ev.phase;
                  if (ev.message) s.phaseMessage = ev.message;
                  if (ev.total_steps != null) s.totalSteps = ev.total_steps;
                  if (ev.score != null) s.verifyScore = ev.score;
                  if (ev.passed != null) s.verifyPassed = ev.passed;
                  if (ev.elapsed_ms != null && ev.phase === 'verify') s.verifyMs = ev.elapsed_ms;
                  break;
                case 'plan_generated':
                  s.plan = ev.plan;
                  s.planDelta = undefined;
                  s.planReasoning = undefined;
                  if (ev.elapsed_ms != null) s.generateMs = ev.elapsed_ms;
                  break;
                case 'plan_delta':
                  s.planDelta = (s.planDelta ?? '') + ev.delta;
                  break;
                case 'plan_reasoning_delta':
                  s.planReasoning = (s.planReasoning ?? '') + ev.delta;
                  break;
                case 'step_start':
                  if (findIdx(ev.step_id) === -1) {
                    steps.push({
                      step_id: ev.step_id,
                      objective: ev.objective,
                      status: 'running',
                      tao: ev.tao,
                    });
                  }
                  break;
                case 'step_output': {
                  const idx = findIdx(ev.step_id);
                  if (idx !== -1) {
                    steps[idx] = {
                      ...steps[idx],
                      output: ev.output,
                      tao_loops: ev.tao_loops || steps[idx].tao_loops,
                      exec_ms: ev.elapsed_ms,
                    };
                  }
                  break;
                }
                case 'step_output_delta': {
                  const idx = findIdx(ev.step_id);
                  if (idx !== -1) {
                    steps[idx] = {
                      ...steps[idx],
                      output: (steps[idx].output ?? '') + ev.delta,
                    };
                  }
                  break;
                }
                case 'step_reasoning_delta': {
                  const idx = findIdx(ev.step_id);
                  if (idx !== -1) {
                    steps[idx] = {
                      ...steps[idx],
                      reasoning: (steps[idx].reasoning ?? '') + ev.delta,
                    };
                  }
                  break;
                }
                case 'checkpoint': {
                  const idx = findIdx(ev.step_id);
                  if (idx !== -1) steps[idx] = { ...steps[idx], checkpoint_passed: ev.passed, checkpoint_ms: ev.elapsed_ms };
                  break;
                }
                case 'replan': {
                  const idx = findIdx(ev.step_id);
                  if (idx !== -1) {
                    steps[idx] = {
                      ...steps[idx],
                      replan: { count: ev.count, correction: ev.correction },
                    };
                  }
                  break;
                }
                case 'step_done': {
                  const idx = findIdx(ev.step_id);
                  if (idx !== -1) {
                    steps[idx] = { ...steps[idx], status: ev.status as 'done' | 'failed', checkpoint_passed: ev.checkpoint_passed, total_ms: ev.elapsed_ms };
                  }
                  break;
                }
                case 'done':
                  return { ...m, loading: false, result: ev.result, stream: undefined, timings: ev.timings, totalMs: ev.total_ms };
                case 'error':
                  return { ...m, loading: false, error: ev.message, stream: undefined };
              }
              s.steps = steps;
              return { ...m, stream: s };
            });
          },
          history,
          controller.signal,
        );
      } catch (err) {
        if ((err as Error).name === 'AbortError') return;
        const msg = err instanceof ApiError ? err.detail : (err as Error).message;
        patch((m) => ({ ...m, loading: false, error: msg, stream: undefined }));
      }
    },
    [config, messages],
  );

  const { t, lang, setLang } = useI18n();

  return (
    <div className="app-layout">
      <header className="app-header">
        <h1>XTAO Agent Demo</h1>
        <span className="subtitle">{t('app.subtitle')}</span>
        <button
          className="lang-toggle"
          onClick={() => setLang(lang === 'zh' ? 'en' : 'zh')}
        >
          {lang === 'zh' ? 'EN' : '中'}
        </button>
      </header>
      <div className="app-body">
        <ChatPanel messages={messages} onSend={send} />
        <SettingsPanel config={config} onChange={setConfig} />
      </div>
    </div>
  );
}
