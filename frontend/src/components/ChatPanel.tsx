import { useState, type KeyboardEvent } from 'react';
import type { ChatMessage } from '../App';
import { useI18n } from '../i18n';
import { ResultCard } from './ResultCard';
import { LiveProgress } from './LiveProgress';

interface Props {
  messages: ChatMessage[];
  onSend: (text: string) => void;
}

export function ChatPanel({ messages, onSend }: Props) {
  const [input, setInput] = useState('');
  const { t, lang } = useI18n();

  const submit = () => {
    const text = input.trim();
    if (!text) return;
    onSend(text);
    setInput('');
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const examples = lang === 'zh'
    ? [
        '帮我把一份 3 页财报总结成 5 个要点',
        '调研并对比三个主流向量数据库的优缺点',
        '规划一次为期 5 天的东京行程',
      ]
    : [
        'Summarize a 3-page financial report into 5 key points',
        'Research and compare three mainstream vector databases',
        'Plan a 5-day trip to Tokyo',
      ];

  const placeholder = lang === 'zh'
    ? '输入任务，Enter 发送，Shift+Enter 换行'
    : 'Enter task, Enter to send, Shift+Enter for newline';

  return (
    <section className="chat-panel">
      <div className="messages">
        {messages.length === 0 && (
          <div className="empty-hint">
            <p>{lang === 'zh' ? '输入一个任务，例如：' : 'Try one of these tasks:'}</p>
            <ul>
              {examples.map((ex) => (
                <li key={ex}>{ex}</li>
              ))}
            </ul>
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`msg msg-${m.role}`}>
            {m.role === 'user' ? (
              <div className="bubble user-bubble">{m.content}</div>
            ) : m.stream ? (
              <LiveProgress stream={m.stream} />
            ) : m.loading ? (
              <div className="bubble assistant-bubble loading">
                <span className="dot" />
                <span className="dot" />
                <span className="dot" />
                <span className="loading-text">{t('chat.thinking')}</span>
              </div>
            ) : m.error ? (
              <div className="bubble assistant-bubble error-bubble">
                <strong>{t('chat.error')}</strong>
                <pre>{m.error}</pre>
              </div>
            ) : m.result ? (
              <ResultCard result={m.result} timings={m.timings} totalMs={m.totalMs} />
            ) : null}
          </div>
        ))}
      </div>
      <div className="composer">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKey}
          placeholder={placeholder}
          rows={2}
        />
        <button onClick={submit} disabled={!input.trim()}>
          {t('chat.send')}
        </button>
      </div>
    </section>
  );
}
