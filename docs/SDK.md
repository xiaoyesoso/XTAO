# XPlan Python SDK

> A Pythonic, type-safe async client for the XPlan G4C Plan service.

The SDK wraps every REST endpoint exposed by the XPlan FastAPI server and
reuses the Pydantic models from `xplan.models`, so callers can pass model
instances directly without dealing with raw JSON.

- **Async-first**: built on `httpx.AsyncClient`, fits naturally into FastAPI / async codebases.
- **Type-safe**: accepts and returns Pydantic models / typed dicts.
- **Unified errors**: all failures raise subclasses of `XPlanError`.
- **One entry point**: `run_plan()` orchestrates the full G4C lifecycle; granular methods are exposed for advanced control.

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Client Configuration](#client-configuration)
- [Main Entry Point: `run_plan`](#main-entry-point-run_plan)
- [Method Reference](#method-reference)
  - [Plan Operations](#plan-operations)
  - [Constraints](#constraints)
  - [Evaluation](#evaluation)
  - [Metrics & DAG](#metrics--dag)
  - [Trust State](#trust-state)
  - [Backtracking](#backtracking)
  - [Candidate Paths](#candidate-paths)
  - [TAO Loop](#tao-loop)
- [Error Handling](#error-handling)
- [Using Models vs Dicts](#using-models-vs-dicts)
- [Sync Usage](#sync-usage)
- [Recipes](#recipes)

---

## Installation

The SDK ships with the `xplan` package. Install the project in editable mode
from the repository root:

```bash
pip install -e .
```

Dependencies (`httpx`, `pydantic>=2.9`) are pulled in automatically.

## Quick Start

```python
import asyncio
from xplan.sdk import XPlanClient

async def main():
    # Use as an async context manager so the HTTP client is closed automatically.
    async with XPlanClient(base_url="http://localhost:8000") as client:
        # 1. Health check
        print(await client.health_check())

        # 2. Run the full G4C lifecycle (primary entry point)
        result = await client.run_plan(
            user_input="Help me optimize my resume for an Alibaba Java backend role",
        )
        print(result["status"])          # completed / failed / aborted / clarify_needed
        print(result["replan_count"])    # number of replans triggered
        print(result["verification_score"])

asyncio.run(main())
```

## Client Configuration

```python
from xplan.sdk import XPlanClient

client = XPlanClient(
    base_url="http://localhost:8000",  # XPlan server URL
    api_key="optional-bearer-token",   # sent as Authorization: Bearer <key>
    timeout=120.0,                     # request timeout in seconds
)
```

| Parameter  | Type                  | Default                  | Description                                                      |
|------------|-----------------------|--------------------------|------------------------------------------------------------------|
| `base_url` | `str`                 | `http://localhost:8000`  | XPlan server base URL.                                           |
| `api_key`  | `str \| None`         | `None`                   | Optional bearer token.                                           |
| `timeout`  | `float`               | `120.0`                  | Default request timeout (seconds).                               |
| `client`   | `httpx.AsyncClient`   | `None`                   | Optional pre-configured client (caller closes it).               |

The client is an async context manager (`async with XPlanClient(...) as c:`).
If you instantiate it manually, call `await client.close()` when done.

## Main Entry Point: `run_plan`

`run_plan` is the **primary interface**. Internally it orchestrates the full
G4C pipeline:

1. **Generate** the Plan (optionally via the generate-evaluate-correct iteration loop).
2. **Verify** the Plan across the G4C five dimensions (optional, threshold-gated).
3. **Execute** the Plan step by step, running checkpoints at each milestone.
4. On checkpoint failure, orchestrate recovery:
   - **Failure tracing** — locate the root cause (failure point ≠ root cause point).
   - **Trust state** — mark failed results `invalid`, cascade `dirty` downstream.
   - **Backtracking** — progressive expansion (action → step → stage → global).
   - **Replan** — controlled correction via `ReplanEngine` or TCC Replan.
   - **Evaluation** — record the replan event for effectiveness metrics.
5. Return an `OrchestratorResult` containing the final plan, execution trace,
   replan count, and verification score.

```python
from xplan.sdk import XPlanClient
from xplan.models import OrchestratorConfig

config = OrchestratorConfig(
    use_iteration=True,
    max_iterations=3,
    verify_before_execute=True,
    verification_threshold=0.8,
    enable_failure_tracing=True,
    enable_trust_state=True,
    enable_progressive_backtracking=True,
    enable_tcc_replan=False,   # set True only for high-risk scenarios
    max_replan_count=3,
)

result = await client.run_plan(
    user_input="...",
    conversation_history="...",  # optional
    config=config,               # optional, defaults are sensible
)
```

| `OrchestratorConfig` field        | Default | Description                                                |
|-----------------------------------|---------|------------------------------------------------------------|
| `use_iteration`                   | `True`  | Use the generate-evaluate-correct loop.                    |
| `max_iterations`                  | `3`     | Max iterations for the loop.                               |
| `verify_before_execute`           | `True`  | Verify the plan before execution.                          |
| `verification_threshold`          | `0.8`   | Verification score threshold (0–1).                        |
| `enable_failure_tracing`          | `True`  | Enable failure tracing on checkpoint failure.              |
| `enable_trust_state`              | `True`  | Enable trust state management during execution.            |
| `enable_progressive_backtracking` | `True`  | Enable progressive backtracking on failure.                |
| `enable_tcc_replan`               | `False` | Enable TCC Replan for high-risk scenarios.                 |
| `max_replan_count`                | `3`     | Max replan attempts during execution.                      |
| `use_tao`                           | `False` | Execute steps via the TAO controlled state loop.  |
| `tao_max_loops`                     | `10`    | Max TAO inner loop rounds per step.                |
| `tao_max_time`                      | `300.0` | Max TAO execution time per step in seconds.         |
| `tao_supervisor_interval`           | `3`     | TAO outer supervisor loop interval (inner rounds).  |
| `tao_supervisor_interval_seconds`   | `0.0`   | TAO async outer loop interval in seconds.            |

The returned `OrchestratorResult` dict contains:

| Field                 | Type                      | Description                                              |
|-----------------------|---------------------------|----------------------------------------------------------|
| `plan`                | `Plan`                    | Final plan (may differ from the initial one if replanned).|
| `status`              | `str`                     | `completed` / `failed` / `aborted` / `clarify_needed`.   |
| `step_records`        | `list[StepExecutionRecord]` | Per-step execution trace.                              |
| `replan_count`        | `int`                     | Total replan attempts.                                   |
| `iteration_count`     | `int`                     | Plan generation iterations.                              |
| `verification_score`  | `float \| None`           | Plan verification score (0–1).                           |
| `verification_passed` | `bool \| None`            | Whether verification passed the threshold.               |
| `errors`              | `list[str]`               | Errors encountered during execution.                     |
| `clarify_message`     | `str \| None`             | Clarification message when `status == "clarify_needed"`. |

---

## Method Reference

All methods are `async`. Each maps 1:1 to a REST endpoint under `/api`.

### Plan Operations

#### `generate_plan(user_input, conversation_history="", use_iteration=False) -> dict`
`POST /api/plan/generate` — Generate a G4C Plan.

```python
res = await client.generate_plan(
    user_input="Optimize my resume",
    use_iteration=True,
)
plan = res["plan"]
```

When `use_iteration=True`, the response also includes `verification_results`
and `iterations`.

#### `verify_plan(plan) -> dict`
`POST /api/plan/verify` — Evaluate a Plan across the G4C five dimensions.

```python
res = await client.verify_plan(plan)
print(res["verification"])
```

#### `execute_plan(plan) -> dict`
`POST /api/plan/execute` — Execute a Plan step by step with checkpoints.

```python
res = await client.execute_plan(plan)
executed_plan = res["plan"]
print(executed_plan["status"])   # completed / aborted / ...
```

#### `iterate_plan(user_input, conversation_history="") -> dict`
`POST /api/plan/iterate` — Iterative generation via the
generate-evaluate-correct loop. Returns `plan`, `verification_results`,
`iterations`.

#### `trace_failure(plan, failure_step_id, failure_info="", step_records=None) -> dict`
`POST /api/plan/trace` — Trigger failure tracing and root cause location.

Core concept: **failure point ≠ root cause point**. The tracer builds a
reverse tracing chain from the failure point, locates the true root cause,
and suggests a rollback point and a Replan start point.

```python
res = await client.trace_failure(
    plan=plan,
    failure_step_id="step-3",
    failure_info="checkpoint failed: QPS estimate unsupported",
    step_records=[{"step_id": "step-3", "output": {...}}],
)
result = res["result"]
print(result["root_cause_point"])     # the true root cause
print(result["rollback_point"])       # state recovery location
print(result["replan_start_point"])   # where re-planning should start
```

#### `replan(plan, error_info="", user_input="", conversation_history="") -> dict`
`POST /api/plan/replan` — Trigger Replan (controlled correction).

Flow: detect trigger → code judgment → LLM judgment → execute replan.

#### `tcc_replan(plan, conversation_history="") -> dict`
`POST /api/plan/tcc-replan` — Execute TCC Replan (Try / Confirm / Cancel).

Only for high-failure-cost, high-external-dependency, high-side-effect-risk
scenarios. The response `result` contains `try`, `confirm`, `cancel` phases.

### Constraints

Hard constraints cannot be violated; soft constraints should be satisfied.
**Constraint modification requires user input as evidence** — the Agent
cannot modify constraints autonomously.

#### `add_hard_constraint(constraint, user_input) -> dict`
#### `add_soft_constraint(constraint, user_input) -> dict`
#### `get_constraints() -> dict`

```python
await client.add_hard_constraint(
    constraint="Must not fabricate project facts",
    user_input="Please don't make up things I didn't do",
)
await client.add_soft_constraint(constraint="Quantify results where possible", user_input="...")
print(await client.get_constraints())
# {"hard": [...], "soft": [...]}
```

### Evaluation

#### `offline_analysis(plan) -> dict`
`POST /api/evaluation/offline` — Offline Plan analysis around the G4C five dimensions.

#### `record_replan_event(event) -> dict`
`POST /api/evaluation/replan/event` — Record a Replan event for evaluation.
Events with the same `event_id` are updated, not duplicated.

#### `get_replan_metrics() -> dict`
`GET /api/evaluation/replan/metrics` — Replan effectiveness five metrics:
root cause accuracy, Replan start accuracy, result reuse rate, Replan
recovery success rate, Replan oscillation rate.

#### `get_replan_report() -> dict`
`GET /api/evaluation/replan/report` — Textual evaluation report with
improvement suggestions.

#### `annotate_replan(annotations) -> dict`
`POST /api/evaluation/replan/annotate` — Import manual annotations. Each
item must contain `event_id` plus annotation fields such as
`root_cause_correct` / `replan_start_correct`.

#### `export_replan_test_set() -> dict`
`GET /api/evaluation/replan/test-set` — Export the Replan evaluation test
set (key fields of all events, with annotation fields set to `null`).

### Metrics & DAG

#### `get_metrics() -> dict`
`GET /api/metrics` — Online monitoring metrics:
`plan_completion_rate`, `step_success_rate`, `replan_rate`,
`user_correction_rate`, `task_success_rate`, `average_iteration_count`.

#### `validate_dag(dag) -> dict`
`POST /api/dag/validate` — Validate a DAG structure (cycle detection +
topological sort). Returns `valid`, `errors`, `cycles`, `topological_order`.

```python
from xplan.models import DAGPlan, DAGNode, DAGEdge

dag = DAGPlan(nodes=[DAGNode(...)], edges=[DAGEdge(...)])
res = await client.validate_dag(dag)
print(res["valid"], res["cycles"], res["topological_order"])
```

### Trust State

Trust state marks intermediate results so that, on failure, the tracer can
prioritize suspicious/dirty facts and skip verified ones.

| State        | Meaning                                                       |
|--------------|---------------------------------------------------------------|
| `verified`   | Confirmed correct (skip during root cause search).           |
| `available`  | Default; usable but not yet verified.                         |
| `suspicious` | Needs priority checking.                                      |
| `invalid`    | Confirmed wrong — cascade `dirty` to all downstream facts.    |
| `dirty`      | Depends on an invalid fact (transitively tainted).            |

#### `add_fact(key, value, evidence="", source_step_id="", depends_on=None) -> dict`
#### `get_facts() -> dict`
#### `update_trust_state(key, new_state, reason="") -> dict`
Setting `new_state="invalid"` triggers BFS cascade marking; the response
includes all change records.

#### `get_trust_state_report() -> dict`
#### `get_suspicious_and_dirty() -> dict`

```python
await client.add_fact(
    key="highest_qps",
    value=12000,
    evidence="user interview 2026-07-26",
    source_step_id="step-1",
    depends_on=["cluster_size"],
)
# Later, mark it invalid — downstream facts become dirty automatically
changes = await client.update_trust_state("highest_qps", "invalid", reason="user retracted")
print(changes["changes"])
```

### Backtracking

Five backtracking levels, from smallest to largest scope:
`action` → `step` → `stage` → `global` → `cross_turn`.

#### `execute_backtracking(plan, error_info="", level=None, failure_tracing_result=None, step_id="", decision_id="", stage_checkpoint_id="", contamination=None) -> dict`
`POST /api/backtracking/execute` — Execute backtracking at a given level.
When `level=None` the server auto-determines it. `cross_turn` requires
`contamination`.

#### `progressive_backtracking(plan, error_info="", failure_tracing_result=None) -> dict`
`POST /api/backtracking/progressive` — Progressive expansion
(action → step → stage → global). Each expansion validates the new plan via
TCC before proceeding.

#### `jump_backtracking(error_pattern, jump_rules=None) -> dict`
`POST /api/backtracking/jump` — Jump backtracking via predefined rules.
Skips progressive expansion by directly locating the backtracking position.
Response includes `matched: bool`.

### Candidate Paths

Decision nodes retain candidate paths so that, on failure, switching paths
is fast — no need to regenerate the Plan.

#### `register_decision(decision_id, selected, candidates=None) -> dict`
#### `switch_candidate_path(decision_id) -> dict`
#### `get_failed_paths() -> dict`

```python
from xplan.models import CandidatePath

await client.register_decision(
    decision_id="extract-facts",
    selected="llm-extract",
    candidates=[
        CandidatePath(path="llm-extract"),
        CandidatePath(path="regex-extract"),
        CandidatePath(path="user-form"),
    ],
)
# When llm-extract fails, switch to the next available candidate
new_path = await client.switch_candidate_path("extract-facts")
print(new_path["new_path"])   # regex-extract
```

### TAO Loop

TAO (Think-Action-Observation) is a controlled state loop for step-level
execution. The Plan defines the macro path, while TAO decides how each
concrete step moves forward and interprets feedback.

#### `run_tao(user_input, plan=None, candidate_actions=None, max_loops=10, max_time=300.0) -> dict`
`POST /api/tao/run` - Run the full TAO controlled state loop.

```python
from xplan.models import ActionCandidate, ActionType

result = await client.run_tao(
    user_input="Optimize my resume project experience",
    candidate_actions=[
        ActionCandidate(name="read_resume", type=ActionType.TOOL_CALL, description="Read resume"),
        ActionCandidate(name="write_resume", type=ActionType.TOOL_CALL, description="Write optimized resume"),
    ],
    max_loops=6,
)
print(result["exit_type"])    # finish / clarify / replan / interrupt
print(result["used_loops"])
print(result["final_output"])
```

#### `tao_think(state) -> dict`
`POST /api/tao/think` - Atomic TAO Think round.

Runs one Think round on the given state, producing a structured ThinkResult
(five judgments: goal, state, path, stop, risk) plus the loop controller's
exit decision. The caller carries the TAOState between calls.

#### `tao_act(state, action_name, params=None) -> dict`
`POST /api/tao/act` - Atomic TAO Action execution.

Executes the named action from the candidate space. Illegal actions and
unsatisfied preconditions are rejected with a 400 error.

#### `tao_observe(state, record, expectation="") -> dict`
`POST /api/tao/observe` - Atomic TAO Observation interpretation.

Interprets an action's raw output into a structured Observation with
evidence-bound fact extraction.

#### `record_tao_evaluation_event(event) -> dict`
`POST /api/evaluation/tao/event` - Record a TAO evaluation event.

#### `get_tao_metrics() -> dict`
`GET /api/evaluation/tao/metrics` - Get aggregated TAO evaluation metrics
(Think/Action/Observation/Overall).

#### `get_tao_report() -> dict`
`GET /api/evaluation/tao/report` - Get TAO evaluation report with
metrics, abnormal samples and suggestions.

#### `annotate_tao(annotations) -> dict`
`POST /api/evaluation/tao/annotate` - Import human golden-answer annotations.

#### `export_tao_test_set() -> dict`
`GET /api/evaluation/tao/test-set` - Export TAO evaluation test set.

#### `tao_llm_judge(request) -> dict`
`POST /api/evaluation/tao/judge` - Run LLM-as-judge on a single TAO round.

### TAO via `run_plan`

TAO can also be enabled per-step within the main orchestration:

```python
from xplan.models import OrchestratorConfig

config = OrchestratorConfig(
    use_tao=True,
    tao_max_loops=10,
    tao_max_time=300.0,
    tao_supervisor_interval=3,
)
result = await client.run_plan(user_input="...", config=config)
# step_records will show tao_used=True, tao_loops, tao_exit per step
```

---

## Error Handling

All SDK failures raise subclasses of `XPlanError`. Catch the base class to
handle any SDK error, or catch specific subclasses for finer control.

| Exception        | When raised                                              |
|------------------|----------------------------------------------------------|
| `XPlanError`     | Base class for all SDK errors.                           |
| `ConnectionError`| Cannot reach the XPlan server.                           |
| `TimeoutError`   | Request timed out.                                       |
| `APIError`       | Server returned a non-2xx status. Exposes `status_code` and `detail`. |
| `ValidationError`| Response cannot be parsed into the requested model.      |

```python
from xplan.sdk import XPlanClient, APIError, ConnectionError, XPlanError

try:
    result = await client.run_plan(user_input="...")
except ConnectionError:
    # server unreachable
    raise
except APIError as exc:
    if exc.status_code == 400:
        print("Bad request:", exc.detail)
    elif exc.status_code >= 500:
        print("Server error:", exc.detail)
    raise
except XPlanError:
    # catch-all for any other SDK error
    raise
```

> Note: `xplan.sdk.ConnectionError` / `xplan.sdk.TimeoutError` shadow the
> Python builtins of the same name. Import them with an alias if you need
> both in the same module.

## Using Models vs Dicts

The SDK accepts either Pydantic model instances or plain dicts — whichever
is more convenient. Internally, models are serialized via
`model_dump(mode="json")`, so enums and datetimes are handled correctly.

```python
# Using models (recommended for IDE support and validation)
from xplan.models import Plan, Goal, Context, Choice, Step

plan = Plan(
    goal=Goal(user_goal="...", success_criteria=[...]),
    context=Context(known_facts=[...]),
    choice=Choice(selected_path="...", reason="...", steps=[Step(...)]),
)
await client.verify_plan(plan)

# Using dicts (handy for quick scripts)
await client.verify_plan({
    "goal": {"user_goal": "...", "success_criteria": [...]},
    "context": {"known_facts": [...]},
    "choice": {"selected_path": "...", "reason": "...", "steps": [...]},
})
```

Responses are returned as parsed JSON dicts. To validate a response into a
model, use Pydantic directly:

```python
from xplan.models import OrchestratorResult

res = await client.run_plan(user_input="...")
result = OrchestratorResult.model_validate(res)
print(result.plan.goal.user_goal)
```

## Sync Usage

The SDK is async-first, but you can drive it from synchronous code with
`asyncio.run`:

```python
import asyncio
from xplan.sdk import XPlanClient

def run(user_input: str) -> dict:
    async def _run():
        async with XPlanClient() as client:
            return await client.run_plan(user_input=user_input)
    return asyncio.run(_run())

print(run("Help me optimize my resume"))
```

For long-running sync applications, prefer keeping a single event loop and
reusing the client rather than recreating it per call.

## Recipes

### Full lifecycle with custom config

```python
from xplan.sdk import XPlanClient
from xplan.models import OrchestratorConfig

async def full_lifecycle(client: XPlanClient, goal: str) -> dict:
    config = OrchestratorConfig(
        use_iteration=True,
        max_iterations=3,
        verify_before_execute=True,
        verification_threshold=0.85,
        enable_failure_tracing=True,
        enable_progressive_backtracking=True,
        max_replan_count=2,
    )
    return await client.run_plan(user_input=goal, config=config)
```

### Manual control: generate → verify → execute

Use this when you want to inspect or mutate the plan between stages.

```python
async def manual_control(client: XPlanClient, goal: str):
    gen = await client.generate_plan(user_input=goal, use_iteration=True)
    plan = gen["plan"]

    verification = await client.verify_plan(plan)
    if not verification["verification"]["passed"]:
        # iterate or fix the plan
        ...

    executed = await client.execute_plan(plan)
    return executed["plan"]
```

### Failure recovery loop

```python
async def recover(client: XPlanClient, plan: dict, failed_step: str, error: str):
    # 1. Trace the root cause (failure point != root cause point)
    trace = await client.trace_failure(plan, failed_step, error)
    root = trace["result"]["root_cause_point"]

    # 2. Mark the failed fact invalid — downstream facts become dirty
    if root and root.get("step_id"):
        await client.update_trust_state(root["step_id"], "invalid", reason=error)

    # 3. Progressive backtracking (action -> step -> stage -> global)
    bt = await client.progressive_backtracking(
        plan, error_info=error, failure_tracing_result=trace["result"]
    )
    return bt["result"]
```

### Evaluate Replan effectiveness

```python
async def evaluate(client: XPlanClient):
    # After collecting replan events via record_replan_event(...)...
    metrics = await client.get_replan_metrics()
    print("Root cause accuracy:", metrics["root_cause_accuracy"])
    print("Replan start accuracy:", metrics["replan_start_accuracy"])
    print("Result reuse rate:", metrics["result_reuse_rate"])
    print("Replan recovery success rate:", metrics["replan_recovery_success_rate"])
    print("Replan oscillation rate:", metrics["replan_oscillation_rate"])

    # Export test set for manual annotation
    test_set = await client.export_replan_test_set()
    # ... annotate offline, then import back ...
    await client.annotate_replan(annotations=[
        {"event_id": "evt-1", "root_cause_correct": True, "replan_start_correct": False},
    ])
```

---

## See Also

- [README.md](../README.md) — Project overview and deployment.
- [API.md](API.md) — Raw REST API reference.
- Source: [`src/xplan/sdk/`](../src/xplan/sdk)
