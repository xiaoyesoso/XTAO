# XTAO API Reference

## 1. Introduction

XTAO is an Agent Plan mechanism built on the **G4C methodology** (Goal, Context, Choice, Checkpoint, Correction). This document describes the REST API exposed by the XTAO FastAPI backend service.

### Base URL

```
http://localhost:8000/api
```

### Conventions

- All endpoints are served under the `/api` prefix.
- Request and response bodies use `Content-Type: application/json`.
- All responses are JSON-encoded.
- Date/time fields are strings (ISO 8601 where applicable).
- Enum values are lowercase string literals (e.g. `"linear"`, `"step"`, `"verified"`).

### Authentication

The API does not require authentication by default. Configure the underlying LLM service via environment variables (`BASE_URL`, `API_KEY`, `FLASH_LLM_MODEL`, `PRO_LLM_MODEL`).

### Primary Entry Point

`POST /api/plan/run` is the **main orchestration entry point**. It runs the full G4C lifecycle internally — generate → verify → execute → correct — and, on checkpoint failure, orchestrates failure tracing, trust state, backtracking, replan, and evaluation. The other endpoints expose the individual subsystems for granular control. A Python SDK is also available (see [SDK.md](SDK.md)) with `XTAOClient.run_plan()` as the matching primary method.

---

## 2. API Endpoints

### 2.1 Health & Metrics

#### GET /api/health

Health check endpoint.

**Request**

No request body.

**Response**

| Field | Type | Description |
|---|---|---|
| `status` | string | Service status, always `"ok"` when healthy |
| `service` | string | Service name, always `"xtao"` |
| `version` | string | Service version |

**Example**

```bash
curl -X GET http://localhost:8000/api/health
```

```json
{
  "status": "ok",
  "service": "xtao",
  "version": "0.1.0"
}
```

---

#### GET /api/metrics

Get online monitoring metrics aggregated from plan execution.

**Request**

No request body.

**Response**

| Field | Type | Description |
|---|---|---|
| `plan_completion_rate` | float | Plan completion rate (0.0–1.0) |
| `step_success_rate` | float | Step success rate (0.0–1.0) |
| `replan_rate` | float | Replan trigger rate (0.0–1.0) |
| `user_correction_rate` | float | User correction rate (0.0–1.0) |
| `task_success_rate` | float | Task success rate (0.0–1.0) |
| `average_iteration_count` | float | Average iteration count per plan |

**Example**

```bash
curl -X GET http://localhost:8000/api/metrics
```

```json
{
  "plan_completion_rate": 0.85,
  "step_success_rate": 0.92,
  "replan_rate": 0.15,
  "user_correction_rate": 0.05,
  "task_success_rate": 0.88,
  "average_iteration_count": 2.3
}
```

---

### 2.2 Plan Management

#### POST /api/plan/run

**Main orchestration entry point.** Runs the complete G4C pipeline internally: generate → verify → execute → correct. On checkpoint failure it orchestrates failure tracing, trust state marking, progressive backtracking, replan (or TCC replan), and replan event recording, then returns the final plan with the full execution trace.

This endpoint internally calls all other endpoints' underlying engines. For granular control, use the individual endpoints directly (or the matching SDK methods).

**Request Body**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `user_input` | string | Yes | — | User's goal or request |
| `conversation_history` | string | No | `""` | Conversation history for context |
| `config` | OrchestratorConfig \| null | No | `null` | Orchestration configuration (uses sensible defaults when `null`) |

**OrchestratorConfig fields**

| Field | Type | Default | Description |
|---|---|---|---|
| `use_iteration` | boolean | `true` | Use the generate-evaluate-correct loop |
| `max_iterations` | integer | `3` | Max iterations for the loop |
| `verify_before_execute` | boolean | `true` | Verify the plan before execution |
| `verification_threshold` | float | `0.8` | Verification score threshold (0–1) |
| `enable_failure_tracing` | boolean | `true` | Enable failure tracing on checkpoint failure |
| `enable_trust_state` | boolean | `true` | Enable trust state management during execution |
| `enable_progressive_backtracking` | boolean | `true` | Enable progressive backtracking on failure |
| `enable_tcc_replan` | boolean | `false` | Enable TCC Replan for high-risk scenarios |
| `max_replan_count` | integer | `3` | Max replan attempts during execution |
| `use_tao` | boolean | `false` | Execute each plan step via the TAO (Think-Action-Observation) controlled state loop |
| `tao_max_loops` | integer | `10` | Max TAO inner loop rounds per step |
| `tao_max_time` | float | `300.0` | Max TAO execution time per step in seconds |
| `tao_supervisor_interval` | integer | `3` | Trigger the TAO outer supervisor loop every N inner rounds (`0` disables it) |
| `tao_supervisor_interval_seconds` | float | `0.0` | Trigger the TAO outer supervisor loop asynchronously every N seconds (`0` disables it) |

**Response** (OrchestratorResult)

| Field | Type | Description |
|---|---|---|
| `plan` | Plan | Final plan (may differ from the initial one if replanned) |
| `status` | string | `completed` / `failed` / `aborted` / `clarify_needed` |
| `step_records` | array[StepExecutionRecord] | Per-step execution trace |
| `replan_count` | integer | Total replan attempts |
| `iteration_count` | integer | Plan generation iterations |
| `verification_score` | float \| null | Plan verification score (0–1) |
| `verification_passed` | boolean \| null | Whether verification passed the threshold |
| `errors` | array[string] | Errors encountered during execution |
| `clarify_message` | string \| null | Clarification message when `status == "clarify_needed"` |

**Example**

```bash
curl -X POST http://localhost:8000/api/plan/run \
  -H "Content-Type: application/json" \
  -d '{
    "user_input": "Design a high-concurrency order system that supports 10000 QPS",
    "conversation_history": "",
    "config": {
      "use_iteration": true,
      "max_iterations": 3,
      "verify_before_execute": true,
      "verification_threshold": 0.8,
      "enable_failure_tracing": true,
      "enable_progressive_backtracking": true,
      "max_replan_count": 3
    }
  }'
```

```json
{
  "plan": { "goal": { "user_goal": "..." }, "status": "completed" },
  "status": "completed",
  "step_records": [
    {
      "step_id": "s1",
      "step_objective": "Gather non-functional requirements",
      "status": "done",
      "checkpoint_passed": true,
      "replan_triggered": false
    }
  ],
  "replan_count": 0,
  "iteration_count": 2,
  "verification_score": 0.86,
  "verification_passed": true,
  "errors": [],
  "clarify_message": null
}
```

---

#### POST /api/plan/generate

Generate a G4C Plan. Supports both normal generation and iterative generation (generate-evaluate-correct loop).

**Request Body**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `user_input` | string | Yes | — | User input describing the task |
| `conversation_history` | string | No | `""` | Conversation history for context |
| `use_iteration` | boolean | No | `false` | Whether to use iterative generation |

**Response**

| Field | Type | Description |
|---|---|---|
| `plan` | Plan | Generated Plan object |
| `verification_results` | array | (Only when `use_iteration=true`) Verification results from each iteration |
| `iterations` | integer | (Only when `use_iteration=true`) Number of iterations performed |

**Example**

```bash
curl -X POST http://localhost:8000/api/plan/generate \
  -H "Content-Type: application/json" \
  -d '{
    "user_input": "Design a high-concurrency order system that supports 10000 QPS",
    "conversation_history": "",
    "use_iteration": false
  }'
```

```json
{
  "plan": {
    "goal": {
      "user_goal": "Design a high-concurrency order system supporting 10000 QPS",
      "success_criteria": [
        "Sustained throughput reaches 10000 QPS under load testing",
        "P99 latency below 200ms"
      ],
      "adjective_standards": {
        "high-concurrency": ">= 10000 QPS"
      }
    },
    "context": {
      "known_facts": ["Target peak QPS is 10000"],
      "missing_info": ["Database type not confirmed"],
      "constraints": {
        "hard": ["Cannot use proprietary paid databases"],
        "soft": ["Prefer open-source solutions"]
      }
    },
    "choice": {
      "selected_path": "Microservice architecture with Redis cache and MySQL sharding",
      "reason": "Based on the hard constraint of open-source only and the 10000 QPS target",
      "candidate_paths": [
        "Single-machine in-memory cache",
        "Microservice architecture with Redis cache and MySQL sharding"
      ],
      "steps": [
        {
          "id": "s1",
          "objective": "Gather non-functional requirements",
          "reason": "Confirms latency budget and consistency level",
          "status": "pending"
        },
        {
          "id": "s2",
          "objective": "Design cache layer with Redis",
          "reason": "Cache layer absorbs read traffic to meet QPS target",
          "status": "pending"
        }
      ]
    },
    "checkpoint": [
      {
        "step_id": "s2",
        "checks": ["Cache hit rate >= 95% under load test"]
      }
    ],
    "correction": [
      {
        "condition": "Cache hit rate below 90%",
        "action": {
          "type": "replan",
          "retry_granularity": null,
          "target_step_id": "s2",
          "params": {},
          "message": "Replan cache strategy if hit rate is too low"
        }
      }
    ],
    "mode": "linear",
    "status": "draft",
    "dag": null,
    "check_results": [],
    "current_step_index": 0,
    "iteration_count": 0
  }
}
```

---

#### POST /api/plan/verify

Evaluate Plan quality across the G4C five dimensions.

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `plan` | Plan | Yes | Plan object to evaluate |

**Response**

| Field | Type | Description |
|---|---|---|
| `verification` | object | Verification result containing G4C five-dimension scores |

**Example**

```bash
curl -X POST http://localhost:8000/api/plan/verify \
  -H "Content-Type: application/json" \
  -d '{
    "plan": {
      "goal": {
        "user_goal": "Design a high-concurrency order system",
        "success_criteria": ["Sustained throughput reaches 10000 QPS"],
        "adjective_standards": {}
      },
      "context": {
        "known_facts": [],
        "missing_info": [],
        "constraints": {"hard": [], "soft": []}
      },
      "choice": {
        "selected_path": "Microservice architecture",
        "reason": "Meets scalability requirement",
        "candidate_paths": [],
        "steps": []
      },
      "checkpoint": [],
      "correction": []
    }
  }'
```

```json
{
  "verification": {
    "overall_score": 8.2,
    "goal_score": 9.0,
    "context_score": 8.0,
    "choice_score": 8.5,
    "checkpoint_score": 7.5,
    "correction_score": 8.0,
    "suggestions": [
      "Add more checkpoints at error-prone steps",
      "Clarify missing information in context"
    ]
  }
}
```

---

#### POST /api/plan/execute

Execute a Plan step-by-step with checkpoint execution.

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `plan` | Plan | Yes | Plan object to execute |

**Response**

| Field | Type | Description |
|---|---|---|
| `plan` | Plan | Executed Plan with updated status and check results |

**Example**

```bash
curl -X POST http://localhost:8000/api/plan/execute \
  -H "Content-Type: application/json" \
  -d '{
    "plan": {
      "goal": {
        "user_goal": "Generate a deployment script",
        "success_criteria": ["Script runs successfully"],
        "adjective_standards": {}
      },
      "context": {
        "known_facts": ["Target environment is Linux"],
        "missing_info": [],
        "constraints": {"hard": ["Must use bash"], "soft": []}
      },
      "choice": {
        "selected_path": "Bash script with error handling",
        "reason": "Meets hard constraint",
        "candidate_paths": [],
        "steps": [
          {"id": "s1", "objective": "Write script skeleton", "reason": "Establish structure", "status": "pending"}
        ]
      },
      "checkpoint": [
        {"step_id": "s1", "checks": ["Script has shebang line"]}
      ],
      "correction": []
    }
  }'
```

```json
{
  "plan": {
    "goal": {
      "user_goal": "Generate a deployment script",
      "success_criteria": ["Script runs successfully"],
      "adjective_standards": {}
    },
    "context": {
      "known_facts": ["Target environment is Linux"],
      "missing_info": [],
      "constraints": {"hard": ["Must use bash"], "soft": []}
    },
    "choice": {
      "selected_path": "Bash script with error handling",
      "reason": "Meets hard constraint",
      "candidate_paths": [],
      "steps": [
        {"id": "s1", "objective": "Write script skeleton", "reason": "Establish structure", "status": "done"}
      ]
    },
    "checkpoint": [
      {"step_id": "s1", "checks": ["Script has shebang line"]}
    ],
    "correction": [],
    "mode": "linear",
    "status": "completed",
    "dag": null,
    "check_results": [
      {
        "step_id": "s1",
        "check_point": "Script has shebang line",
        "passed": true,
        "result": "Shebang line present",
        "evidences": []
      }
    ],
    "current_step_index": 1,
    "iteration_count": 0
  }
}
```

---

#### POST /api/plan/iterate

Iterative Plan generation using the generate-evaluate-correct loop.

**Request Body**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `user_input` | string | Yes | — | User input describing the task |
| `conversation_history` | string | No | `""` | Conversation history for context |

**Response**

| Field | Type | Description |
|---|---|---|
| `plan` | Plan | Final generated Plan after iterations |
| `verification_results` | array | Verification results from each iteration |
| `iterations` | integer | Number of iterations performed |

**Example**

```bash
curl -X POST http://localhost:8000/api/plan/iterate \
  -H "Content-Type: application/json" \
  -d '{
    "user_input": "Design a rate limiter for an API gateway",
    "conversation_history": ""
  }'
```

```json
{
  "plan": {
    "goal": {
      "user_goal": "Design a rate limiter for an API gateway",
      "success_criteria": ["Limits requests to 1000 per second per client"],
      "adjective_standards": {}
    },
    "context": {
      "known_facts": ["API gateway supports Redis"],
      "missing_info": [],
      "constraints": {"hard": [], "soft": []}
    },
    "choice": {
      "selected_path": "Token bucket algorithm with Redis backend",
      "reason": "Token bucket supports burst traffic while enforcing average rate",
      "candidate_paths": [],
      "steps": []
    },
    "checkpoint": [],
    "correction": [],
    "mode": "linear",
    "status": "draft",
    "dag": null,
    "check_results": [],
    "current_step_index": 0,
    "iteration_count": 2
  },
  "verification_results": [
    {"overall_score": 7.0, "suggestions": ["Add more success criteria"]},
    {"overall_score": 8.5, "suggestions": []}
  ],
  "iterations": 2
}
```

---

#### POST /api/plan/replan

Trigger Replan (controlled correction mechanism). Full flow: detect_trigger → code_judge → llm_judge → execute_replan.

**Request Body**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `plan` | Plan | Yes | — | Current Plan object |
| `error_info` | string | No | `""` | Error information description |
| `user_input` | string | No | `""` | User supplementary input |
| `conversation_history` | string | No | `""` | Conversation history |

**Response**

| Field | Type | Description |
|---|---|---|
| `plan` | Plan | New Plan after Replan (or original Plan if no Replan needed) |
| `replan_result` | ReplanResult \| null | Replan execution result details |

**Example**

```bash
curl -X POST http://localhost:8000/api/plan/replan \
  -H "Content-Type: application/json" \
  -d '{
    "plan": {
      "goal": {
        "user_goal": "Deploy service to production",
        "success_criteria": ["Service is live and healthy"],
        "adjective_standards": {}
      },
      "context": {
        "known_facts": [],
        "missing_info": [],
        "constraints": {"hard": [], "soft": []}
      },
      "choice": {
        "selected_path": "Blue-green deployment",
        "reason": "Minimizes downtime",
        "candidate_paths": [],
        "steps": [
          {"id": "s1", "objective": "Provision blue environment", "reason": "Need staging area", "status": "done"},
          {"id": "s2", "objective": "Deploy to blue", "reason": "Deploy new version", "status": "failed"}
        ]
      },
      "checkpoint": [],
      "correction": []
    },
    "error_info": "Blue environment provisioning failed: insufficient quota",
    "user_input": "",
    "conversation_history": ""
  }'
```

```json
{
  "plan": {
    "goal": {
      "user_goal": "Deploy service to production",
      "success_criteria": ["Service is live and healthy"],
      "adjective_standards": {}
    },
    "context": {
      "known_facts": ["Blue environment quota exhausted"],
      "missing_info": [],
      "constraints": {"hard": [], "soft": []}
    },
    "choice": {
      "selected_path": "Rolling deployment",
      "reason": "Switched path because blue-green failed due to quota",
      "candidate_paths": ["Blue-green deployment", "Rolling deployment"],
      "steps": [
        {"id": "s1", "objective": "Provision blue environment", "reason": "Need staging area", "status": "done"},
        {"id": "s2", "objective": "Rolling update pods", "reason": "Incremental rollout avoids quota issue", "status": "pending"}
      ]
    },
    "checkpoint": [],
    "correction": [],
    "mode": "linear",
    "status": "draft",
    "dag": null,
    "check_results": [],
    "current_step_index": 1,
    "iteration_count": 0
  },
  "replan_result": null
}
```

---

#### POST /api/plan/tcc-replan

Execute TCC Replan (Try/Confirm/Cancel three-step methodology). Only applicable to high-failure-cost, high-external-dependency, high-side-effect-risk scenarios.

- **Try**: Minimally validate the weakest point of the new Plan (dry-run, low side effects).
- **Confirm**: Execute Plan after Try passes, reuse Try data.
- **Cancel**: Rollback temporary state after Try fails, mark failed assumptions.

**Request Body**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `plan` | Plan | Yes | — | New Plan to validate |
| `conversation_history` | string | No | `""` | Conversation history to supplement context |

**Response**

| Field | Type | Description |
|---|---|---|
| `result` | TCCResult | TCC Replan complete result |

**Example**

```bash
curl -X POST http://localhost:8000/api/plan/tcc-replan \
  -H "Content-Type: application/json" \
  -d '{
    "plan": {
      "goal": {
        "user_goal": "Migrate database to new cluster",
        "success_criteria": ["Zero data loss", "Downtime under 5 minutes"],
        "adjective_standards": {}
      },
      "context": {
        "known_facts": [],
        "missing_info": [],
        "constraints": {"hard": ["No data loss"], "soft": []}
      },
      "choice": {
        "selected_path": "Dual-write then cutover",
        "reason": "Ensures zero data loss",
        "candidate_paths": [],
        "steps": [
          {"id": "s1", "objective": "Enable dual-write", "reason": "Write to both clusters", "status": "pending"},
          {"id": "s2", "objective": "Verify data consistency", "reason": "Ensure both clusters match", "status": "pending"}
        ]
      },
      "checkpoint": [],
      "correction": []
    },
    "conversation_history": ""
  }'
```

```json
{
  "result": {
    "phase": "confirm",
    "try_result": {
      "validations": [
        {
          "target_step_id": "s1",
          "validation_type": "tool_availability",
          "passed": true,
          "result": "Both database clusters reachable",
          "evidence": "Connectivity test passed"
        },
        {
          "target_step_id": "s2",
          "validation_type": "data_accessibility",
          "passed": true,
          "result": "Consistency check tool available",
          "evidence": "Tool version 1.2 detected"
        }
      ],
      "all_passed": true,
      "temp_data": {"connection_verified": true},
      "failed_assumptions": [],
      "unavailable_tools": []
    },
    "confirm_result": {
      "executed": true,
      "try_results_written": true,
      "reused_try_data": true,
      "execution_summary": "Plan executed successfully, dual-write enabled"
    },
    "cancel_result": null,
    "new_plan": null
  }
}
```

---

#### POST /api/plan/trace

Trigger failure tracing and root cause localization. Core concept: failure point ≠ root cause point. Starting from the failure point, traces backwards to find the root cause, and provides rollback point and Replan start point suggestions.

**Request Body**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `plan` | Plan | Yes | — | Current Plan object |
| `failure_step_id` | string | Yes | — | Failed step ID |
| `failure_info` | string | No | `""` | Failure information description |
| `step_records` | array[StepRecord] | No | `[]` | Step execution record list |

**Response**

| Field | Type | Description |
|---|---|---|
| `result` | FailureTracingResult | Failure tracing result with root cause analysis |

**Example**

```bash
curl -X POST http://localhost:8000/api/plan/trace \
  -H "Content-Type: application/json" \
  -d '{
    "plan": {
      "goal": {
        "user_goal": "Generate analytics report",
        "success_criteria": ["Report contains valid charts"],
        "adjective_standards": {}
      },
      "context": {
        "known_facts": [],
        "missing_info": [],
        "constraints": {"hard": [], "soft": []}
      },
      "choice": {
        "selected_path": "Query DB then render charts",
        "reason": "Standard ETL flow",
        "candidate_paths": [],
        "steps": [
          {"id": "s1", "objective": "Query database", "reason": "Fetch raw data", "status": "done"},
          {"id": "s2", "objective": "Aggregate data", "reason": "Compute metrics", "status": "done"},
          {"id": "s3", "objective": "Render charts", "reason": "Visualize results", "status": "failed"}
        ]
      },
      "checkpoint": [],
      "correction": []
    },
    "failure_step_id": "s3",
    "failure_info": "Chart rendering failed: division by zero",
    "step_records": []
  }'
```

```json
{
  "result": {
    "failure_point": {
      "step_id": "s3",
      "reason": "Chart rendering failed with division by zero",
      "checkpoint_id": null,
      "action": "render_charts",
      "error": "division by zero"
    },
    "root_cause_point": {
      "step_id": "s2",
      "reason": "Aggregation produced zero denominator, causing division by zero downstream",
      "checkpoint_id": null,
      "action": "",
      "error": ""
    },
    "rollback_point": {
      "step_id": "s2",
      "reason": "Rollback to aggregation step to fix denominator",
      "checkpoint_id": null,
      "action": "",
      "error": ""
    },
    "replan_start_point": {
      "step_id": "s2",
      "reason": "Re-plan aggregation logic to handle zero denominator",
      "checkpoint_id": null,
      "action": "",
      "error": ""
    },
    "tracing_chain": [
      {
        "step_id": "s3",
        "reason": "Failure point: chart rendering failed",
        "checkpoint_id": null,
        "action": "render_charts",
        "error": "division by zero"
      },
      {
        "step_id": "s2",
        "reason": "Upstream: aggregation produced zero denominator",
        "checkpoint_id": null,
        "action": "",
        "error": ""
      },
      {
        "step_id": "s1",
        "reason": "Upstream: raw data query returned expected rows",
        "checkpoint_id": null,
        "action": "",
        "error": ""
      }
    ],
    "checkpoint_reliable": true
  }
}
```

---

### 2.3 Constraint Management

#### POST /api/constraints/hard

Add a hard constraint. Constraint modification requires user input as evidence; the Agent cannot modify constraints autonomously.

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `constraint` | string | Yes | Constraint content |
| `user_input` | string | Yes | User input (serves as evidence for constraint modification) |

**Response**

| Field | Type | Description |
|---|---|---|
| `success` | boolean | Whether the operation succeeded |
| `constraints` | array[string] | Updated hard constraint list |

**Example**

```bash
curl -X POST http://localhost:8000/api/constraints/hard \
  -H "Content-Type: application/json" \
  -d '{
    "constraint": "Must use PostgreSQL 15 or above",
    "user_input": "Our company standard requires PostgreSQL 15"
  }'
```

```json
{
  "success": true,
  "constraints": [
    "Must use PostgreSQL 15 or above"
  ]
}
```

---

#### POST /api/constraints/soft

Add a soft constraint.

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `constraint` | string | Yes | Constraint content |
| `user_input` | string | Yes | User input (serves as evidence for constraint modification) |

**Response**

| Field | Type | Description |
|---|---|---|
| `success` | boolean | Whether the operation succeeded |
| `constraints` | array[string] | Updated soft constraint list |

**Example**

```bash
curl -X POST http://localhost:8000/api/constraints/soft \
  -H "Content-Type: application/json" \
  -d '{
    "constraint": "Prefer containerized deployment",
    "user_input": "We prefer Docker-based deployments for consistency"
  }'
```

```json
{
  "success": true,
  "constraints": [
    "Prefer containerized deployment"
  ]
}
```

---

#### GET /api/constraints

Get all constraints (both hard and soft).

**Request**

No request body.

**Response**

| Field | Type | Description |
|---|---|---|
| `hard` | array[string] | Hard constraint list |
| `soft` | array[string] | Soft constraint list |

**Example**

```bash
curl -X GET http://localhost:8000/api/constraints
```

```json
{
  "hard": [
    "Must use PostgreSQL 15 or above"
  ],
  "soft": [
    "Prefer containerized deployment"
  ]
}
```

---

### 2.4 Trust State Management

#### POST /api/trust-state/facts

Add a fact entry. The default trust state is `AVAILABLE`. Supports evidence source and dependency recording.

**Request Body**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `key` | string | Yes | — | Fact key, e.g. `highest_qps` |
| `value` | any | Yes | — | Fact value |
| `evidence` | string | No | `""` | Evidence source |
| `source_step_id` | string | No | `""` | Step ID that produced this fact |
| `depends_on` | array[string] | No | `[]` | List of other fact keys this fact depends on |

**Response**

| Field | Type | Description |
|---|---|---|
| `success` | boolean | Whether the operation succeeded |
| `fact` | FactEntry | Created fact entry |

**Example**

```bash
curl -X POST http://localhost:8000/api/trust-state/facts \
  -H "Content-Type: application/json" \
  -d '{
    "key": "peak_qps",
    "value": 12000,
    "evidence": "Load test report 2026-07-01",
    "source_step_id": "s1",
    "depends_on": []
  }'
```

```json
{
  "success": true,
  "fact": {
    "key": "peak_qps",
    "value": 12000,
    "trust_state": "available",
    "evidence": "Load test report 2026-07-01",
    "source_step_id": "s1",
    "depends_on": []
  }
}
```

---

#### GET /api/trust-state/facts

Get all fact entries.

**Request**

No request body.

**Response**

| Field | Type | Description |
|---|---|---|
| `facts` | array[FactEntry] | All fact entries |

**Example**

```bash
curl -X GET http://localhost:8000/api/trust-state/facts
```

```json
{
  "facts": [
    {
      "key": "peak_qps",
      "value": 12000,
      "trust_state": "available",
      "evidence": "Load test report 2026-07-01",
      "source_step_id": "s1",
      "depends_on": []
    },
    {
      "key": "cache_hit_rate",
      "value": 0.96,
      "trust_state": "verified",
      "evidence": "Monitoring dashboard",
      "source_step_id": "s2",
      "depends_on": ["peak_qps"]
    }
  ]
}
```

---

#### POST /api/trust-state/update

Update the trust state of a fact. If the new state is `INVALID`, automatically triggers cascade marking: all facts depending on this fact will be marked as `DIRTY` (BFS traversal of the dependency chain).

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `key` | string | Yes | Fact key |
| `new_state` | TrustState | Yes | New trust state |
| `reason` | string | No | Change reason |

**Response**

| Field | Type | Description |
|---|---|---|
| `success` | boolean | Whether the operation succeeded |
| `changes` | array[TrustStateChange] | All change records (including cascade marking) |

**Example**

```bash
curl -X POST http://localhost:8000/api/trust-state/update \
  -H "Content-Type: application/json" \
  -d '{
    "key": "peak_qps",
    "new_state": "invalid",
    "reason": "Load test report was found to be flawed"
  }'
```

```json
{
  "success": true,
  "changes": [
    {
      "key": "peak_qps",
      "old_state": "available",
      "new_state": "invalid",
      "reason": "Load test report was found to be flawed",
      "cascaded": false
    },
    {
      "key": "cache_hit_rate",
      "old_state": "verified",
      "new_state": "dirty",
      "reason": "Cascade marking: depends on invalid fact peak_qps",
      "cascaded": true
    }
  ]
}
```

---

#### GET /api/trust-state/report

Get the trust state report, including count statistics for each state.

**Request**

No request body.

**Response**

| Field | Type | Description |
|---|---|---|
| `facts` | array[FactEntry] | All fact entries |
| `changes` | array[TrustStateChange] | State change records |
| `verified_count` | integer | Verified count |
| `available_count` | integer | Available count |
| `suspicious_count` | integer | Suspicious count |
| `invalid_count` | integer | Invalid count |
| `dirty_count` | integer | Dirty count |

**Example**

```bash
curl -X GET http://localhost:8000/api/trust-state/report
```

```json
{
  "facts": [
    {
      "key": "peak_qps",
      "value": 12000,
      "trust_state": "invalid",
      "evidence": "Load test report 2026-07-01",
      "source_step_id": "s1",
      "depends_on": []
    },
    {
      "key": "cache_hit_rate",
      "value": 0.96,
      "trust_state": "dirty",
      "evidence": "Monitoring dashboard",
      "source_step_id": "s2",
      "depends_on": ["peak_qps"]
    }
  ],
  "changes": [],
  "verified_count": 0,
  "available_count": 0,
  "suspicious_count": 0,
  "invalid_count": 1,
  "dirty_count": 1
}
```

---

#### GET /api/trust-state/suspicious

Get Suspicious and Dirty facts that need priority checking. When backtracking to locate root causes, prioritize checking these facts (skip Verified).

**Request**

No request body.

**Response**

| Field | Type | Description |
|---|---|---|
| `facts` | array[FactEntry] | Suspicious and Dirty fact entries |

**Example**

```bash
curl -X GET http://localhost:8000/api/trust-state/suspicious
```

```json
{
  "facts": [
    {
      "key": "cache_hit_rate",
      "value": 0.96,
      "trust_state": "dirty",
      "evidence": "Monitoring dashboard",
      "source_step_id": "s2",
      "depends_on": ["peak_qps"]
    }
  ]
}
```

---

### 2.5 Backtracking

#### POST /api/backtracking/execute

Execute backtracking based on the specified backtracking level. Auto-determines the level if not specified. Supports five backtracking levels: `ACTION` / `STEP` / `STAGE` / `GLOBAL` / `CROSS_TURN`.

**Request Body**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `plan` | Plan | Yes | — | Current Plan object |
| `error_info` | string | No | `""` | Error information description |
| `level` | BacktrackingLevel \| null | No | `null` | Backtracking level, auto-determined when `null` |
| `failure_tracing_result` | object \| null | No | `null` | Failure tracing result |
| `step_id` | string | No | `""` | Failed step ID (action/step level) |
| `decision_id` | string | No | `""` | Decision node ID (step level) |
| `stage_checkpoint_id` | string | No | `""` | Stage Checkpoint ID (stage level) |
| `contamination` | CrossTurnContamination \| null | No | `null` | Cross-turn contamination record (cross_turn level) |

**Response**

| Field | Type | Description |
|---|---|---|
| `result` | BacktrackingResult | Backtracking result |
| `level` | BacktrackingLevel | Backtracking level used |

**Example**

```bash
curl -X POST http://localhost:8000/api/backtracking/execute \
  -H "Content-Type: application/json" \
  -d '{
    "plan": {
      "goal": {
        "user_goal": "Run data pipeline",
        "success_criteria": ["Pipeline completes without errors"],
        "adjective_standards": {}
      },
      "context": {
        "known_facts": [],
        "missing_info": [],
        "constraints": {"hard": [], "soft": []}
      },
      "choice": {
        "selected_path": "Sequential ETL",
        "reason": "Simple and reliable",
        "candidate_paths": [],
        "steps": [
          {"id": "s1", "objective": "Extract data", "reason": "Pull from source", "status": "done"},
          {"id": "s2", "objective": "Transform data", "reason": "Apply transformations", "status": "failed"}
        ]
      },
      "checkpoint": [],
      "correction": []
    },
    "error_info": "Transform step failed: schema mismatch",
    "level": "action",
    "step_id": "s2"
  }'
```

```json
{
  "result": {
    "level": "action",
    "success": true,
    "rollback_to": "s2",
    "new_plan_steps": [
      {"id": "s2", "objective": "Retry transform with adjusted schema", "reason": "Schema mismatch detected", "status": "pending"}
    ],
    "reused_results": ["s1_output"],
    "expanded": false,
    "next_level": null
  },
  "level": "action"
}
```

---

#### POST /api/backtracking/progressive

Progressive expansion backtracking. Progressively expands backtracking scope: `ACTION` → `STEP` → `STAGE` → `GLOBAL`. Judges new plan feasibility via TCC before each expansion.

**Request Body**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `plan` | Plan | Yes | — | Current Plan object |
| `error_info` | string | No | `""` | Error information description |
| `failure_tracing_result` | object \| null | No | `null` | Failure tracing result |

**Response**

| Field | Type | Description |
|---|---|---|
| `result` | BacktrackingResult | Progressive backtracking result |

**Example**

```bash
curl -X POST http://localhost:8000/api/backtracking/progressive \
  -H "Content-Type: application/json" \
  -d '{
    "plan": {
      "goal": {
        "user_goal": "Deploy microservice",
        "success_criteria": ["Service is live"],
        "adjective_standards": {}
      },
      "context": {
        "known_facts": [],
        "missing_info": [],
        "constraints": {"hard": [], "soft": []}
      },
      "choice": {
        "selected_path": "Container deploy",
        "reason": "Standard approach",
        "candidate_paths": [],
        "steps": [
          {"id": "s1", "objective": "Build image", "reason": "Create container", "status": "done"},
          {"id": "s2", "objective": "Push image", "reason": "Upload to registry", "status": "failed"}
        ]
      },
      "checkpoint": [],
      "correction": []
    },
    "error_info": "Image push failed: authentication error"
  }'
```

```json
{
  "result": {
    "level": "step",
    "success": true,
    "rollback_to": "s2",
    "new_plan_steps": [
      {"id": "s2", "objective": "Re-authenticate and push image", "reason": "Switched auth method", "status": "pending"}
    ],
    "reused_results": ["s1_image_built"],
    "expanded": true,
    "next_level": "stage"
  }
}
```

---

#### POST /api/backtracking/jump

Jump backtracking. Matches error patterns via predefined rules, directly locates the backtracking position, skipping the overhead of progressive expansion.

**Request Body**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `error_pattern` | string | Yes | — | Error pattern description |
| `jump_rules` | array[JumpRule] \| null | No | `null` | Jump backtracking rule list |

**Response**

| Field | Type | Description |
|---|---|---|
| `result` | BacktrackingResult \| null | Backtracking result, `null` if no rule matched |
| `matched` | boolean | Whether a rule was matched |

**Example**

```bash
curl -X POST http://localhost:8000/api/backtracking/jump \
  -H "Content-Type: application/json" \
  -d '{
    "error_pattern": "authentication denied",
    "jump_rules": [
      {
        "error_pattern": "authentication denied",
        "rollback_position": "s1",
        "new_plan_template": "Refresh credentials then retry",
        "similarity_threshold": 0.8
      }
    ]
  }'
```

```json
{
  "result": {
    "level": "stage",
    "success": true,
    "rollback_to": "s1",
    "new_plan_steps": [
      {"id": "s1", "objective": "Refresh credentials then retry", "reason": "Matched authentication denied rule", "status": "pending"}
    ],
    "reused_results": [],
    "expanded": false,
    "next_level": null
  },
  "matched": true
}
```

---

### 2.6 Candidate Paths

#### POST /api/candidate-paths/register

Register a decision node. Records the selected path and candidate path list, supporting subsequent path switching.

**Request Body**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `decision_id` | string | Yes | — | Decision node ID |
| `selected` | string | Yes | — | Currently selected path |
| `candidates` | array[CandidatePath] | No | `[]` | Candidate path list |

**Response**

| Field | Type | Description |
|---|---|---|
| `success` | boolean | Whether the operation succeeded |
| `decision_id` | string | Decision node ID |
| `selected` | string | Currently selected path |
| `candidate_count` | integer | Number of candidate paths |

**Example**

```bash
curl -X POST http://localhost:8000/api/candidate-paths/register \
  -H "Content-Type: application/json" \
  -d '{
    "decision_id": "db_choice",
    "selected": "postgresql",
    "candidates": [
      {"path": "postgresql", "status": "available", "reason": "", "failure_id": ""},
      {"path": "mysql", "status": "available", "reason": "", "failure_id": ""},
      {"path": "mongodb", "status": "available", "reason": "", "failure_id": ""}
    ]
  }'
```

```json
{
  "success": true,
  "decision_id": "db_choice",
  "selected": "postgresql",
  "candidate_count": 3
}
```

---

#### POST /api/candidate-paths/switch/{decision_id}

Fast path switching. Gets the next available candidate path of the decision node and switches to it.

**Path Parameters**

| Parameter | Type | Description |
|---|---|---|
| `decision_id` | string | Decision node ID |

**Request**

No request body.

**Response**

| Field | Type | Description |
|---|---|---|
| `success` | boolean | Whether the operation succeeded |
| `new_path` | string | New path switched to |

**Example**

```bash
curl -X POST http://localhost:8000/api/candidate-paths/switch/db_choice
```

```json
{
  "success": true,
  "new_path": "mysql"
}
```

---

#### GET /api/candidate-paths/failed

Get failed path records. Returns all failed path records, including failure reasons and recovery status.

**Request**

No request body.

**Response**

| Field | Type | Description |
|---|---|---|
| `failed_paths` | array[FailurePathRecord] | Failed path records |

**Example**

```bash
curl -X GET http://localhost:8000/api/candidate-paths/failed
```

```json
{
  "failed_paths": [
    {
      "path": "postgresql",
      "failure_reason": "Connection timeout in production environment",
      "failure_turn": 3,
      "recovered": false,
      "recovery_checked_at": ""
    }
  ]
}
```

---

### 2.7 Evaluation

#### POST /api/evaluation/offline

Offline analysis of Plan quality across the G4C five dimensions.

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `plan` | Plan | Yes | Plan object to analyze |

**Response**

| Field | Type | Description |
|---|---|---|
| `analysis` | object | Offline analysis result |

**Example**

```bash
curl -X POST http://localhost:8000/api/evaluation/offline \
  -H "Content-Type: application/json" \
  -d '{
    "plan": {
      "goal": {
        "user_goal": "Build a REST API",
        "success_criteria": ["API responds with 200"],
        "adjective_standards": {}
      },
      "context": {
        "known_facts": [],
        "missing_info": [],
        "constraints": {"hard": [], "soft": []}
      },
      "choice": {
        "selected_path": "FastAPI with SQLAlchemy",
        "reason": "Modern and fast",
        "candidate_paths": [],
        "steps": []
      },
      "checkpoint": [],
      "correction": []
    }
  }'
```

```json
{
  "analysis": {
    "goal_analysis": "Goal is clear but success criteria could be more specific",
    "context_analysis": "Context is sparse, consider adding known constraints",
    "choice_analysis": "Path selection is reasonable",
    "checkpoint_analysis": "No checkpoints defined, add at least one",
    "correction_analysis": "No correction rules defined",
    "overall_score": 6.5,
    "recommendations": [
      "Add measurable success criteria",
      "Add checkpoints at key milestones"
    ]
  }
}
```

---

#### POST /api/evaluation/replan/event

Record a Replan event. Collects complete information of a single Replan event for subsequent effect evaluation. Events with the same `event_id` are updated rather than duplicated.

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `event` | ReplanEvent | Yes | Replan event record |

**Response**

| Field | Type | Description |
|---|---|---|
| `success` | boolean | Whether the operation succeeded |
| `event_id` | string | Event ID |
| `total_events` | integer | Total number of recorded events |

**Example**

```bash
curl -X POST http://localhost:8000/api/evaluation/replan/event \
  -H "Content-Type: application/json" \
  -d '{
    "event": {
      "event_id": "evt-001",
      "timestamp": "2026-07-26T10:00:00Z",
      "plan_id": "plan-001",
      "trigger": "tool_failure",
      "failure_step_id": "s3",
      "root_cause_step_id": "s1",
      "actual_root_cause": "",
      "root_cause_correct": null,
      "replan_start_step_id": "s1",
      "actual_replan_start": "",
      "replan_start_correct": null,
      "total_results": 5,
      "trusted_results": 3,
      "reused_results": 2,
      "recovered": true,
      "path_history": ["path_a", "path_b"]
    }
  }'
```

```json
{
  "success": true,
  "event_id": "evt-001",
  "total_events": 1
}
```

---

#### GET /api/evaluation/replan/metrics

Get Replan effectiveness evaluation five metrics.

**Request**

No request body.

**Response** (ReplanMetrics)

| Field | Type | Description |
|---|---|---|
| `root_cause_accuracy` | float | Root cause localization accuracy (0.0–1.0) |
| `replan_start_accuracy` | float | Replan start point accuracy (0.0–1.0) |
| `result_reuse_rate` | float | Existing result reuse rate (0.0–1.0) |
| `recovery_success_rate` | float | Replan recovery success rate (0.0–1.0) |
| `oscillation_rate` | float | Replan oscillation rate (0.0–1.0) |
| `total_replan_count` | integer | Total Replan count |
| `total_failure_cases` | integer | Total failure case count |

**Example**

```bash
curl -X GET http://localhost:8000/api/evaluation/replan/metrics
```

```json
{
  "root_cause_accuracy": 0.82,
  "replan_start_accuracy": 0.75,
  "result_reuse_rate": 0.6,
  "recovery_success_rate": 0.88,
  "oscillation_rate": 0.05,
  "total_replan_count": 20,
  "total_failure_cases": 18
}
```

---

#### GET /api/evaluation/replan/report

Get the Replan evaluation report in text format, including the five metrics and improvement suggestions.

**Request**

No request body.

**Response**

| Field | Type | Description |
|---|---|---|
| `report` | string | Evaluation report text |

**Example**

```bash
curl -X GET http://localhost:8000/api/evaluation/replan/report
```

```json
{
  "report": "Replan Effectiveness Evaluation Report\n=======================================\n\nFive Core Metrics:\n- Root Cause Accuracy: 0.82\n- Replan Start Accuracy: 0.75\n- Result Reuse Rate: 0.60\n- Recovery Success Rate: 0.88\n- Oscillation Rate: 0.05\n\nTotal Replan Count: 20\nTotal Failure Cases: 18\n\nSuggestions:\n1. Improve root cause localization by adding more checkpoints.\n2. Replan start point selection could be more conservative.\n3. Increase reuse of existing intermediate results."
}
```

---

#### POST /api/evaluation/replan/annotate

Import manual annotation results. Matches and updates event annotation fields by `event_id` (e.g. `root_cause_correct`, `replan_start_correct`).

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `annotations` | array[object] | Yes | Annotation list, each item contains `event_id` and annotation fields |

**Response**

| Field | Type | Description |
|---|---|---|
| `success` | boolean | Whether the operation succeeded |
| `annotated_count` | integer | Number of annotations imported |

**Example**

```bash
curl -X POST http://localhost:8000/api/evaluation/replan/annotate \
  -H "Content-Type: application/json" \
  -d '{
    "annotations": [
      {
        "event_id": "evt-001",
        "root_cause_correct": true,
        "replan_start_correct": false,
        "actual_root_cause": "s1",
        "actual_replan_start": "s2"
      }
    ]
  }'
```

```json
{
  "success": true,
  "annotated_count": 1
}
```

---

#### GET /api/evaluation/replan/test-set

Export the Replan evaluation test set. Exports key fields of all events for manual annotation or fault injection evaluation. The `root_cause_correct` and `replan_start_correct` fields are set to `null` for annotation.

**Request**

No request body.

**Response**

| Field | Type | Description |
|---|---|---|
| `test_set` | array[object] | Test set entries |
| `total` | integer | Total number of entries |

**Example**

```bash
curl -X GET http://localhost:8000/api/evaluation/replan/test-set
```

```json
{
  "test_set": [
    {
      "event_id": "evt-001",
      "plan_id": "plan-001",
      "trigger": "tool_failure",
      "failure_step_id": "s3",
      "root_cause_step_id": "s1",
      "root_cause_correct": null,
      "replan_start_step_id": "s1",
      "replan_start_correct": null,
      "path_history": ["path_a", "path_b"]
    }
  ],
  "total": 1
}
```

---

### 2.8 DAG

#### POST /api/dag/validate

Validate DAG structure (circular dependency detection, node reference validity).

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `dag` | DAGPlan | Yes | DAG Plan structure to validate |

**Response**

| Field | Type | Description |
|---|---|---|
| `valid` | boolean | Whether the DAG is valid |
| `errors` | array[string] | Validation error messages |
| `cycles` | array[array[string]] | Detected cycles (each cycle is a list of node IDs) |
| `topological_order` | array[string] | Topological ordering of nodes |

**Example**

```bash
curl -X POST http://localhost:8000/api/dag/validate \
  -H "Content-Type: application/json" \
  -d '{
    "dag": {
      "nodes": [
        {"id": "n1", "objective": "Fetch data", "reason": "Get source data", "depends_on": [], "status": "pending"},
        {"id": "n2", "objective": "Process data", "reason": "Transform", "depends_on": ["n1"], "status": "pending"},
        {"id": "n3", "objective": "Export data", "reason": "Save results", "depends_on": ["n2"], "status": "pending"}
      ],
      "edges": [
        {"src": "n1", "dst": "n2", "attrs": {}},
        {"src": "n2", "dst": "n3", "attrs": {}}
      ]
    }
  }'
```

```json
{
  "valid": true,
  "errors": [],
  "cycles": [],
  "topological_order": ["n1", "n2", "n3"]
}
```

**Example with a cycle:**

```bash
curl -X POST http://localhost:8000/api/dag/validate \
  -H "Content-Type: application/json" \
  -d '{
    "dag": {
      "nodes": [
        {"id": "n1", "objective": "Step A", "reason": "", "depends_on": ["n2"], "status": "pending"},
        {"id": "n2", "objective": "Step B", "reason": "", "depends_on": ["n1"], "status": "pending"}
      ],
      "edges": [
        {"src": "n1", "dst": "n2", "attrs": {}},
        {"src": "n2", "dst": "n1", "attrs": {}}
      ]
    }
  }'
```

```json
{
  "valid": false,
  "errors": ["Cycle detected: n1 -> n2 -> n1"],
  "cycles": [["n1", "n2", "n1"]],
  "topological_order": []
}
```

---

### 2.9 TAO (Think-Action-Observation)

TAO is a controlled state loop for step-level execution. The Plan defines the macro path; TAO decides how each concrete step moves forward and interprets feedback. It maintains five runtime states — **Goal / Action / Observation / Fact / Control** — and takes exactly one exit per round: `continue` / `finish` / `clarify` / `retry` / `replan` / `interrupt`.

Each round runs: **Think** (five structured judgments: goal, state, path, stop, risk) → **Action** (execute the selected candidate) → **Observation** (interpret the raw output, extract evidence-bound facts) → **state update** → **exit decision**. An optional outer supervisor loop checks goal drift, constraint violations and stagnation every N inner rounds. Control State prevents runaway execution via `max_loops` / `max_time`.

TAO can also be enabled per step inside the main orchestration flow via `OrchestratorConfig.use_tao` (see [POST /api/plan/run](#post-apiplanrun)).

#### Action Design & Candidate Filtering

An Action in TAO is a goal-oriented wrapper, not a raw tool. Good Action design directly affects Think accuracy and loop stability.

**Design principles**

| Principle | Description |
|---|---|
| Business completeness | An Action represents a complete business operation; internally it may call one tool, multiple tools, or spawn a sub-agent. |
| Orthogonality | Actions have clear responsibility boundaries; overlap should be minimized. |
| Sub-agent encapsulation | Complex subtasks are encapsulated as sub-agents and launched via Actions. |
| Coarse-grained anti-pattern | When the action space is too large, prefer coarse-grained Actions whose internal logic dispatches to concrete operations, combined with multi-stage filtering. |
| Minimal params/returns | Parameters should be easy to obtain; return values should expose only what the caller needs. |

**Candidate metadata**

`ActionCandidate` carries extended metadata to support filtering and evidence-based selection. Beyond the base fields documented in the model reference, the following fields are available:

| Field | Type | Description |
|---|---|---|
| `applicable_scenarios` | array[string] | Scenarios where this action should be used. |
| `inapplicable_scenarios` | array[string] | Scenarios where this action must NOT be used. |
| `required_params` | array[string] | Required parameter keys. |
| `optional_params` | array[string] | Optional parameter keys. |
| `cost` | string | Cost estimate: `low` / `medium` / `high`. |
| `risk` | string | Risk level: `low` / `medium` / `high`. |
| `reversible` | boolean | Whether the action can be undone. |
| `permissions` | array[string] | Required permissions or authorization scopes. |
| `tags` | array[string] | Tags for filtering. |
| `intents` | array[string] | Intents under which this action is applicable. |
| `repeatable_on_retry` | boolean | Whether the action may recover on retry (e.g. transient network delays). |
| `alternatives` | array[string] | Names of alternative actions that can replace this one. |

**Filtering pipeline**

The engine coarse-filters the full candidate space before each Think round:

```
All Actions → intent/tag filter → rule engine → preconditions/permissions → success rate → information gain → LLM coarse filter → LLM fine filter → Selected Action
```

- Deterministic filters (intent, tag, rules, preconditions, permissions) run first and can short-circuit the pipeline when the remaining candidates are few enough.
- `ActionFilterRule` objects can be used to include/exclude actions based on facts, permissions, or intent.
- Historical success rates are tracked in `ActionAvailability` and used to deprioritize or temporarily disable unreliable actions.
- Information-gain ranking prioritizes actions that fill currently missing slots.
- LLM coarse filter uses the fast model with minimal context; the fine filter uses the pro model with full context.

**Execution guards**

Before executing the selected action, the runtime verifies:
- The action name is in the current candidate space.
- All `required_params` are present.
- The caller has the required `permissions`.
- Input parameters conform to `params_schema`.

**High availability & permissions**

Actions support retry, fallback to `alternatives`, circuit-breaker disabling, and rate limiting. Permission checks can be implemented either inside the Action wrapper or via a unified AOP layer.

#### POST /api/tao/run

Run the full TAO loop until an exit other than continue/retry is taken.

**Request Body**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `user_input` | string | Yes | — | User's goal or request |
| `plan` | Plan \| null | No | `null` | Optional G4C Plan providing goal/context anchoring |
| `candidate_actions` | array[ActionCandidate] | No | `[]` | Full candidate action space (coarse-filtered inside the engine) |
| `max_loops` | integer | No | `10` | Maximum TAO inner loop rounds |
| `max_time` | float | No | `300.0` | Maximum execution time in seconds |

**Response** (TAOResult)

| Field | Type | Description |
|---|---|---|
| `exit_type` | string | Final exit: `finish` / `clarify` / `replan` / `interrupt` |
| `final_output` | string | Final output text (when `exit_type == "finish"`) |
| `clarify_message` | string | Question to the user (when `exit_type == "clarify"`) |
| `exit_reason` | string | Exit reason detail |
| `used_loops` | integer | Total loop rounds used |
| `total_actions` | integer | Total actions executed |
| `exit_history` | array[TAOExitRecord] | Exit decision record of every round |
| `state` | TAOState \| null | Final TAO state snapshot |

**Example**

```bash
curl -X POST http://localhost:8000/api/tao/run \
  -H "Content-Type: application/json" \
  -d '{
    "user_input": "Summarize the Q3 sales report",
    "candidate_actions": [
      {
        "name": "read_report",
        "type": "tool_call",
        "description": "Read the sales report file",
        "params_schema": {"path": "report file path"}
      },
      {
        "name": "ask_user",
        "type": "user_interaction",
        "description": "Ask the user for missing information"
      }
    ],
    "max_loops": 10,
    "max_time": 300.0
  }'
```

```json
{
  "exit_type": "finish",
  "final_output": "Q3 sales grew 12% QoQ, driven by ...",
  "clarify_message": "",
  "exit_reason": "Success criteria satisfied",
  "used_loops": 3,
  "total_actions": 3,
  "exit_history": [
    {"exit_type": "continue", "reason": "...", "used_loops": 1},
    {"exit_type": "finish", "reason": "Success criteria satisfied", "used_loops": 3}
  ],
  "state": { "goal_state": {"final_goal": "..."}, "facts": {}, "control": {"used_loops": 3} }
}
```

---

#### POST /api/tao/think

Atomic TAO Think: run one Think round on the given state. The caller carries the `TAOState` between calls (stateful client, stateless server).

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `state` | TAOState | Yes | Current TAO state |

**Response**

| Field | Type | Description |
|---|---|---|
| `think` | ThinkResult | Structured Think result (five judgments) |
| `exit` | TAOExitRecord | Exit decision for this round |

**Example**

```bash
curl -X POST http://localhost:8000/api/tao/think \
  -H "Content-Type: application/json" \
  -d '{
    "state": {
      "goal_state": {"final_goal": "Summarize the Q3 sales report", "current_goal": "Read the report"},
      "candidate_actions": [{"name": "read_report", "type": "tool_call"}],
      "control": {"max_loops": 10, "used_loops": 0}
    }
  }'
```

```json
{
  "think": {
    "current_goal": "Read the report",
    "facts_sufficient": false,
    "selected_action": "read_report",
    "action_params": {"path": "q3-sales.md"},
    "should_stop": false,
    "exit_decision": "continue",
    "reason": "Report content is required before summarizing",
    "risk_level": "low"
  },
  "exit": {"exit_type": "continue", "reason": "...", "used_loops": 0, "overridden": false}
}
```

---

#### POST /api/tao/act

Atomic TAO Action execution. Executes the named action from the candidate space carried in the state. Illegal actions (outside the candidate space) and unsatisfied hard preconditions are rejected with a `400` error.

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `state` | TAOState | Yes | Current TAO state (carries the candidate space) |
| `action_name` | string | Yes | Selected action name (must be in the candidate space) |
| `params` | object | No | Action parameters (default `{}`) |

**Response**

| Field | Type | Description |
|---|---|---|
| `record` | ActionRecord | Executed action record (status `done` or `failed`) |

**Example**

```bash
curl -X POST http://localhost:8000/api/tao/act \
  -H "Content-Type: application/json" \
  -d '{
    "state": {"candidate_actions": [{"name": "read_report", "type": "tool_call"}]},
    "action_name": "read_report",
    "params": {"path": "q3-sales.md"}
  }'
```

```json
{
  "record": {
    "action_id": "act-1a2b3c4d",
    "name": "read_report",
    "type": "tool_call",
    "input": {"path": "q3-sales.md"},
    "output": "Q3 sales grew 12% QoQ ...",
    "status": "done",
    "retry_count": 0
  }
}
```

---

#### POST /api/tao/observe

Atomic TAO Observation interpretation. Code performs field/format checks; the LLM performs semantic interpretation (fact extraction, evidence binding, gap identification). Note: HTTP 200 != real success — empty data, permission errors and anomalies are detected.

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `state` | TAOState | Yes | Current TAO state |
| `record` | ActionRecord | Yes | Action record to interpret |
| `expectation` | string | No | Optional expectation for the output |

**Response**

| Field | Type | Description |
|---|---|---|
| `observation` | Observation | Structured interpretation of the raw output |

**Example**

```bash
curl -X POST http://localhost:8000/api/tao/observe \
  -H "Content-Type: application/json" \
  -d '{
    "state": {"goal_state": {"final_goal": "Summarize the Q3 sales report"}},
    "record": {"action_id": "act-1a2b3c4d", "name": "read_report", "output": "Q3 sales grew 12% QoQ ...", "status": "done"}
  }'
```

```json
{
  "observation": {
    "observation_id": "obs-5e6f7a8b",
    "action_id": "act-1a2b3c4d",
    "execution_status": "success",
    "new_facts": [
      {"key": "q3_sales_growth", "value": "12% QoQ", "category": "confirmed", "evidence": "act-1a2b3c4d"}
    ],
    "missing_information": [],
    "progress": true,
    "information_gain": "high",
    "summary": "Report read successfully; growth figures extracted"
  }
}
```

#### POST /api/evaluation/tao/event

Record a TAO evaluation event containing Think / Action / Observation round data for subsequent metric computation.

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `event` | TAOEvaluationEvent | Yes | TAO evaluation event |

**Response**

| Field | Type | Description |
|---|---|---|
| `success` | boolean | Whether the event was recorded |
| `event_id` | string | Event ID |
| `total_events` | integer | Total recorded events |

---

#### GET /api/evaluation/tao/metrics

Get aggregated TAO evaluation metrics across four layers: Think, Action, Observation and Overall.

**Response** (TAOEvaluationMetrics)

| Field | Type | Description |
|---|---|---|
| `think` | ThinkMetrics | Think-phase metrics |
| `action` | ActionMetrics | Action execution metrics |
| `observation` | ObservationMetrics | Observation interpretation metrics |
| `overall` | OverallMetrics | Overall task metrics |

---

#### GET /api/evaluation/tao/report

Generate a TAO evaluation report with metrics, abnormal samples and optimization suggestions.

**Response** (TAOEvaluationReport)

| Field | Type | Description |
|---|---|---|
| `metrics` | TAOEvaluationMetrics | Aggregated metrics |
| `suggestions` | array[TAOEvaluationSuggestion] | Optimization suggestions |
| `abnormal_samples` | array[string] | Abnormal sample event IDs |
| `summary` | string | Natural-language summary |

---

#### POST /api/evaluation/tao/annotate

Import golden-answer annotations for computing accuracy metrics such as action selection and fact extraction.

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `annotations` | array[GoldenAnswer] | Yes | List of golden answers keyed by event_id |

**Response**

| Field | Type | Description |
|---|---|---|
| `success` | boolean | Whether import succeeded |
| `annotated_count` | integer | Number of imported annotations |

---

#### GET /api/evaluation/tao/test-set

Export a test set for human annotation with golden-answer fields left empty.

**Response**

| Field | Type | Description |
|---|---|---|
| `test_set` | array[dict] | Test set |
| `total` | integer | Sample count |

---

#### POST /api/evaluation/tao/judge

Run LLM-as-judge on a single TAO round.

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `request` | LLMJudgeRequest | Yes | Judge request for a TAO round |

**Response** (LLMJudgeResult)

| Field | Type | Description |
|---|---|---|
| `event_id` | string | Event ID |
| `round_index` | integer | Round index |
| `source` | string | Source: `llm` / `code` |
| `scores` | object | Metric scores |
| `reasoning` | string | Scoring reasoning |

---

## 3. Data Models

### Plan

The G4C composite Plan object, resolving execution uncertainty through five elements.

| Field | Type | Default | Description |
|---|---|---|---|
| `goal` | Goal | — | Goal and success criteria |
| `context` | Context | `{}` | Context and constraints |
| `choice` | Choice | — | Path decision and steps |
| `checkpoint` | array[Checkpoint] | `[]` | Checkpoint list |
| `correction` | array[Correction] | `[]` | Correction rule list |
| `mode` | PlanMode | `"linear"` | Plan mode (`linear` or `dag`) |
| `status` | PlanStatus | `"draft"` | Execution status |
| `dag` | DAGPlan \| null | `null` | DAG structure (only when `mode=dag`) |
| `check_results` | array[CheckResult] | `[]` | Checkpoint execution results |
| `current_step_index` | integer | `0` | Current execution step index |
| `iteration_count` | integer | `0` | Iteration generation loop count |

#### Goal

| Field | Type | Default | Description |
|---|---|---|---|
| `user_goal` | string | — | User goal description |
| `success_criteria` | array[string] | `[]` | Success criteria list, each item must be verifiable |
| `adjective_standards` | object | `{}` | Adjective standard definitions, mapping vague adjectives to quantifiable criteria |

#### Context

| Field | Type | Default | Description |
|---|---|---|---|
| `known_facts` | array[string] | `[]` | Known facts list |
| `missing_info` | array[string] | `[]` | Missing information list |
| `constraints` | Constraints | `{}` | Constraint set |

#### Constraints

| Field | Type | Default | Description |
|---|---|---|---|
| `hard` | array[string] | `[]` | Hard constraint list, cannot be violated |
| `soft` | array[string] | `[]` | Soft constraint list, should be satisfied |

#### Choice

| Field | Type | Default | Description |
|---|---|---|---|
| `selected_path` | string | — | Description of the selected path |
| `reason` | string | — | Selection reason, must be evidence-based |
| `candidate_paths` | array[string] | `[]` | Candidate path list |
| `steps` | array[Step] | `[]` | Step list |

#### Step

| Field | Type | Default | Description |
|---|---|---|---|
| `id` | string | — | Step unique identifier |
| `objective` | string | — | Step objective |
| `reason` | string | `""` | Reason for the step's existence |
| `status` | string | `"pending"` | Step status: `pending` \| `running` \| `done` \| `failed` \| `skipped` |

#### Checkpoint

| Field | Type | Default | Description |
|---|---|---|---|
| `step_id` | string | — | Associated step ID |
| `checks` | array[string] | `[]` | Check item list |

#### CheckResult

| Field | Type | Default | Description |
|---|---|---|---|
| `step_id` | string | — | Associated step ID |
| `check_point` | string | — | Check item |
| `passed` | boolean | — | Whether passed |
| `result` | string | — | Check result description |
| `evidences` | array[CheckEvidence] | `[]` | Evidence list |

#### Correction

| Field | Type | Description |
|---|---|---|
| `condition` | string | Trigger condition description |
| `action` | CorrectionAction | Correction action |

#### CorrectionAction

| Field | Type | Default | Description |
|---|---|---|---|
| `type` | CorrectionType | — | Correction strategy type |
| `retry_granularity` | RetryGranularity \| null | `null` | Retry granularity (only when `type=retry`) |
| `target_step_id` | string \| null | `null` | Target step ID (for rollback or partial retry) |
| `params` | object | `{}` | Additional parameters |
| `message` | string | `""` | Description of the correction action |

### PlanMode (enum)

| Value | Description |
|---|---|
| `linear` | Linear Plan (default), simple, reliable, easy to debug |
| `dag` | DAG-style Plan, suitable for complex scenarios requiring step parallelism |

### PlanStatus (enum)

| Value | Description |
|---|---|
| `draft` | Draft state |
| `ready` | Ready to execute |
| `running` | Currently executing |
| `completed` | Execution completed |
| `failed` | Execution failed |
| `aborted` | Execution aborted |

### CorrectionType (enum)

| Value | Description |
|---|---|
| `retry` | Retry (step-level / partial-flow / full-restart) |
| `replan` | Regenerate Plan |
| `clarify` | Clarify with user |
| `rollback` | Rollback to before a step |
| `abort` | Abort execution |

### ReplanResult

Replan execution result, containing step change classification and updated control info.

| Field | Type | Default | Description |
|---|---|---|---|
| `retained_steps` | array[StepChange] | `[]` | Retained steps and reasons |
| `modified_steps` | array[StepChange] | `[]` | Modified steps and reasons |
| `removed_steps` | array[StepChange] | `[]` | Removed steps and reasons |
| `new_plan` | Plan \| null | `null` | New Plan after Replan |
| `replan_info` | ReplanInfo | `{}` | Updated Replan control info |

### ReplanTrigger (enum)

| Value | Description |
|---|---|
| `tool_failure` | Tool call failure (non-transient) |
| `context_change` | Context changed (user adds constraints or supplements information) |
| `assumption_violation` | Assumption violated (checkpoint not passed) |

### ReplanGranularity (enum)

| Value | Description |
|---|---|
| `step` | Current step Replan, retains previously completed steps |
| `partial` | Partial Replan, re-plans from a specified rollback step |
| `global` | Global Replan, generates a brand new Plan from scratch |

### TCCResult

TCC Replan complete result.

| Field | Type | Default | Description |
|---|---|---|---|
| `phase` | TCCPhase | — | Final phase (`try` / `confirm` / `cancel`) |
| `try_result` | TryResult \| null | `null` | Try phase result |
| `confirm_result` | ConfirmResult \| null | `null` | Confirm phase result |
| `cancel_result` | CancelResult \| null | `null` | Cancel phase result |
| `new_plan` | Plan \| null | `null` | Final new Plan (if successful) |

### TCCPhase (enum)

| Value | Description |
|---|---|
| `try` | Try phase |
| `confirm` | Confirm phase |
| `cancel` | Cancel phase |

### FailureTracingResult

Failure backtracking result, containing four key point definitions and the reverse tracing chain.

| Field | Type | Default | Description |
|---|---|---|---|
| `failure_point` | TracingPoint | — | Failure point: where the error is exposed |
| `root_cause_point` | TracingPoint \| null | `null` | Root cause point: where the error was originally introduced |
| `rollback_point` | TracingPoint \| null | `null` | Rollback point: state recovery location |
| `replan_start_point` | TracingPoint \| null | `null` | Replan start point |
| `tracing_chain` | array[TracingPoint] | `[]` | Reverse tracing chain |
| `checkpoint_reliable` | boolean | `true` | Whether the Checkpoint is reliable |

### TrustState (enum)

Intermediate result trust state.

| Value | Description |
|---|---|
| `verified` | Verified, currently trusted |
| `available` | Temporarily usable, not fully verified |
| `suspicious` | May have issues, needs re-checking |
| `invalid` | Confirmed error |
| `dirty` | Depends on an Invalid result |

### FactEntry

| Field | Type | Default | Description |
|---|---|---|---|
| `key` | string | — | Fact key |
| `value` | any | — | Fact value |
| `trust_state` | TrustState | `"available"` | Trust state |
| `evidence` | string | `""` | Evidence source |
| `source_step_id` | string | `""` | Step ID that produced this fact |
| `depends_on` | array[string] | `[]` | Other fact keys depended on |

### BacktrackingLevel (enum)

| Value | Description |
|---|---|
| `action` | Action level (retry), does not modify Plan |
| `step` | Step level (switch tool), switches to next candidate path |
| `stage` | Stage level (return to stage entry), re-plans with Checkpoint as boundary |
| `global` | Global, invalidates all intermediate results |
| `cross_turn` | Cross-turn, handles historical data contaminated by error facts |

### BacktrackingResult

| Field | Type | Default | Description |
|---|---|---|---|
| `level` | BacktrackingLevel | — | Backtracking level |
| `success` | boolean | `false` | Whether backtracking succeeded |
| `rollback_to` | string | `""` | Rollback position (step_id or stage_id) |
| `new_plan_steps` | array[object] | `[]` | New plan steps |
| `reused_results` | array[string] | `[]` | Reused intermediate results |
| `expanded` | boolean | `false` | Whether backtracking scope was expanded |
| `next_level` | BacktrackingLevel \| null | `null` | Next expanded level |

### ReplanMetrics

Replan effectiveness evaluation metrics.

| Field | Type | Default | Description |
|---|---|---|---|
| `root_cause_accuracy` | float | `0.0` | Root cause localization accuracy |
| `replan_start_accuracy` | float | `0.0` | Replan start point accuracy |
| `result_reuse_rate` | float | `0.0` | Existing result reuse rate |
| `recovery_success_rate` | float | `0.0` | Replan recovery success rate |
| `oscillation_rate` | float | `0.0` | Replan oscillation rate |
| `total_replan_count` | integer | `0` | Total Replan count |
| `total_failure_cases` | integer | `0` | Total failure case count |

### DAGPlan

| Field | Type | Default | Description |
|---|---|---|---|
| `nodes` | array[DAGNode] | `[]` | Node list |
| `edges` | array[DAGEdge] | `[]` | Edge list for dependency relationships |

### CandidatePath

| Field | Type | Default | Description |
|---|---|---|---|
| `path` | string | — | Path name |
| `status` | string | `"available"` | Status: `available` / `failed` / `tried` |
| `reason` | string | `""` | Failure reason (when failed) |
| `failure_id` | string | `""` | Failure record ID |

### TAOState

Aggregate TAO runtime state, carried across loop rounds (and between atomic API calls).

| Field | Type | Default | Description |
|---|---|---|---|
| `goal_state` | GoalState | — | Goal State: `final_goal`, `current_goal`, `success_criteria`, `current_goal_completed` |
| `actions` | array[ActionRecord] | `[]` | Action State: executed action records in order |
| `observations` | array[Observation] | `[]` | Observation State: structured interpretations in order |
| `facts` | object | `{}` | Fact State: fact key → FactItem (`key` / `value` / `category` / `evidence`) |
| `control` | ControlState | `{}` | Control State: `max_loops` / `used_loops` / `max_time` / `start_time` / `exit_reason` / `max_action_retries` |
| `plan_step_id` | string | `""` | Associated Plan step ID, if any |
| `candidate_actions` | array[ActionCandidate] | `[]` | Coarse-filtered candidate action space |

### ActionCandidate

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | string | — | Unique action name |
| `type` | string | `"tool_call"` | Action type: `tool_call` / `internal_api` / `user_interaction` / `aggregate` |
| `description` | string | `""` | What this action does |
| `params_schema` | object | `{}` | Expected parameter schema |
| `preconditions` | array[string] | `[]` | Hard preconditions (fact keys that must be confirmed first) |
| `rollbackable` | boolean | `true` | Whether this action can be rolled back |
| `estimated_cost` | string | `"low"` | Rough cost estimate: `low` / `medium` / `high` |
| `metadata` | object | `{}` | Extra business metadata (e.g. `plan_nodes` / `intents` whitelists, `sub_actions`) |
| `applicable_scenarios` | array[string] | `[]` | Scenarios where this action should be used |
| `inapplicable_scenarios` | array[string] | `[]` | Scenarios where this action must NOT be used |
| `required_params` | array[string] | `[]` | Required parameter keys |
| `optional_params` | array[string] | `[]` | Optional parameter keys |
| `cost` | string | `"low"` | Cost estimate: `low` / `medium` / `high` |
| `risk` | string | `"low"` | Risk level: `low` / `medium` / `high` |
| `reversible` | boolean | `true` | Whether the action can be undone |
| `permissions` | array[string] | `[]` | Required permissions or authorization scopes |
| `tags` | array[string] | `[]` | Tags for filtering |
| `intents` | array[string] | `[]` | Intents under which this action is applicable |
| `repeatable_on_retry` | boolean | `false` | Whether the action may recover on retry |
| `alternatives` | array[string] | `[]` | Names of alternative actions that can replace this one |

### ActionRecord

| Field | Type | Default | Description |
|---|---|---|---|
| `action_id` | string | auto | Unique action execution ID (`act-xxxxxxxx`) |
| `name` | string | — | Action name (from the candidate space) |
| `type` | string | `"tool_call"` | Action type |
| `tool_name` | string | `""` | Underlying tool/API name, if any |
| `input` | object | `{}` | Action input parameters |
| `output` | any | `null` | Raw action output |
| `status` | string | `"pending"` | `pending` / `running` / `done` / `failed` |
| `error` | string | `""` | Error message when failed |
| `start_time` | string | auto | Start time (ISO 8601) |
| `end_time` | string \| null | `null` | End time |
| `retry_count` | integer | `0` | Number of retries performed |
| `rollbackable` | boolean | `true` | Whether this action is rollbackable |

### Observation

| Field | Type | Default | Description |
|---|---|---|---|
| `observation_id` | string | auto | Unique observation ID (`obs-xxxxxxxx`) |
| `action_id` | string | `""` | ID of the interpreted action |
| `execution_status` | string | `"success"` | `success` / `partial_success` / `failed` (HTTP 200 != real success) |
| `new_facts` | array[ObservationFact] | `[]` | Newly extracted facts, each bound to evidence |
| `missing_information` | array[string] | `[]` | Information still missing after this action |
| `state_changes` | array[string] | `[]` | Summary of state changes caused by this action |
| `anomalies` | array[string] | `[]` | Detected anomalies or violated assumptions |
| `suggested_next_action` | string | `""` | Suggested next action name (advisory only) |
| `progress` | boolean | `false` | Whether real progress was made |
| `information_gain` | string | `"low"` | `low` / `medium` / `high` |
| `summary` | string | `""` | Short natural-language summary |

### ThinkResult

| Field | Type | Default | Description |
|---|---|---|---|
| `current_goal` | string | `""` | Goal being pursued this round |
| `success_criteria_satisfied` | boolean | `false` | Whether final success criteria are satisfied |
| `current_goal_completed` | boolean | `false` | Whether the current stage goal is completed |
| `facts_sufficient` | boolean | `false` | Whether known facts are sufficient |
| `missing_slots` | array[string] | `[]` | Missing fact slots |
| `unverified_assumptions` | array[string] | `[]` | Assumptions not yet verified |
| `fact_conflicts` | array[string] | `[]` | Detected fact conflicts |
| `selected_action` | string | `""` | Selected action name (from the candidate space) |
| `action_params` | object | `{}` | Action parameters |
| `should_stop` | boolean | `false` | Whether the loop should stop |
| `exit_decision` | string | `"continue"` | `continue` / `finish` / `clarify` / `retry` / `replan` / `interrupt` |
| `reason` | string | `""` | Evidence-based reason (must reference Goal/Context/Constraint) |
| `risk_level` | string | `"low"` | `low` / `medium` / `high` |
| `risk_reason` | string | `""` | Extaoation when risk is not low |

### TAOResult

| Field | Type | Default | Description |
|---|---|---|---|
| `exit_type` | string | — | Final exit type |
| `final_output` | string | `""` | Final output text (when finish) |
| `clarify_message` | string | `""` | Question to the user (when clarify) |
| `exit_reason` | string | `""` | Exit reason detail |
| `used_loops` | integer | `0` | Total loop rounds used |
| `total_actions` | integer | `0` | Total actions executed |
| `exit_history` | array[TAOExitRecord] | `[]` | Exit decision record of every round |
| `state` | TAOState \| null | `null` | Final TAO state snapshot |

---

## 4. Error Handling

The API uses standard HTTP status codes to indicate errors.

### 400 Bad Request

Returned when the input is invalid or a constraint is violated.

```json
{
  "detail": "Constraint modification requires user input as evidence"
}
```

Common causes:
- Missing required fields in the request body
- Invalid enum value
- Constraint modification without user input evidence
- Unsupported backtracking level
- Cross-turn level backtracking without the `contamination` parameter

### 404 Not Found

Returned when the requested resource is not found.

```json
{
  "detail": "Decision node db_choice has no available candidate paths"
}
```

Common causes:
- Decision node ID not found when switching candidate paths
- Fact key not found when updating trust state

### 500 Internal Server Error

Returned when an unexpected server error occurs.

```json
{
  "detail": "Internal server error"
}
```

Common causes:
- LLM service unavailable
- Unexpected runtime exception
