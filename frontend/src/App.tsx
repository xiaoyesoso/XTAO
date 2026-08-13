import { useState, useCallback } from 'react';
import type { OrchestratorConfig } from './types';
import { runPlan, ApiError } from './api';
import { ChatPanel } from './components/ChatPanel';
import { SettingsPanel } from './components/SettingsPanel';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  // assistant messages carry either an error or an orchestrator result
  error?: string;
  result?: Awaited<ReturnType<typeof runPlan>>;
  loading?: boolean;
}

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [config, setConfig] = useState<Partial<OrchestratorConfig>>({
    use_tao: false,
    max_replan_count: 3,
    verification_threshold: 0.8,
    enable_tcc_replan: false,
  });

  const send = useCallback(
    async (text: string) => {
      const userMsg: ChatMessage = { id: crypto.randomUUID(), role: 'user', content: text };
      const pendingMsg: ChatMessage = { id: crypto.randomUUID(), role: 'assistant', content: '', loading: true };
      // Build conversation history from prior user turns.
      const history = messages
        .filter((m) => m.role === 'user')
        .map((m) => m.content)
        .join('\n');
      setMessages((prev) => [...prev, userMsg, pendingMsg]);
      try {
        const result = await runPlan(text, config, history);
        setMessages((prev) =>
          prev.map((m) => (m.id === pendingMsg.id ? { ...m, loading: false, result } : m)),
        );
      } catch (err) {
        const msg = err instanceof ApiError ? err.detail : (err as Error).message;
        setMessages((prev) =>
          prev.map((m) => (m.id === pendingMsg.id ? { ...m, loading: false, error: msg } : m)),
        );
      }
    },
    [config, messages],
  );

  return (
    <div className="app-layout">
      <header className="app-header">
        <h1>XTAO Agent Demo</h1>
        <span className="subtitle">G4C 规划与执行 · 对话式调用 /api/plan/run</span>
      </header>
      <div className="app-body">
        <ChatPanel messages={messages} onSend={send} />
        <SettingsPanel config={config} onChange={setConfig} />
      </div>
    </div>
  );
}
