# XTAO

> Agent planning and execution framework based on the **G4C methodology** (Goal, Context, Choice, Checkpoint, Correction).

**中文**：[README.md](README.md)

XTAO is an **Agent planning and execution** framework. It addresses not only "how to generate a good Plan", but also "how a Plan senses deviation, locates root causes, and corrects itself during execution".

The framework consists of three core parts:

- **G4C** (Goal, Context, Choice, Checkpoint, Correction) elevates a Plan from a "step list" to a **checkable, correctable, executable runtime object**.
- **TAO** (Think-Action-Observation) handles **step-level execution**, making the Agent think before acting and observe after acting.
- **Replan** performs **controlled correction** when execution deviates, covering Step / Partial / Global granularities.

G4C systematically eliminates five types of uncertainty during Agent execution: goal uncertainty, context uncertainty, path uncertainty, process uncertainty, and failure uncertainty.

![G4C five-element architecture](docs/images/g4c_architecture.png)

> The diagram above shows how the five G4C elements surround the Plan runtime object. A more complete project overview is available in [docs/wechat_article_xplan.md](docs/wechat_article_xplan.md).

![Frontend Demo screenshot](docs/images/frontend_demo.jpg)

> The built-in React chat demo supports SSE streaming, Markdown rendering, bilingual UI (zh/en), and real-time timing stats. See the [Frontend Demo](#frontend-demo) section for details.

---

## Features

- **G4C Five Elements** — Goal, Context, Choice, Checkpoint, Correction as first-class runtime objects.
- **Replan Mechanism** — Trigger detection, code + LLM dual judgment, three granularity levels (step / partial / global), evidence-based prompt design.
- **TCC Replan** (optional advanced) — Try / Confirm / Cancel three-phase scheme borrowed from distributed transactions, for high-failure-cost, high-side-effect-risk scenarios.
- **Failure Backtracking & Root Cause Localization** — Four key points: failure point, root cause point, rollback point, and replan start point (failure point ≠ root cause point).
- **Trust State Management** — Five states: `Verified` / `Available` / `Suspicious` / `Invalid` / `Dirty`, with cascade marking on dependency chains.
- **Backtracking Levels** — Action / Step / Stage / Global / Cross-turn, with progressive expansion and jump backtracking modes.
- **Candidate Path Retention** — Records alternative paths at decision nodes, supporting fast path switching without re-planning.
- **Iterative Plan Generation** — Generate–evaluate–correct loop with configurable iteration cap.
- **DAG Plan Generation** (optional) — Dependency-aware plan as a directed acyclic graph (linear plan is the default).
- **Plan Quality Evaluation** — Offline G4C 5-dimension analysis + online Prometheus metrics.
- **Replan Effect Evaluation** - Five metrics: root cause accuracy, replan start accuracy, result reuse rate, replan recovery success rate, replan oscillation rate.
- **TAO (Think-Action-Observation) Loop** - Step-level controlled state loop with five structured judgments per round (goal, state, path, stop, risk), candidate action space management, evidence-bound fact extraction, and an optional double-layer supervisor loop for goal drift detection.
- **TAO Quality Evaluation** - Think/Action/Observation/Overall four-layer metrics, LLM-as-judge evaluation, and golden-answer comparison.

## Tech Stack

- **Python 3.11+**
- **FastAPI** — async REST API
- **Pydantic v2** — data models
- **httpx** — async LLM calls (OpenAI-compatible)
- **OpenAI-compatible LLM API** — tested with SiliconFlow DeepSeek

## Project Structure

```
XTAO/
├── src/xtao/
│   ├── main.py                     # FastAPI app entry point
│   ├── api/
│   │   └── routes.py               # REST API routes (incl. main /api/plan/run entry)
│   ├── models/                     # G4C data models (Pydantic)
│   │   ├── plan.py                 # Plan composite (G4C + mode/status)
│   │   ├── goal.py / context.py / choice.py / checkpoint.py / correction.py
│   │   ├── dag.py                  # DAGNode / DAGEdge / DAGPlan
│   │   ├── replan.py / replan_evaluation.py / tcc.py
│   │   ├── backtracking.py         # BacktrackingLevel / CandidatePath / JumpRule
│   │   ├── trust_state.py          # FactEntry / TrustState / TrustStateReport
│   │   ├── tracing.py              # TracingPoint / FailureTracingResult / StepRecord
│   │   ├── tao.py                   # TAO data models (TAOState, ThinkResult, ActionCandidate, etc.)
│   │   └── orchestrator.py          # OrchestratorConfig / OrchestratorResult
│   ├── prompts/                    # Prompt modules (one per G4C element)
│   ├── services/                   # LLMService, RAGService, ConstraintManager,
│   │                               # TrustStateManager, CandidatePathManager,
│   │                               # TAOStateManager
│   ├── engine/                     # Core engine
│   │   ├── plan_generator.py       # 7-step G4C generation
│   │   ├── plan_verifier.py        # G4C 5-dimension scoring
│   │   ├── plan_executor.py        # Step-by-step execution
│   │   ├── correction_handler.py   # 5 strategies: retry/replan/clarify/rollback/abort
│   │   ├── dag_validator.py        # Cycle detection + topological sort
│   │   ├── iteration_loop.py       # Generate-evaluate-correct loop
│   │   ├── replan_engine.py        # Dual judgment + 3 granularities
│   │   ├── tcc_replan.py           # Try/Confirm/Cancel
│   │   ├── backtracking_engine.py  # 5 levels + progressive expansion
│   │   ├── cross_turn_tracker.py   # Cross-turn contamination tracking
│   │   ├── failure_tracer.py       # Failure backtracking + root cause localization
│   │   ├── orchestrator.py         # PlanOrchestrator (main entrypoint engine)
│   │   ├── tao_engine.py           # TAO controlled state loop engine
│   │   ├── tao_think_engine.py     # Five structured Think judgments
│   │   ├── tao_action_runtime.py   # Action abstraction & execution (filters, HA wrappers)
│   │   ├── tao_observation_interpreter.py # Raw output -> structured Observation
│   │   ├── tao_loop_controller.py  # Loop exit + dead-loop/stagnation detection
│   │   └── tao_massive_action_filter.py  # Multi-stage candidate filtering pipeline
│   ├── sdk/                        # Python SDK - async client for the REST API
│   │   ├── client.py               # XTAOClient (covers all granular REST endpoints)
│   │   └── exceptions.py           # XTAOError / APIError / ConnectionError / ...
│   └── evaluation/                 # Metrics, offline analyzer, ReplanEvaluator
│       └── tao_evaluator.py        # TAO quality evaluation (Think/Action/Observation metrics)
├── tests/
│   ├── test_plan.py                # Unit tests (G4C core)
│   ├── test_tao.py                 # Unit tests (TAO models, engine, filtering, loop safety)
│   ├── test_backtracking.py        # Unit tests (backtracking engine)
│   ├── test_tracing.py             # Unit tests (failure tracing)
│   ├── test_live.py                # Live LLM integration test
│   └── test_tao_live.py            # Live TAO end-to-end test
├── frontend/                      # React + Vite chat demo
│   ├── src/
│   │   ├── api.ts                 # SSE streaming client
│   │   ├── i18n.tsx               # Bilingual (zh/en) i18n
│   │   ├── App.tsx                # Main app + stream state management
│   │   └── components/            # Chat panel, live progress, result card, etc.
│   ├── vite.config.ts             # Vite config (/api proxy)
│   └── package.json
├── docs/
│   ├── API.md / API_zh.md          # Bilingual REST API reference
│   └── SDK.md / SDK_zh.md          # Bilingual Python SDK docs
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── requirements.txt
```

## Quick Start

### Local Development

```bash
# Clone
git clone <repo-url>
cd XTAO

# Install dependencies
pip install -e .

# Configure environment
cp .env.example .env
# Edit .env with your LLM API key

# Run
python -m uvicorn xtao.main:app --host 0.0.0.0 --port 8000
```

### Docker Deployment

```bash
cp .env.example .env
# Edit .env
docker compose up -d
```

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `BASE_URL` | LLM API base URL | `http://localhost:11434/v1` |
| `API_KEY` | LLM API key | (required) |
| `FLASH_LLM_MODEL` | Fast LLM model name | `deepseek-ai/DeepSeek-V4-Flash` |
| `PRO_LLM_MODEL` | Pro LLM model name | `deepseek-ai/DeepSeek-V4-Pro` |
| `RAG_ENABLED` | Enable RAG retrieval | `false` |
| `PROMETHEUS_ENABLED` | Enable Prometheus metrics | `false` |
| `TCC_ENABLED` | Enable TCC Replan mode | `false` |
| `MAX_REPLAN_TOTAL` | Max Replan attempts | `3` |
| `CORS_ORIGINS` | Allowed CORS origins (comma-separated, for Vite dev) | `http://localhost:5173` |
| `FRONTEND_DIST` | Frontend build output dir (skip mounting if absent) | `frontend/dist` |
| `HOST` | Server host | `0.0.0.0` |
| `PORT` | Server port | `8000` |

## API Overview

All routes are prefixed with `/api`. **`POST /api/plan/run` is the primary entry point** — it orchestrates the full G4C lifecycle (generate → verify → execute → correct, including failure tracing, trust state, backtracking, replan, and evaluation). The remaining endpoints expose individual subsystems for granular control. See [docs/API.md](docs/API.md) for full reference.

### Health & Metrics

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/metrics` | Get online monitoring metrics |

### Plan Management

| Method | Path | Description |
|---|---|---|
| **`POST`** | **`/api/plan/run`** | **Main orchestration entry point** (full G4C lifecycle) |
| `POST` | `/api/plan/run/stream` | Main orchestration entry point (SSE streaming output) |
| `POST` | `/api/plan/generate` | Generate G4C Plan (supports iteration mode) |
| `POST` | `/api/plan/verify` | Evaluate Plan quality (G4C 5 dimensions) |
| `POST` | `/api/plan/execute` | Execute Plan step-by-step with checkpoints |
| `POST` | `/api/plan/iterate` | Iterative Plan generation (generate-evaluate-correct loop) |
| `POST` | `/api/plan/trace` | Failure tracing and root cause localization |
| `POST` | `/api/plan/replan` | Trigger Replan (dual judgment, 3 granularities) |
| `POST` | `/api/plan/tcc-replan` | Execute TCC Replan (Try/Confirm/Cancel) |
| `POST` | `/api/dag/validate` | Validate DAG structure (cycle detection + topological sort) |

### Constraint Management

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/constraints/hard` | Add hard constraint (requires user input as evidence) |
| `POST` | `/api/constraints/soft` | Add soft constraint |
| `GET` | `/api/constraints` | Get all constraints |

### Trust State Management

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/trust-state/facts` | Add fact entry (default state: Available) |
| `GET` | `/api/trust-state/facts` | Get all fact entries |
| `POST` | `/api/trust-state/update` | Update trust state (cascade marking on Invalid) |
| `GET` | `/api/trust-state/report` | Get trust state report (per-state counts) |
| `GET` | `/api/trust-state/suspicious` | Get Suspicious and Dirty facts for priority checking |

### Backtracking

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/backtracking/execute` | Execute backtracking (5 levels, auto-determine if omitted) |
| `POST` | `/api/backtracking/progressive` | Progressive expansion backtracking (Action → Step → Stage → Global) |
| `POST` | `/api/backtracking/jump` | Jump backtracking via predefined error-pattern rules |

### Candidate Paths

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/candidate-paths/register` | Register decision node with selected path and candidates |
| `POST` | `/api/candidate-paths/switch/{decision_id}` | Fast switch to next available candidate path |
| `GET` | `/api/candidate-paths/failed` | Get failed path records with recovery status |

### Evaluation

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/evaluation/offline` | Offline Plan analysis (G4C 5 dimensions) |
| `POST` | `/api/evaluation/replan/event` | Record a Replan event |
| `GET` | `/api/evaluation/replan/metrics` | Get Replan effect evaluation (5 metrics) |
| `GET` | `/api/evaluation/replan/report` | Get Replan evaluation report with suggestions |
| `POST` | `/api/evaluation/replan/annotate` | Import manual annotations for events |
| `GET` | `/api/evaluation/replan/test-set` | Export Replan evaluation test set |

TAO evaluation endpoints (`/api/evaluation/tao/event`, `/api/evaluation/tao/metrics`, `/api/evaluation/tao/report`, `/api/evaluation/tao/annotate`, `/api/evaluation/tao/test-set`, `/api/evaluation/tao/judge`) are listed under [TAO (Think-Action-Observation)](#tao-think-action-observation).

### TAO (Think-Action-Observation)

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/tao/run` | Run the full TAO controlled state loop |
| `POST` | `/api/tao/think` | Atomic TAO Think (five structured judgments) |
| `POST` | `/api/tao/act` | Atomic TAO Action execution |
| `POST` | `/api/tao/observe` | Atomic TAO Observation interpretation |
| `POST` | `/api/evaluation/tao/event` | Record a TAO evaluation event |
| `GET` | `/api/evaluation/tao/metrics` | Get TAO evaluation metrics (Think/Action/Observation/Overall) |
| `GET` | `/api/evaluation/tao/report` | Get TAO evaluation report with suggestions |
| `POST` | `/api/evaluation/tao/annotate` | Import golden-answer annotations for TAO |
| `GET` | `/api/evaluation/tao/test-set` | Export TAO evaluation test set |
| `POST` | `/api/evaluation/tao/judge` | Run LLM-as-judge on a single TAO round |

### TAO Action Design

TAO Actions are goal-oriented wrappers, not raw tools. Designing them well improves Think accuracy and loop stability:

- **Business completeness** — an Action is a complete business operation; internally it may call one or more tools or spawn a sub-agent.
- **Orthogonality** — keep responsibility boundaries clear to reduce overlap.
- **Sub-agent encapsulation** — complex subtasks can be encapsulated as sub-agents launched via Actions.
- **Metadata-driven selection** — populate `tags`, `intents`, `applicable_scenarios`, `permissions`, `cost`, `risk`, and `alternatives` to help the engine filter candidates and pick the right action.
- **Execution guards** — the runtime checks candidate-space membership, required params, permissions, and parameter schema before execution.

See [docs/API.md](docs/API.md) for the full filtering pipeline and [docs/SDK.md](docs/SDK.md) for usage examples.

## Frontend Demo

A React + Vite chat demo is included that puts `POST /api/plan/run` to work: type a task in the chat box and watch the streaming output, final status, G4C summary, step trace, and replan/verification metrics in real time.

Highlights:

- **Streaming output** — SSE-based (`POST /api/plan/run/stream`) real-time display of Plan generation and step execution, including LLM reasoning tokens and token-by-token content generation.
- **Markdown rendering** — Step outputs and final results support full Markdown (headings, lists, code blocks, tables, etc.).
- **Bilingual UI** — Toggle between Chinese and English with one click.
- **Timing stats** — Per-phase (generate/verify/execute) and per-step (LLM call/checkpoint) elapsed time displayed inline.
- **G4C visualization** — Expand to inspect Goal, Context, Choice, Checkpoint, and Correction details.
- **Config panel** — Toggle TAO, skip checkpoint, adjust replan count, verification threshold, and more.

### Production mode (FastAPI same-origin)

```bash
# Build frontend assets to frontend/dist/
cd frontend && npm install && npm run build && cd ..

# Start backend (auto-serves frontend/dist/)
python -m uvicorn xtao.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000/` in your browser.

### Development mode (hot reload)

```bash
# Terminal 1: start backend
python -m uvicorn xtao.main:app --port 8000

# Terminal 2: start Vite dev server (proxies /api to :8000)
cd frontend && npm install && npm run dev
```

Open `http://localhost:5173/` — frontend code changes hot-reload instantly.

## Testing

```bash
python -m pytest tests/ -v

# TAO unit tests
python -m pytest tests/test_tao.py -v

# Live TAO end-to-end test (requires API_KEY)
python tests/test_tao_live.py
```

## Python SDK

A type-safe async client ships under `xtao.sdk`. It wraps every REST endpoint and reuses the Pydantic models from `xtao.models` so you can pass model instances directly.

```python
import asyncio
from xtao.sdk import XTAOClient

async def main():
    async with XTAOClient(base_url="http://localhost:8000") as client:
        result = await client.run_plan(user_input="Help me optimize my resume")
        print(result["status"], result["replan_count"])

asyncio.run(main())
```

```python
# Enable TAO loop for step-level execution
from xtao.models import OrchestratorConfig

config = OrchestratorConfig(use_tao=True, tao_max_loops=10)
result = await client.run_plan(user_input="...", config=config)
```

The primary SDK method is `XTAOClient.run_plan()`; additional methods mirror all granular REST endpoints (generate, verify, execute, trace, replan, tcc_replan, constraints, trust state, backtracking, candidate paths, evaluation, metrics, DAG, TAO). Full SDK docs: [docs/SDK.md](docs/SDK.md) (English) / [docs/SDK_zh.md](docs/SDK_zh.md) (中文).

## G4C Methodology

Plan is not a step list, but a **checkable, correctable, executable runtime object**. G4C defines five essential elements of a good Plan:

| Element | Core Question | Uncertainty Resolved |
|---|---|---|
| **Goal** | What to achieve? What is success? | Goal uncertainty |
| **Context** | What is known? What is missing? | Context uncertainty |
| **Choice** | Why this path? What alternatives? | Path uncertainty |
| **Checkpoint** | How to know the step is correct? | Process uncertainty |
| **Correction** | What to do when deviating? | Failure uncertainty |

### Key Design Principles

- **Hard vs. soft constraints** — Hard constraints cannot be violated; soft constraints should be satisfied. Both are injected into the system prompt on every LLM call.
- **Constraints only modified by user input** — The Agent cannot modify constraints autonomously.
- **Evidence-based path selection** — Selection reasons must reference facts or constraints from the context.
- **Checkpoint 3 rules** — Set at milestones, key intermediate outputs, and error-prone steps.
- **5 correction strategies** — Retry, Replan, Clarify, Rollback, Abort.
- **Linear Plan is default** — DAG Plan is an optional advanced mode.

## TAO in a Nutshell

**TAO** stands for **Think - Action - Observation**, the step-level controlled state loop engine in XTAO.

If G4C and Replan solve the problem of "how to generate and correct a macro Plan", TAO solves the problem of "how each individual step of the Plan is executed". Every TAO round performs five structured judgments: goal judgment, state judgment, path judgment, stop judgment, and risk judgment.

![TAO loop diagram](docs/images/tao_loop.png)

In TAO, an Action is not a raw tool call but a goal-oriented operation wrapper. Before execution, candidates pass through a multi-stage filter; after execution, the Observation Interpreter converts raw output into evidence-bound facts. TAO also supports an optional double-layer supervisor loop to detect goal drift, constraint violations, and stagnation.

For more details, see [docs/API.md](docs/API.md) and usage examples in [docs/SDK.md](docs/SDK.md).

## Documentation

- [docs/API.md](docs/API.md) — Full REST API reference (English)
- [docs/API_zh.md](docs/API_zh.md) — Full REST API reference (Chinese)
- [docs/SDK.md](docs/SDK.md) — Python SDK documentation (English)
- [docs/SDK_zh.md](docs/SDK_zh.md) — Python SDK documentation (Chinese)
- [docs/wechat_article_xplan.md](docs/wechat_article_xplan.md) — Project retrospective with in-depth explanations of G4C, Replan, failure tracing, trust state, TCC, and TAO, plus illustrations

Design illustrations are stored in [docs/images/](docs/images/).

## License

MIT
