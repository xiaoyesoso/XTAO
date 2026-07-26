# XPlan

> Agent Plan mechanism based on the **G4C methodology** (Goal, Context, Choice, Checkpoint, Correction).

XPlan elevates a Plan from a "step list" to a **checkable, correctable, executable runtime object**, systematically eliminating five types of uncertainty during Agent execution: goal uncertainty, context uncertainty, path uncertainty, process uncertainty, and failure uncertainty.

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
- **Replan Effect Evaluation** — Five metrics: root cause accuracy, replan start accuracy, result reuse rate, replan recovery success rate, replan oscillation rate.

## Tech Stack

- **Python 3.11+**
- **FastAPI** — async REST API
- **Pydantic v2** — data models
- **httpx** — async LLM calls (OpenAI-compatible)
- **OpenAI-compatible LLM API** — tested with SiliconFlow DeepSeek

## Project Structure

```
XPlan/
├── src/xplan/
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
│   │   └── orchestrator.py         # OrchestratorConfig / OrchestratorResult
│   ├── prompts/                    # Prompt modules (one per G4C element)
│   ├── services/                   # LLMService, RAGService, ConstraintManager,
│   │                               # TrustStateManager, CandidatePathManager
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
│   │   └── orchestrator.py         # PlanOrchestrator (main entrypoint engine)
│   ├── sdk/                        # Python SDK — async client for the REST API
│   │   ├── client.py               # XPlanClient (all 31 endpoints)
│   │   └── exceptions.py           # XPlanError / APIError / ConnectionError / ...
│   └── evaluation/                 # Metrics, offline analyzer, ReplanEvaluator
├── tests/
│   ├── test_plan.py                # Unit tests
│   └── test_live.py                # Live LLM integration test
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
cd XPlan

# Install dependencies
pip install -e .

# Configure environment
cp .env.example .env
# Edit .env with your LLM API key

# Run
python -m uvicorn xplan.main:app --host 0.0.0.0 --port 8000
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

## Testing

```bash
python -m pytest tests/ -v
```

## Python SDK

A type-safe async client ships under `xplan.sdk`. It wraps every REST endpoint and reuses the Pydantic models from `xplan.models` so you can pass model instances directly.

```python
import asyncio
from xplan.sdk import XPlanClient

async def main():
    async with XPlanClient(base_url="http://localhost:8000") as client:
        result = await client.run_plan(user_input="Help me optimize my resume")
        print(result["status"], result["replan_count"])

asyncio.run(main())
```

The primary SDK method is `XPlanClient.run_plan()`; 30 additional methods mirror the granular REST endpoints (generate, verify, execute, trace, replan, tcc_replan, constraints, trust state, backtracking, candidate paths, evaluation, metrics, DAG). Full SDK docs: [docs/SDK.md](docs/SDK.md) (English) / [docs/SDK_zh.md](docs/SDK_zh.md) (中文).

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

## License

MIT
