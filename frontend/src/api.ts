import type { OrchestratorConfig, OrchestratorResult } from './types';

const ENDPOINT = '/api/plan/run';

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(`API ${status}: ${detail}`);
    this.status = status;
    this.detail = detail;
  }
}

// Call the main orchestration endpoint POST /api/plan/run.
// conversation_history is optional context from prior turns.
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
