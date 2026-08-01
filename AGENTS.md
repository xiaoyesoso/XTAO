# AGENTS.md

This file provides project context and working guidelines for AI agents.

## Project Overview

XTAO is an Agent Plan mechanism built on the **G4C methodology** (Goal, Context, Choice, Checkpoint, Correction). The core objective is to elevate Plan from a "step list" to a "checkable, correctable, executable runtime object," systematically eliminating five types of uncertainty during Agent execution: goal uncertainty, context uncertainty, path uncertainty, process uncertainty, and failure uncertainty.

The project also implements a **Replan mechanism** (trigger detection, code+LLM dual judgment, three granularity levels, evidence-based prompt design), an optional **TCC Replan** advanced scheme (Try/Confirm/Cancel), and a **TAO (Think-Action-Observation) / ReAct execution engine** with Action design guidelines, multi-dimensional candidate filtering, loop safety, and high-availability wrappers.

## Project Structure

```
XTAO/
├── AGENTS.md                              # This file - AI Agent guidelines
├── README.md                              # English README
├── README_zh.md                           # Chinese README
├── .gitignore                             # Git ignore rules
├── .env.example                           # Environment variable template
├── .env                                   # Environment variables (not in git)
├── Dockerfile                             # Docker image definition
├── docker-compose.yml                     # Docker Compose deployment
├── pyproject.toml                         # Python project config (setuptools)
├── requirements.txt                       # Python dependencies
├── docs/                                  # Documentation
│   ├── API.md                             # REST API reference (English)
│   ├── API_zh.md                          # REST API reference (Chinese)
│   ├── SDK.md                             # Python SDK docs (English)
│   └── SDK_zh.md                          # Python SDK docs (Chinese)
├── src/
│   └── xtao/
│       ├── __init__.py                    # Package init
│       ├── main.py                        # FastAPI app entry point
│       ├── api/
│       │   ├── __init__.py
│       │   └── routes.py                  # REST API routes (incl. main /api/plan/run entry)
│       ├── models/                        # G4C data models (Pydantic)
│       │   ├── __init__.py
│       │   ├── plan.py                    # Plan composite object (G4C + PlanMode/PlanStatus)
│       │   ├── goal.py                    # Goal (user_goal + success_criteria + adjective_standards)
│       │   ├── context.py                 # Context (known_facts + missing_info + Constraints hard/soft)
│       │   ├── choice.py                  # Choice (selected_path + reason + Steps with reason)
│       │   ├── checkpoint.py              # Checkpoint, CheckResult, CheckEvidence
│       │   ├── correction.py              # Correction, CorrectionAction (5 correction types)
│       │   ├── dag.py                     # DAGNode, DAGEdge, DAGPlan
│       │   ├── replan.py                  # ReplanTrigger, ReplanGranularity, ReplanInfo, ReplanJudgment, ReplanResult
│       │   ├── replan_evaluation.py       # ReplanEvent, ReplanMetrics, OscillationDetector
│       │   ├── tcc.py                     # TCCPhase, TryValidation, TryResult, ConfirmResult, CancelResult
│       │   ├── backtracking.py            # BacktrackingLevel, CandidatePath, JumpRule, CrossTurnContamination
│       │   ├── trust_state.py             # FactEntry, TrustState, TrustStateReport
│       │   ├── tracing.py                 # TracingPoint / FailureTracingResult / StepRecord
│       │   ├── tao.py                     # TAO models: TAOState, ThinkResult, ActionCandidate, ActionAvailability, ActionFilterRule
│       │   └── orchestrator.py            # OrchestratorConfig / OrchestratorResult / StepExecutionRecord
│       ├── prompts/                       # Prompt modules (one per G4C element)
│       │   ├── __init__.py
│       │   ├── goal_prompt.py             # Goal prompt (structured output + adjective standards + RAG)
│       │   ├── context_prompt.py          # Context prompt (constraint injection)
│       │   ├── choice_prompt.py           # Choice prompt (evidence-based path selection)
│       │   ├── checkpoint_prompt.py       # Checkpoint prompt (3 rules + 1/3 granularity)
│       │   ├── correction_prompt.py       # Correction prompt (5 strategies + scenarios)
│       │   ├── dag_prompt.py              # DAG prompt (dependency rules + few-shot)
│       │   ├── replan_prompt.py           # Replan prompt (G4C context + constraints + evidence-based)
│       │   ├── tcc_prompt.py              # TCC prompt (Try/Confirm/Cancel 3-phase)
│       │   ├── tracing_prompt.py          # Failure tracing prompt
│       │   ├── tao_prompt.py              # TAO Think prompt (evidence-based action selection + loop safety)
│       │   ├── aggregator.py              # Aggregates all 5 module prompts
│       │   └── constants.py               # Shared constants
│       ├── services/                      # Service layer
│       │   ├── __init__.py
│       │   ├── llm_service.py             # LLMService (httpx async, OpenAI-compatible, retry incl. SSL errors)
│       │   ├── rag_service.py             # RAGService (knowledge base retrieval)
│       │   ├── constraint_manager.py      # ConstraintManager (hard/soft, user-evidence required)
│       │   ├── trust_state_manager.py     # TrustStateManager (5 states + cascade marking)
│       │   └── candidate_path_manager.py  # CandidatePathManager (decision nodes, fast switch)
│       ├── engine/                        # Core engine
│       │   ├── __init__.py
│       │   ├── plan_generator.py          # PlanGenerator (7-step G4C generation)
│       │   ├── plan_verifier.py           # PlanVerifier (G4C 5-dimension scoring)
│       │   ├── plan_executor.py           # PlanExecutor (step-by-step + checkpoint + correction)
│       │   ├── correction_handler.py      # CorrectionHandler (5 strategies: retry/replan/clarify/rollback/abort)
│       │   ├── dag_validator.py           # DAGValidator (cycle detection, topological sort)
│       │   ├── iteration_loop.py          # IterationLoop (generate-evaluate-correct loop)
│       │   ├── replan_engine.py           # ReplanEngine (trigger detection, dual judgment, 3 granularities)
│       │   ├── tcc_replan.py              # TCCReplan (Try/Confirm/Cancel, dry-run, alternative check)
│       │   ├── backtracking_engine.py     # BacktrackingEngine (5 levels + progressive expansion)
│       │   ├── cross_turn_tracker.py      # CrossTurnTracker (cross-turn contamination tracking)
│       │   ├── failure_tracer.py          # FailureTracer (failure backtracking + root cause localization)
│       │   ├── orchestrator.py            # PlanOrchestrator (main entrypoint engine)
│       │   ├── tao_engine.py              # TAOEngine (Think-Action-Observation controlled state loop)
│       │   ├── tao_think_engine.py        # TAOThinkEngine (five structured judgments)
│       │   ├── tao_action_runtime.py      # TAOActionRuntime (candidate filtering, execution guards, HA wrappers)
│       │   ├── tao_observation_interpreter.py # Observation interpreter (evidence-bound fact extraction)
│       │   ├── tao_loop_controller.py     # TAOLoopController (loop exit + dead-loop/stagnation detection)
│       │   ├── tao_massive_action_filter.py # MassiveActionFilter (multi-stage candidate filtering)
│       │   └── tao_state_manager.py       # TAOStateManager (runtime state persistence)
│       ├── sdk/                           # Python SDK (client for the REST API)
│       │   ├── __init__.py                # Public exports: XTAOClient + exceptions
│       │   ├── client.py                  # XTAOClient (async, httpx-based, all endpoints)
│       │   └── exceptions.py              # XTAOError / APIError / ConnectionError / TimeoutError / ValidationError
│       └── evaluation/                    # Quality evaluation
│           ├── __init__.py
│           ├── metrics.py                 # PlanMetrics (Prometheus counters/gauges/histograms)
│           ├── offline_analyzer.py        # OfflineAnalyzer (G4C 5-dimension offline analysis)
│           ├── replan_evaluator.py        # ReplanEvaluator (5 metrics: root cause / replan start / reuse / recovery / oscillation)
│           ├── user_correction_detector.py # UserCorrectionDetector (keyword + LLM detection)
│           └── tao_evaluator.py           # TAOEvaluator (Think/Action/Observation/Overall metrics)
├── tests/
│   ├── __init__.py
│   ├── test_plan.py                       # Unit tests (G4C core)
│   ├── test_tao.py                        # Unit tests (TAO models, engine, filtering, loop safety)
│   ├── test_backtracking.py               # Unit tests (backtracking engine)
│   ├── test_tracing.py                    # Unit tests (failure tracing)
│   ├── test_live.py                       # Live LLM integration test
│   └── test_tao_live.py                   # Live TAO end-to-end test
├── .trae/                                 # OpenSpec Trae skills (not in git)
├── openspec/                              # OpenSpec specs and changes (not in git)
└── 规划执行/                               # Original requirement documents (not in git)
```

## OpenSpec Workflow

This project uses [OpenSpec](https://github.com/Fission-AI/OpenSpec) for spec-driven development with the `spec-driven` schema.

### Workflow Stages

```
proposal -> specs -> design -> tasks -> implement -> archive
```

1. **Propose**: Create a change proposal (`openspec new change <name>`)
2. **Specs**: Write spec files per capability (with SHALL/MUST requirements and Scenarios)
3. **Design**: Write technical design document (decisions, risks, migration plan)
4. **Tasks**: Break down into implementation task checklist
5. **Apply**: Implement code following the task checklist
6. **Archive**: Archive completed change and sync to main specs

### Common Commands

```bash
# View change status
openspec status --change <name>

# Get artifact creation instructions
openspec instructions <artifact> --change <name>

# Validate change integrity
openspec validate <name>

# List all changes
openspec list

# Archive completed change
openspec archive <name>
```

### Trae Skills (Slash Commands)

- `/opsx:propose` - Propose a new change and generate all artifacts
- `/opsx:apply` - Implement tasks from a change
- `/opsx:archive` - Archive a completed change
- `/opsx:explore` - Explore mode (thinking partner)

## G4C Methodology

Plan is not a step list, but a **checkable, correctable, executable runtime object**. G4C defines 5 essential elements of a good Plan:

| Element | Core Question | Uncertainty Resolved |
|---|---|---|
| **Goal** | What to achieve? What is success? | Goal uncertainty |
| **Context** | What is known? What is missing? | Context uncertainty |
| **Choice** | Why this path? What alternatives? | Path uncertainty |
| **Checkpoint** | How to know the step is correct? | Process uncertainty |
| **Correction** | What to do when deviating? | Failure uncertainty |

### Key Design Principles

- **Hard vs soft constraints**: Hard constraints cannot be violated; soft constraints should be satisfied. Both are injected into the system prompt on every LLM call.
- **Constraints only modified by user input**: Agent cannot modify constraints autonomously.
- **Evidence-based path selection**: Selection reasons must reference facts or constraints from the context.
- **Checkpoint 3 rules**: Set at milestones, key intermediate outputs, and error-prone steps.
- **5 correction strategies**: Retry, Replan, Clarify, Rollback, Abort.
- **Linear Plan is default**: DAG Plan is an optional advanced mode.

## Replan Mechanism

Replan is the core implementation of Correction, defined as "controlled modification of the original plan during execution, based on new Goal, Context, Choice, and Checkpoint results."

### Key Concepts

- **Trigger conditions**: Tool failure (non-transient), context change (user adds constraints/info), assumption violation (checkpoint detects invalid assumption)
- **Dual judgment**: Code judgment first (filters transient errors like timeouts), then LLM judgment for uncertain cases
- **Judgment-execution separation**: Two independent LLM calls — never mix judgment and execution in one call
- **3 granularity levels**: Step Replan (from current step), Partial Replan (rollback to a specific step), Global Replan (from scratch)
- **Minimize scope**: Prefer smallest granularity, reuse existing results
- **Replan control info**: `replan_info` with `max_replan_total` and `used_replan_total`
- **Evidence-based**: All Replan decisions must be based on evidence; no evidence = no claim of Goal/Context/constraint changes
- **Categorized output**: `retained_steps` / `modified_steps` / `removed_steps` with reasons

## TCC Replan (Optional Advanced)

Borrowed from distributed transaction TCC, applicable only to high-failure-cost, high-external-dependency, high-side-effect-risk scenarios.

| Phase | Responsibility | Key Constraint |
|---|---|---|
| **Try** | Find and minimally validate the weakest point of the new Plan | Low cost, no/low side effects, use dry-run |
| **Confirm** | Execute Plan + write Try results to context | Reuse Try data where possible |
| **Cancel** | Rollback Try temp state + mark failed assumptions + decide Replan or abort | Try data in temp space, not in Context |

## TAO / ReAct Execution Engine

TAO (Think-Action-Observation) is a step-level controlled state loop. The Plan defines the macro path; TAO decides how each concrete step moves forward and interprets feedback.

### Key Concepts

- **Five runtime states**: Goal State, Action State, Observation State, Fact State, Control State.
- **Five Think judgments**: goal, state, path, stop, risk.
- **Action design**: Actions are goal-oriented wrappers, not raw tools. Design principles include business completeness, orthogonality, sub-agent encapsulation, and minimal params/returns.
- **Action metadata**: `ActionCandidate` carries `tags`, `intents`, `applicable_scenarios`, `inapplicable_scenarios`, `permissions`, `cost`, `risk`, `reversible`, `repeatable_on_retry`, and `alternatives` to support filtering and evidence-based selection.
- **Multi-dimensional filtering**: intent/tag filter → rule engine (`ActionFilterRule`) → preconditions/permissions → historical success rate (`ActionAvailability`) → information gain → LLM coarse filter (Fast LLM) → LLM fine filter (Pro LLM).
- **Execution guards**: candidate-space check, required params check, permission check, params-schema check.
- **High availability**: retry, fallback to alternatives, circuit breaker, rate limiting.
- **Loop safety**: max loops / max time, dead-loop detection, stagnation detection, exclude already-failed actions unless `repeatable_on_retry`.
- **TAO evaluation**: Think/Action/Observation/Overall four-layer metrics with LLM-as-judge and golden-answer comparison.

## API Endpoints

All routes are prefixed with `/api`. `POST /api/plan/run` is the **primary entry point** that internally orchestrates the full G4C lifecycle (generate → verify → execute → correct, including failure tracing, trust state, backtracking, replan, and evaluation). The remaining endpoints expose the individual subsystems for granular control.

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Health check |
| **POST** | **`/api/plan/run`** | **Main orchestration entry point** (full G4C lifecycle) |
| POST | `/api/plan/generate` | Generate G4C Plan (supports iteration mode) |
| POST | `/api/plan/verify` | Evaluate Plan quality (G4C 5 dimensions) |
| POST | `/api/plan/execute` | Execute Plan (step-by-step with checkpoints) |
| POST | `/api/plan/iterate` | Iterative Plan generation (generate-evaluate-correct loop) |
| POST | `/api/plan/trace` | Failure tracing and root cause localization (failure point ≠ root cause point) |
| POST | `/api/plan/replan` | Trigger Replan (with dual judgment and 3 granularities) |
| POST | `/api/plan/tcc-replan` | Execute TCC Replan (Try/Confirm/Cancel) |
| POST | `/api/constraints/hard` | Add hard constraint (requires user input as evidence) |
| POST | `/api/constraints/soft` | Add soft constraint |
| GET | `/api/constraints` | Get all constraints |
| POST | `/api/trust-state/facts` | Add fact entry (default state `AVAILABLE`) |
| GET | `/api/trust-state/facts` | Get all fact entries |
| POST | `/api/trust-state/update` | Update trust state (`INVALID` triggers cascade `DIRTY` marking) |
| GET | `/api/trust-state/report` | Get trust state report (per-state counts) |
| GET | `/api/trust-state/suspicious` | Get Suspicious/Dirty facts to check first |
| POST | `/api/backtracking/execute` | Execute backtracking (5 levels, auto-determine if omitted) |
| POST | `/api/backtracking/progressive` | Progressive expansion backtracking (action → step → stage → global) |
| POST | `/api/backtracking/jump` | Jump backtracking via predefined error-pattern rules |
| POST | `/api/candidate-paths/register` | Register decision node with selected path and candidates |
| POST | `/api/candidate-paths/switch/{id}` | Fast switch to next available candidate path |
| GET | `/api/candidate-paths/failed` | Get failed path records with recovery status |
| POST | `/api/evaluation/offline` | Offline Plan analysis (G4C 5 dimensions) |
| POST | `/api/evaluation/replan/event` | Record a Replan event for evaluation |
| GET | `/api/evaluation/replan/metrics` | Get Replan effect evaluation (5 metrics) |
| GET | `/api/evaluation/replan/report` | Get Replan evaluation report with suggestions |
| POST | `/api/evaluation/replan/annotate` | Import manual annotations for events |
| GET | `/api/evaluation/replan/test-set` | Export Replan evaluation test set |
| GET | `/api/metrics` | Get online monitoring metrics |
| POST | `/api/dag/validate` | Validate DAG structure (cycle detection + topological sort) |
| POST | `/api/tao/run` | Run the full TAO (Think-Action-Observation) controlled state loop |
| POST | `/api/tao/think` | Atomic TAO Think (five structured judgments + exit decision) |
| POST | `/api/tao/act` | Atomic TAO Action execution (candidate space enforced) |
| POST | `/api/tao/observe` | Atomic TAO Observation interpretation (evidence-bound facts) |
| POST | `/api/evaluation/tao/event` | Record a TAO evaluation event |
| GET | `/api/evaluation/tao/metrics` | Get TAO evaluation metrics (Think/Action/Observation/Overall) |
| GET | `/api/evaluation/tao/report` | Get TAO evaluation report with suggestions |
| POST | `/api/evaluation/tao/annotate` | Import golden-answer annotations for TAO |
| GET | `/api/evaluation/tao/test-set` | Export TAO evaluation test set |
| POST | `/api/evaluation/tao/judge` | Run LLM-as-judge on a single TAO round |

## Python SDK

A type-safe async client lives under [src/xtao/sdk/](src/xtao/sdk). It wraps every REST endpoint and reuses the Pydantic models from `xtao.models`, so callers can pass model instances directly without dealing with raw JSON.

```python
import asyncio
from xtao.sdk import XTAOClient
from xtao.models import OrchestratorConfig

async def main():
    async with XTAOClient(base_url="http://localhost:8000") as client:
        result = await client.run_plan(
            user_input="Help me optimize my resume",
            config=OrchestratorConfig(max_replan_count=2),
        )
        print(result["status"], result["replan_count"])

asyncio.run(main())
```

SDK docs: [docs/SDK.md](docs/SDK.md) (English) / [docs/SDK_zh.md](docs/SDK_zh.md) (Chinese). The single primary SDK method is `XTAOClient.run_plan()`; the other 30 methods mirror the granular REST endpoints.

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `BASE_URL` | LLM API base URL (SiliconFlow) | `http://localhost:11434/v1` |
| `API_KEY` | LLM API key | (required) |
| `FLASH_LLM_MODEL` | Fast LLM model name | `deepseek-ai/DeepSeek-V4-Flash` |
| `PRO_LLM_MODEL` | Pro LLM model name | `deepseek-ai/DeepSeek-V4-Pro` |
| `RAG_ENABLED` | Enable RAG retrieval | `false` |
| `PROMETHEUS_ENABLED` | Enable Prometheus metrics | `false` |
| `TCC_ENABLED` | Enable TCC Replan mode | `false` |
| `MAX_REPLAN_TOTAL` | Max Replan attempts | `3` |
| `HOST` | Server host | `0.0.0.0` |
| `PORT` | Server port | `8000` |

## Coding Conventions

- **Language**: English for comments, docstrings, and documentation; English for code identifiers (kebab-case for files, snake_case for Python). User-facing docs (README, API, SDK) are provided in both English and Chinese.
- **Specs**: Use SHALL/MUST for normative requirements; every Requirement must have at least one `#### Scenario:` block
- **Tasks**: Use `- [ ] X.Y Task description` checkbox format for progress tracking
- **Commits**: Follow Conventional Commits
- **Models**: Use Pydantic v2 for all data models
- **Async**: Use async/await throughout; LLM calls use `llm_service.chat(system_prompt, user_prompt)`
- **SDK**: The SDK (`xtao.sdk`) is async-only, reuses `xtao.models` for request/response payloads, and raises `XTAOError` subclasses on failure. All failures must surface as typed exceptions — never swallow errors silently.
- **Testing**: Run `python -m pytest tests/test_plan.py tests/test_tao.py tests/test_backtracking.py tests/test_tracing.py -v` to verify (64+ tests, all passing)

## Docker Deployment

```bash
# Copy env template and fill in values
cp .env.example .env

# Build and start
docker compose up -d

# Or build manually
docker build -t xtao .
docker run -p 8000:8000 --env-file .env xtao
```

## Current Status

- Change `agent-plan-g4c`: **all tasks complete** (proposal → specs → design → tasks → implement)
- Change `agent-plan-tao-action-selection`: **all tasks complete** (proposal → specs → design → tasks → implement)
- Core engine fully implemented: G4C generation, verification, execution, correction, Replan, TCC Replan, failure tracing, trust state, backtracking (5 levels), candidate paths, cross-turn tracking, TAO/ReAct execution engine, and the `PlanOrchestrator` main entry point
- Python SDK shipped (`xtao.sdk.XTAOClient`) with full live-server end-to-end verification
- Docs: bilingual README (`README.md` / `README_zh.md`), bilingual API reference (`docs/API.md` / `docs/API_zh.md`), bilingual SDK docs (`docs/SDK.md` / `docs/SDK_zh.md`)
- 64 unit tests passing (`tests/test_plan.py` + `tests/test_tao.py`)
- Live LLM integration tested with SiliconFlow DeepSeek
