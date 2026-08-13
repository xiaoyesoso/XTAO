import type { OrchestratorConfig, OrchestratorResult, Plan } from './types';

const ENDPOINT = '/api/plan/run';
const STREAM_ENDPOINT = '/api/plan/run/stream';

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(`API ${status}: ${detail}`);
    this.status = status;
    this.detail = detail;
  }
}

// Progress events emitted by the streaming endpoint.
export type StreamEvent =
  | { type: 'phase'; phase: string; message?: string; total_steps?: number; score?: number; passed?: boolean; elapsed_ms?: number }
  | { type: 'plan_generated'; plan: Plan; elapsed_ms?: number }
  | { type: 'plan_delta'; delta: string }
  | { type: 'plan_reasoning_delta'; delta: string }
  | { type: 'step_start'; index: number; total: number; step_id: string; objective: string; tao: boolean }
  | { type: 'step_output'; step_id: string; output: string; tao_used: boolean; tao_loops: number; elapsed_ms?: number }
  | { type: 'step_output_delta'; step_id: string; delta: string }
  | { type: 'step_reasoning_delta'; step_id: string; delta: string }
  | { type: 'checkpoint'; step_id: string; passed: boolean; elapsed_ms?: number }
  | { type: 'replan'; step_id: string; count: number; correction: string }
  | { type: 'step_done'; step_id: string; status: string; checkpoint_passed: boolean | null; elapsed_ms?: number }
  | { type: 'done'; result: OrchestratorResult; timings?: Record<string, number>; total_ms?: number }
  | { type: 'error'; message: string };

// Call the main orchestration endpoint POST /api/plan/run (non-streaming).
export async function runPlan(
  userInput: string,
  config?: Partial<OrchestratorConfig>,
  conversationHistory = '',
  signal?: AbortSignal,
): Promise<OrchestratorResult> {
  let resp: Response;
  try {
    resp = await fetch(ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_input: userInput,
        conversation_history: conversationHistory,
        config: config ?? null,
      }),
      signal,
    });
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw err;
    throw new ApiError(0, '无法连接后端服务，请确认 uvicorn 已启动。');
  }

  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const data = await resp.json();
      if (data?.detail) detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* ignore body parse failure */
    }
    throw new ApiError(resp.status, detail);
  }

  return (await resp.json()) as OrchestratorResult;
}

// Stream the orchestration via SSE. Calls onEvent for each progress event.
// EventSource cannot POST, so we use fetch + ReadableStream and parse SSE manually.
export async function runPlanStream(
  userInput: string,
  config: Partial<OrchestratorConfig> | undefined,
  onEvent: (event: StreamEvent) => void,
  conversationHistory = '',
  signal?: AbortSignal,
): Promise<void> {
  let resp: Response;
  try {
    resp = await fetch(STREAM_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({
        user_input: userInput,
        conversation_history: conversationHistory,
        config: config ?? null,
      }),
      signal,
    });
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw err;
    throw new ApiError(0, '无法连接后端服务，请确认 uvicorn 已启动。');
  }

  if (!resp.ok || !resp.body) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const data = await resp.json();
      if (data?.detail) detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* ignore */
    }
    throw new ApiError(resp.status, detail);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE events are separated by a blank line.
    const parts = buffer.split('\n\n');
    buffer = parts.pop() ?? '';
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith('data: ')) continue;
      try {
        onEvent(JSON.parse(line.slice(6)) as StreamEvent);
      } catch {
        /* skip malformed event */
      }
    }
  }
}
