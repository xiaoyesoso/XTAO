import { useState, type KeyboardEvent } from 'react';
import type { ChatMessage } from '../App';
import { ResultCard } from './ResultCard';

interface Props {
  messages: ChatMessage[];
  onSend: (text: string) => void;
}

export function ChatPanel({ messages, onSend }: Props) {
  const [input, setInput] = useState('');

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

  return (
    <section className="chat-panel">
      <div className="messages">
        {messages.length === 0 && (
          <div className="empty-hint">
            <p>输入一个任务，例如：</p>
            <ul>
              <li>帮我把一份 3 页财报总结成 5 个要点</li>
              <li>调研并对比三个主流向量数据库的优缺点</li>
              <li>规划一次为期 5 天的东京行程</li>
            </ul>
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`msg msg-${m.role}`}>
            {m.role === 'user' ? (
              <div className="bubble user-bubble">{m.content}</div>
            ) : m.loading ? (
              <div className="bubble assistant-bubble loading">
                <span className="dot" />
                <span className="dot" />
                <span className="dot" />
                <span className="loading-text">XTAO 正在规划与执行…</span>
              </div>
            ) : m.error ? (
              <div className="bubble assistant-bubble error-bubble">
                <strong>调用失败</strong>
                <pre>{m.error}</pre>
              </div>
            ) : m.result ? (
              <ResultCard result={m.result} />
            ) : null}
          </div>
        ))}
      </div>
      <div className="composer">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKey}
          placeholder="输入任务，Enter 发送，Shift+Enter 换行"
          rows={2}
        />
        <button onClick={submit} disabled={!input.trim()}>
          发送
        </button>
      </div>
    </section>
  );
}
