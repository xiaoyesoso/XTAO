# XPlan API 接口调用说明

XPlan 是基于 G4C 方法论（Goal、Context、Choice、Checkpoint、Correction）的 Agent Plan 机制，提供 FastAPI 后端服务。本文档描述所有 REST API 接口的调用方式、请求/响应结构及示例。

---

## 1. 概述

| 项目 | 说明 |
|---|---|
| Base URL | `http://localhost:8000/api` |
| 接口前缀 | 所有接口均位于 `/api` 前缀下 |
| 请求格式 | `Content-Type: application/json` |
| 响应格式 | 所有响应均为 JSON 格式 |
| 字符编码 | UTF-8 |
| 默认端口 | 8000 |

### 接口分类总览

| 分类 | 接口数 | 说明 |
|---|---|---|
| 健康检查与监控 | 2 | 服务健康检查、在线监控指标 |
| Plan 管理 | 8 | **主编排入口**、生成、评估、执行、迭代、Replan、TCC Replan、失败回溯 |
| 约束管理 | 3 | 硬约束、软约束的添加与查询 |
| 可信状态管理 | 5 | 事实条目管理、级联标记、状态报告 |
| 回溯 | 3 | 执行回溯、渐进式回溯、跳跃式回溯 |
| 候选路径 | 3 | 决策节点注册、路径切换、失败路径查询 |
| 评估 | 6 | 离线分析、Replan 事件记录与指标评估 |
| DAG | 1 | DAG 结构验证 |

### 主入口

`POST /api/plan/run` 是**主编排入口**，内部运行完整 G4C 生命周期 —— 生成 → 评估 → 执行 → 纠偏 —— 并在 Checkpoint 失败时编排失败回溯、可信状态、回溯、Replan 与评估。其余接口暴露各子系统供细粒度控制。另提供 Python SDK（见 [SDK_zh.md](SDK_zh.md)），其对应主方法为 `XPlanClient.run_plan()`。

---

## 2. API 接口

### 2.1 健康检查与监控

#### 2.1.1 健康检查

- **方法与路径**：`GET /api/health`
- **描述**：检查服务是否正常运行。

**请求参数**：无

**响应体**：

| 字段 | 类型 | 说明 |
|---|---|---|
| status | string | 服务状态，正常返回 `ok` |
| service | string | 服务名称，固定为 `xplan` |
| version | string | 服务版本号 |

**curl 示例**：

```bash
curl -X GET http://localhost:8000/api/health
```

**响应示例**：

```json
{
  "status": "ok",
  "service": "xplan",
  "version": "0.1.0"
}
```

---

#### 2.1.2 获取监控指标

- **方法与路径**：`GET /api/metrics`
- **描述**：获取在线监控指标，包括 Plan 完成率、步骤成功率、Replan 率等。

**请求参数**：无

**响应体**：

| 字段 | 类型 | 说明 |
|---|---|---|
| plan_completion_rate | float | Plan 完成率 |
| step_success_rate | float | 步骤成功率 |
| replan_rate | float | Replan 触发率 |
| user_correction_rate | float | 用户纠正率 |
| task_success_rate | float | 任务成功率 |
| average_iteration_count | float | 平均迭代次数 |

**curl 示例**：

```bash
curl -X GET http://localhost:8000/api/metrics
```

**响应示例**：

```json
{
  "plan_completion_rate": 0.85,
  "step_success_rate": 0.92,
  "replan_rate": 0.15,
  "user_correction_rate": 0.08,
  "task_success_rate": 0.78,
  "average_iteration_count": 2.3
}
```

---

### 2.2 Plan 管理

#### 2.2.1 主编排入口（运行完整 G4C 生命周期）

- **方法与路径**：`POST /api/plan/run`
- **描述**：**主入口**。内部运行完整 G4C 流水线：生成 → 评估 → 执行 → 纠偏。Checkpoint 失败时编排失败回溯、可信状态标记、渐进式回溯、Replan（或 TCC Replan）与 Replan 事件记录，最终返回最终 Plan 与完整执行轨迹。

该接口在内部调用其他所有接口的底层引擎。如需细粒度控制，请直接使用各细分接口（或 SDK 中对应的方法）。

**请求体**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `user_input` | string | 是 | — | 用户目标或请求 |
| `conversation_history` | string | 否 | `""` | 对话历史，用于补充上下文 |
| `config` | OrchestratorConfig \| null | 否 | `null` | 编排配置，`null` 时使用合理默认值 |

**OrchestratorConfig 字段**：

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `use_iteration` | boolean | `true` | 是否使用 生成-评估-纠偏 迭代循环 |
| `max_iterations` | integer | `3` | 迭代循环最大次数 |
| `verify_before_execute` | boolean | `true` | 执行前是否评估 Plan |
| `verification_threshold` | float | `0.8` | 评估分数阈值（0–1） |
| `enable_failure_tracing` | boolean | `true` | Checkpoint 失败时是否启用失败回溯 |
| `enable_trust_state` | boolean | `true` | 执行期间是否启用可信状态管理 |
| `enable_progressive_backtracking` | boolean | `true` | 失败时是否启用渐进式回溯 |
| `enable_tcc_replan` | boolean | `false` | 是否启用 TCC Replan（高风险场景） |
| `max_replan_count` | integer | `3` | 执行期间最大 Replan 次数 |

**响应体**（OrchestratorResult）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `plan` | Plan | 最终 Plan（若发生 Replan 可能与初始不同） |
| `status` | string | `completed` / `failed` / `aborted` / `clarify_needed` |
| `step_records` | array[StepExecutionRecord] | 每步执行轨迹 |
| `replan_count` | integer | 总 Replan 次数 |
| `iteration_count` | integer | Plan 生成迭代次数 |
| `verification_score` | float \| null | Plan 评估分数（0–1） |
| `verification_passed` | boolean \| null | 评估是否通过阈值 |
| `errors` | array[string] | 执行期间遇到的错误 |
| `clarify_message` | string \| null | 当 `status == "clarify_needed"` 时的澄清消息 |

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/plan/run \
  -H "Content-Type: application/json" \
  -d '{
    "user_input": "设计一个支持 10000 QPS 的高并发订单系统",
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

**响应示例**：

```json
{
  "plan": { "goal": { "user_goal": "..." }, "status": "completed" },
  "status": "completed",
  "step_records": [
    {
      "step_id": "s1",
      "step_objective": "收集非功能需求",
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

#### 2.2.2 生成 G4C Plan

- **方法与路径**：`POST /api/plan/generate`
- **描述**：生成 G4C Plan。支持普通生成和迭代式生成（生成-评估-纠正循环）。

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| user_input | string | 是 | 用户输入 |
| conversation_history | string | 否 | 对话历史，默认为空字符串 |
| use_iteration | boolean | 否 | 是否使用迭代式生成，默认为 `false` |

**响应体**（普通模式）：

| 字段 | 类型 | 说明 |
|---|---|---|
| plan | Plan | 生成的 G4C Plan 对象 |

**响应体**（迭代模式，`use_iteration=true`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| plan | Plan | 生成的 G4C Plan 对象 |
| verification_results | list | 每轮迭代验证结果列表 |
| iterations | integer | 迭代轮数 |

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/plan/generate \
  -H "Content-Type: application/json" \
  -d '{
    "user_input": "帮我设计一个支持千万级 QPS 的电商商品搜索系统",
    "conversation_history": "",
    "use_iteration": false
  }'
```

**响应示例**（普通模式）：

```json
{
  "plan": {
    "goal": {
      "user_goal": "设计一个支持千万级 QPS 的电商商品搜索系统",
      "success_criteria": [
        "系统峰值 QPS 不低于 10000000",
        "搜索延迟 P99 低于 100ms",
        "数据更新延迟不超过 5 秒"
      ],
      "adjective_standards": {
        "高性能": "QPS >= 10000000 且 P99 延迟 < 100ms",
        "高可用": "可用性 >= 99.99%"
      }
    },
    "context": {
      "known_facts": [
        "目标用户规模为 5 亿",
        "商品总量约 10 亿 SKU"
      ],
      "missing_info": [
        "现有基础设施规格",
        "预算限制"
      ],
      "constraints": {
        "hard": ["必须使用开源技术栈"],
        "soft": ["优先使用团队熟悉的技术"]
      }
    },
    "choice": {
      "selected_path": "基于 Elasticsearch + Redis 缓存的搜索架构",
      "reason": "已知事实显示商品总量约 10 亿 SKU，Elasticsearch 支持水平扩展可满足 QPS 需求",
      "candidate_paths": [
        "基于 Elasticsearch + Redis 缓存的搜索架构",
        "基于 MongoDB 的全文索引方案"
      ],
      "steps": [
        {
          "id": "step_1",
          "objective": "完成容量评估与索引分片设计",
          "reason": "需要根据商品总量确定分片数",
          "status": "pending"
        },
        {
          "id": "step_2",
          "objective": "搭建 Elasticsearch 集群并完成数据导入",
          "reason": "分片设计完成后即可部署集群",
          "status": "pending"
        }
      ]
    },
    "checkpoint": [
      {
        "step_id": "step_1",
        "checks": [
          "分片数是否满足 QPS 需求",
          "单分片数据量是否在合理范围"
        ]
      }
    ],
    "correction": [
      {
        "condition": "集群搭建失败",
        "action": {
          "type": "retry",
          "retry_granularity": "step",
          "target_step_id": "step_2",
          "params": {},
          "message": "重试集群搭建步骤"
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

#### 2.2.2 评估 Plan 质量

- **方法与路径**：`POST /api/plan/verify`
- **描述**：从 G4C 五个维度评估 Plan 质量。

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| plan | Plan | 是 | 待评估的 Plan 对象 |

**响应体**：

| 字段 | 类型 | 说明 |
|---|---|---|
| verification | object | G4C 五维度验证结果 |

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/plan/verify \
  -H "Content-Type: application/json" \
  -d '{
    "plan": {
      "goal": {
        "user_goal": "设计搜索系统",
        "success_criteria": ["QPS >= 1000"],
        "adjective_standards": {}
      },
      "choice": {
        "selected_path": "Elasticsearch 方案",
        "reason": "满足搜索需求",
        "candidate_paths": [],
        "steps": []
      }
    }
  }'
```

**响应示例**：

```json
{
  "verification": {
    "goal_score": 0.9,
    "context_score": 0.8,
    "choice_score": 0.85,
    "checkpoint_score": 0.7,
    "correction_score": 0.6,
    "overall_score": 0.77,
    "suggestions": [
      "建议补充更多 Checkpoint 覆盖关键步骤",
      "建议增加针对工具失败的 Correction 规则"
    ]
  }
}
```

---

#### 2.2.3 执行 Plan

- **方法与路径**：`POST /api/plan/execute`
- **描述**：执行 Plan，逐步执行并触发 Checkpoint 检查。

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| plan | Plan | 是 | 待执行的 Plan 对象 |

**响应体**：

| 字段 | 类型 | 说明 |
|---|---|---|
| plan | Plan | 执行后的 Plan 对象（含状态更新和检查结果） |

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/plan/execute \
  -H "Content-Type: application/json" \
  -d '{
    "plan": {
      "goal": {
        "user_goal": "完成容量评估",
        "success_criteria": ["产出容量评估报告"],
        "adjective_standards": {}
      },
      "choice": {
        "selected_path": "基于历史数据进行推算",
        "reason": "历史数据可用",
        "candidate_paths": [],
        "steps": [
          {
            "id": "step_1",
            "objective": "收集历史 QPS 数据",
            "reason": "需要基础数据进行推算",
            "status": "pending"
          }
        ]
      },
      "checkpoint": [
        {
          "step_id": "step_1",
          "checks": ["数据时间范围是否覆盖峰值时段"]
        }
      ]
    }
  }'
```

**响应示例**：

```json
{
  "plan": {
    "goal": {
      "user_goal": "完成容量评估",
      "success_criteria": ["产出容量评估报告"],
      "adjective_standards": {}
    },
    "context": {
      "known_facts": [],
      "missing_info": [],
      "constraints": {
        "hard": [],
        "soft": []
      }
    },
    "choice": {
      "selected_path": "基于历史数据进行推算",
      "reason": "历史数据可用",
      "candidate_paths": [],
      "steps": [
        {
          "id": "step_1",
          "objective": "收集历史 QPS 数据",
          "reason": "需要基础数据进行推算",
          "status": "done"
        }
      ]
    },
    "checkpoint": [
      {
        "step_id": "step_1",
        "checks": ["数据时间范围是否覆盖峰值时段"]
      }
    ],
    "correction": [],
    "mode": "linear",
    "status": "completed",
    "dag": null,
    "check_results": [
      {
        "step_id": "step_1",
        "check_point": "数据时间范围是否覆盖峰值时段",
        "passed": true,
        "result": "数据覆盖了过去 30 天的峰值时段",
        "evidences": [
          {
            "description": "数据时间范围 2026-06-26 至 2026-07-26",
            "source": "监控系统"
          }
        ]
      }
    ],
    "current_step_index": 1,
    "iteration_count": 0
  }
}
```

---

#### 2.2.4 迭代式 Plan 生成

- **方法与路径**：`POST /api/plan/iterate`
- **描述**：迭代式 Plan 生成，执行生成-评估-纠正循环，直到 Plan 质量达标或达到最大迭代次数。

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| user_input | string | 是 | 用户输入 |
| conversation_history | string | 否 | 对话历史，默认为空字符串 |

**响应体**：

| 字段 | 类型 | 说明 |
|---|---|---|
| plan | Plan | 最终生成的 Plan 对象 |
| verification_results | list | 每轮迭代的验证结果列表 |
| iterations | integer | 迭代轮数 |

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/plan/iterate \
  -H "Content-Type: application/json" \
  -d '{
    "user_input": "设计一个微服务架构的订单系统",
    "conversation_history": "用户之前讨论过需要支持分布式事务"
  }'
```

**响应示例**：

```json
{
  "plan": {
    "goal": {
      "user_goal": "设计一个微服务架构的订单系统",
      "success_criteria": ["支持分布式事务", "订单创建 TPS >= 5000"],
      "adjective_standards": {}
    },
    "context": {
      "known_facts": ["需要支持分布式事务"],
      "missing_info": [],
      "constraints": {
        "hard": [],
        "soft": []
      }
    },
    "choice": {
      "selected_path": "基于 Saga 模式的微服务架构",
      "reason": "用户已明确需要分布式事务支持，Saga 适合长事务场景",
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
    "iteration_count": 3
  },
  "verification_results": [
    {"overall_score": 0.6},
    {"overall_score": 0.75},
    {"overall_score": 0.88}
  ],
  "iterations": 3
}
```

---

#### 2.2.5 触发 Replan

- **方法与路径**：`POST /api/plan/replan`
- **描述**：触发受控纠偏机制。执行过程中，基于新的 Goal、Context、Choice、Checkpoint 结果，对原计划进行受控修正。完整流程：检测触发 -> 代码判断 -> LLM 判断 -> 执行 Replan。

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| plan | Plan | 是 | 当前 Plan |
| error_info | string | 否 | 错误信息描述 |
| user_input | string | 否 | 用户补充输入 |
| conversation_history | string | 否 | 对话历史，用于补充上下文 |

**响应体**：

| 字段 | 类型 | 说明 |
|---|---|---|
| plan | Plan | Replan 后的新 Plan（或原 Plan） |
| replan_result | ReplanResult \| null | Replan 执行结果详情 |

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/plan/replan \
  -H "Content-Type: application/json" \
  -d '{
    "plan": {
      "goal": {
        "user_goal": "部署搜索服务",
        "success_criteria": ["服务可访问"],
        "adjective_standards": {}
      },
      "choice": {
        "selected_path": "使用 Elasticsearch 7.x",
        "reason": "版本稳定",
        "candidate_paths": [],
        "steps": [
          {"id": "step_1", "objective": "下载安装包", "reason": "", "status": "done"},
          {"id": "step_2", "objective": "启动服务", "reason": "", "status": "failed"}
        ]
      }
    },
    "error_info": "Elasticsearch 7.x 与当前 JDK 版本不兼容",
    "user_input": "",
    "conversation_history": ""
  }'
```

**响应示例**：

```json
{
  "plan": {
    "goal": {
      "user_goal": "部署搜索服务",
      "success_criteria": ["服务可访问"],
      "adjective_standards": {}
    },
    "context": {
      "known_facts": ["JDK 版本与 ES 7.x 不兼容"],
      "missing_info": [],
      "constraints": {
        "hard": [],
        "soft": []
      }
    },
    "choice": {
      "selected_path": "使用 Elasticsearch 8.x（兼容当前 JDK）",
      "reason": "检测到 JDK 不兼容问题，ES 8.x 兼容当前环境",
      "candidate_paths": [],
      "steps": [
        {"id": "step_1", "objective": "下载 ES 8.x 安装包", "reason": "", "status": "pending"},
        {"id": "step_2", "objective": "启动服务", "reason": "", "status": "pending"}
      ]
    },
    "checkpoint": [],
    "correction": [],
    "mode": "linear",
    "status": "draft",
    "dag": null,
    "check_results": [],
    "current_step_index": 0,
    "iteration_count": 0
  },
  "replan_result": {
    "retained_steps": [],
    "modified_steps": [
      {
        "step_id": "step_1",
        "reason": "版本变更，需重新下载 ES 8.x",
        "change_type": "modified",
        "modification_detail": "下载目标从 ES 7.x 改为 ES 8.x"
      }
    ],
    "removed_steps": [],
    "new_plan": null,
    "replan_info": {
      "max_replan_total": 3,
      "used_replan_total": 1
    }
  }
}
```

---

#### 2.2.6 TCC Replan

- **方法与路径**：`POST /api/plan/tcc-replan`
- **描述**：执行 TCC Replan（Try/Confirm/Cancel 三步法）。借鉴分布式事务 TCC 概念，仅适用于高失败成本、高外部依赖、高副作用风险的场景。

  - **Try**：最小化验证新 Plan 最薄弱点（dry-run，低副作用）
  - **Confirm**：Try 全部通过后执行 Plan，复用 Try 产生的数据
  - **Cancel**：Try 失败后回滚临时状态，标记失败假设

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| plan | Plan | 是 | 待验证的新 Plan |
| conversation_history | string | 否 | 对话历史，用于补充上下文 |

**响应体**：

| 字段 | 类型 | 说明 |
|---|---|---|
| result | TCCResult | TCC Replan 完整结果 |

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/plan/tcc-replan \
  -H "Content-Type: application/json" \
  -d '{
    "plan": {
      "goal": {
        "user_goal": "迁移数据库到新集群",
        "success_criteria": ["数据完整迁移", "服务零停机"],
        "adjective_standards": {}
      },
      "choice": {
        "selected_path": "双写迁移方案",
        "reason": "需要零停机迁移",
        "candidate_paths": [],
        "steps": [
          {"id": "step_1", "objective": "验证新集群连通性", "reason": "", "status": "pending"},
          {"id": "step_2", "objective": "开启双写", "reason": "", "status": "pending"}
        ]
      }
    },
    "conversation_history": ""
  }'
```

**响应示例**（Try 阶段全部通过，进入 Confirm）：

```json
{
  "result": {
    "phase": "confirm",
    "try_result": {
      "validations": [
        {
          "target_step_id": "step_1",
          "validation_type": "tool_availability",
          "passed": true,
          "result": "新集群连接正常",
          "evidence": "dry-run 连接测试成功"
        },
        {
          "target_step_id": "step_2",
          "validation_type": "data_accessibility",
          "passed": true,
          "result": "双写接口可用",
          "evidence": "接口 dry-run 返回 200"
        }
      ],
      "all_passed": true,
      "temp_data": {
        "new_cluster_connection": "established"
      },
      "failed_assumptions": [],
      "unavailable_tools": []
    },
    "confirm_result": {
      "executed": true,
      "try_results_written": true,
      "reused_try_data": true,
      "execution_summary": "Plan 执行完成，复用了 Try 阶段的连接信息"
    },
    "cancel_result": null,
    "new_plan": null
  }
}
```

**响应示例**（Try 阶段失败，进入 Cancel）：

```json
{
  "result": {
    "phase": "cancel",
    "try_result": {
      "validations": [
        {
          "target_step_id": "step_1",
          "validation_type": "tool_availability",
          "passed": false,
          "result": "新集群无法连接",
          "evidence": "dry-run 连接超时"
        }
      ],
      "all_passed": false,
      "temp_data": {},
      "failed_assumptions": ["新集群已就绪"],
      "unavailable_tools": ["new_db_cluster"]
    },
    "confirm_result": null,
    "cancel_result": {
      "temp_data_cleaned": true,
      "failed_assumptions_marked": ["新集群已就绪"],
      "unavailable_tools_marked": ["new_db_cluster"],
      "should_continue_replan": true,
      "has_alternative_solutions": true,
      "abort_reason": null
    },
    "new_plan": null
  }
}
```

---

#### 2.2.7 失败回溯

- **方法与路径**：`POST /api/plan/trace`
- **描述**：触发失败回溯与根因定位。核心概念：失败点 ≠ 根因点。从失败点开始反向追溯，找到根因点，并提供回滚点和 Replan 起点建议。

  完整流程：
  1. 代码构建反向追溯链（build_tracing_chain）
  2. 代码查找最近 Checkpoint（find_nearest_checkpoint）
  3. 代码检查循环依赖（check_circular_dependency）
  4. LLM 进行语义根因定位（llm_trace_root_cause）
  5. 合并代码与 LLM 结果，返回 FailureTracingResult

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| plan | Plan | 是 | 当前 Plan |
| failure_step_id | string | 是 | 失败步骤 ID |
| failure_info | string | 否 | 失败信息描述 |
| step_records | list[StepRecord] | 否 | 步骤执行记录列表 |

**响应体**：

| 字段 | 类型 | 说明 |
|---|---|---|
| result | FailureTracingResult | 失败回溯结果 |

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/plan/trace \
  -H "Content-Type: application/json" \
  -d '{
    "plan": {
      "goal": {
        "user_goal": "生成数据分析报告",
        "success_criteria": ["报告输出完整"],
        "adjective_standards": {}
      },
      "choice": {
        "selected_path": "SQL 查询 + 图表生成",
        "reason": "数据在数据库中",
        "candidate_paths": [],
        "steps": [
          {"id": "step_1", "objective": "查询用户数据", "reason": "", "status": "done"},
          {"id": "step_2", "objective": "计算指标", "reason": "", "status": "done"},
          {"id": "step_3", "objective": "生成图表", "reason": "", "status": "failed"}
        ]
      }
    },
    "failure_step_id": "step_3",
    "failure_info": "图表生成报错：除零错误",
    "step_records": [
      {
        "step_id": "step_1",
        "input": {"table": "users"},
        "output": {"count": 0},
        "context_used": [],
        "facts_used": [],
        "assumptions": ["users 表有数据"],
        "tool_name": "sql_query",
        "tool_input": {"query": "SELECT count(*) FROM users"},
        "tool_output": {"count": 0},
        "checkpoint_result": null,
        "snapshot": {},
        "timestamp": "2026-07-26T10:00:00Z"
      },
      {
        "step_id": "step_2",
        "input": {"count": 0},
        "output": {"ratio": null},
        "context_used": [],
        "facts_used": [],
        "assumptions": ["count > 0"],
        "tool_name": "calculator",
        "tool_input": {"operation": "divide"},
        "tool_output": {"error": "除零"},
        "checkpoint_result": null,
        "snapshot": {},
        "timestamp": "2026-07-26T10:01:00Z"
      }
    ]
  }'
```

**响应示例**：

```json
{
  "result": {
    "failure_point": {
      "step_id": "step_3",
      "reason": "图表生成时除零错误",
      "checkpoint_id": null,
      "action": "generate_chart",
      "error": "ZeroDivisionError"
    },
    "root_cause_point": {
      "step_id": "step_1",
      "reason": "users 表查询结果为 0，导致后续计算除零",
      "checkpoint_id": null,
      "action": "",
      "error": ""
    },
    "rollback_point": {
      "step_id": "step_2",
      "reason": "回滚到指标计算步骤，补充空数据处理逻辑",
      "checkpoint_id": null,
      "action": "",
      "error": ""
    },
    "replan_start_point": {
      "step_id": "step_2",
      "reason": "从指标计算开始重新规划，增加空值检查",
      "checkpoint_id": null,
      "action": "",
      "error": ""
    },
    "tracing_chain": [
      {
        "step_id": "step_3",
        "reason": "失败点：除零错误",
        "checkpoint_id": null,
        "action": "generate_chart",
        "error": "ZeroDivisionError"
      },
      {
        "step_id": "step_2",
        "reason": "传递了 null 值给图表生成",
        "checkpoint_id": null,
        "action": "",
        "error": ""
      },
      {
        "step_id": "step_1",
        "reason": "根因：查询结果为 0，未做空值处理",
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

### 2.3 约束管理

#### 2.3.1 添加硬约束

- **方法与路径**：`POST /api/constraints/hard`
- **描述**：添加硬约束。硬约束不可违反，违反时必须阻断执行。约束修改需要用户输入作为证据，Agent 不能自主修改约束。

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| constraint | string | 是 | 约束内容 |
| user_input | string | 是 | 用户输入（作为约束修改的证据） |

**响应体**：

| 字段 | 类型 | 说明 |
|---|---|---|
| success | boolean | 是否添加成功 |
| constraints | list[string] | 当前所有硬约束列表 |

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/constraints/hard \
  -H "Content-Type: application/json" \
  -d '{
    "constraint": "必须使用国产化技术栈",
    "user_input": "由于合规要求，系统必须使用国产化技术栈"
  }'
```

**响应示例**：

```json
{
  "success": true,
  "constraints": [
    "必须使用国产化技术栈"
  ]
}
```

---

#### 2.3.2 添加软约束

- **方法与路径**：`POST /api/constraints/soft`
- **描述**：添加软约束。软约束应当被满足，违反时记录但允许继续执行。

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| constraint | string | 是 | 约束内容 |
| user_input | string | 是 | 用户输入（作为约束修改的证据） |

**响应体**：

| 字段 | 类型 | 说明 |
|---|---|---|
| success | boolean | 是否添加成功 |
| constraints | list[string] | 当前所有软约束列表 |

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/constraints/soft \
  -H "Content-Type: application/json" \
  -d '{
    "constraint": "优先使用团队熟悉的 Python 技术栈",
    "user_input": "团队 Python 经验丰富，优先使用"
  }'
```

**响应示例**：

```json
{
  "success": true,
  "constraints": [
    "优先使用团队熟悉的 Python 技术栈"
  ]
}
```

---

#### 2.3.3 获取所有约束

- **方法与路径**：`GET /api/constraints`
- **描述**：获取所有约束列表（含硬约束和软约束）。

**请求参数**：无

**响应体**：

| 字段 | 类型 | 说明 |
|---|---|---|
| hard | list[string] | 硬约束列表 |
| soft | list[string] | 软约束列表 |

**curl 示例**：

```bash
curl -X GET http://localhost:8000/api/constraints
```

**响应示例**：

```json
{
  "hard": [
    "必须使用国产化技术栈"
  ],
  "soft": [
    "优先使用团队熟悉的 Python 技术栈"
  ]
}
```

---

### 2.4 可信状态管理

#### 2.4.1 添加事实条目

- **方法与路径**：`POST /api/trust-state/facts`
- **描述**：添加事实条目（默认状态为 AVAILABLE）。为中间结果标记可信状态，支持证据来源和依赖关系记录。

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| key | string | 是 | 事实键名，例如 highest_qps |
| value | object | 是 | 事实值 |
| evidence | string | 否 | 证据来源 |
| source_step_id | string | 否 | 产生该事实的步骤 ID |
| depends_on | list[string] | 否 | 依赖的其他事实键名列表 |

**响应体**：

| 字段 | 类型 | 说明 |
|---|---|---|
| success | boolean | 是否添加成功 |
| fact | FactEntry | 添加的事实条目 |

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/trust-state/facts \
  -H "Content-Type: application/json" \
  -d '{
    "key": "highest_qps",
    "value": 8500000,
    "evidence": "来自监控平台 2026-07 大促数据",
    "source_step_id": "step_1",
    "depends_on": []
  }'
```

**响应示例**：

```json
{
  "success": true,
  "fact": {
    "key": "highest_qps",
    "value": 8500000,
    "trust_state": "available",
    "evidence": "来自监控平台 2026-07 大促数据",
    "source_step_id": "step_1",
    "depends_on": []
  }
}
```

---

#### 2.4.2 获取所有事实

- **方法与路径**：`GET /api/trust-state/facts`
- **描述**：获取所有事实条目。

**请求参数**：无

**响应体**：

| 字段 | 类型 | 说明 |
|---|---|---|
| facts | list[FactEntry] | 所有事实条目列表 |

**curl 示例**：

```bash
curl -X GET http://localhost:8000/api/trust-state/facts
```

**响应示例**：

```json
{
  "facts": [
    {
      "key": "highest_qps",
      "value": 8500000,
      "trust_state": "available",
      "evidence": "来自监控平台 2026-07 大促数据",
      "source_step_id": "step_1",
      "depends_on": []
    },
    {
      "key": "peak_concurrency",
      "value": 1200000,
      "trust_state": "verified",
      "evidence": "已通过压测验证",
      "source_step_id": "step_2",
      "depends_on": ["highest_qps"]
    }
  ]
}
```

---

#### 2.4.3 更新可信状态

- **方法与路径**：`POST /api/trust-state/update`
- **描述**：更新事实的可信状态。如果新状态为 INVALID，自动触发级联标记：所有依赖该事实的事实将被标记为 DIRTY（BFS 遍历依赖链）。返回所有变更记录（含级联标记）。

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| key | string | 是 | 事实键名 |
| new_state | TrustState | 是 | 新的可信状态 |
| reason | string | 否 | 变更原因 |

**响应体**：

| 字段 | 类型 | 说明 |
|---|---|---|
| success | boolean | 是否更新成功 |
| changes | list[TrustStateChange] | 状态变更记录列表（含级联标记） |

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/trust-state/update \
  -H "Content-Type: application/json" \
  -d '{
    "key": "highest_qps",
    "new_state": "invalid",
    "reason": "发现原始监控数据存在采集异常，该数据不可信"
  }'
```

**响应示例**：

```json
{
  "success": true,
  "changes": [
    {
      "key": "highest_qps",
      "old_state": "available",
      "new_state": "invalid",
      "reason": "发现原始监控数据存在采集异常，该数据不可信",
      "cascaded": false
    },
    {
      "key": "peak_concurrency",
      "old_state": "verified",
      "new_state": "dirty",
      "reason": "依赖的 highest_qps 已被标记为 INVALID，级联标记为 DIRTY",
      "cascaded": true
    }
  ]
}
```

---

#### 2.4.4 获取可信状态报告

- **方法与路径**：`GET /api/trust-state/report`
- **描述**：获取可信状态报告，包含各状态的计数统计。

**请求参数**：无

**响应体**：

| 字段 | 类型 | 说明 |
|---|---|---|
| facts | list[FactEntry] | 所有事实条目 |
| changes | list[TrustStateChange] | 状态变更记录 |
| verified_count | int | 已验证（VERIFIED）数量 |
| available_count | int | 可用（AVAILABLE）数量 |
| suspicious_count | int | 可疑（SUSPICIOUS）数量 |
| invalid_count | int | 无效（INVALID）数量 |
| dirty_count | int | 受污染（DIRTY）数量 |

**curl 示例**：

```bash
curl -X GET http://localhost:8000/api/trust-state/report
```

**响应示例**：

```json
{
  "facts": [
    {
      "key": "highest_qps",
      "value": 8500000,
      "trust_state": "invalid",
      "evidence": "来自监控平台 2026-07 大促数据",
      "source_step_id": "step_1",
      "depends_on": []
    },
    {
      "key": "peak_concurrency",
      "value": 1200000,
      "trust_state": "dirty",
      "evidence": "已通过压测验证",
      "source_step_id": "step_2",
      "depends_on": ["highest_qps"]
    },
    {
      "key": "avg_latency",
      "value": 45,
      "trust_state": "verified",
      "evidence": "APM 系统核实",
      "source_step_id": "step_3",
      "depends_on": []
    }
  ],
  "changes": [
    {
      "key": "highest_qps",
      "old_state": "available",
      "new_state": "invalid",
      "reason": "数据采集异常",
      "cascaded": false
    }
  ],
  "verified_count": 1,
  "available_count": 0,
  "suspicious_count": 0,
  "invalid_count": 1,
  "dirty_count": 1
}
```

---

#### 2.4.5 获取需优先检查的事实

- **方法与路径**：`GET /api/trust-state/suspicious`
- **描述**：获取 SUSPICIOUS 和 DIRTY 状态的事实，这些事实需要优先检查。回溯定位根因时，优先检查这些事实（跳过 VERIFIED）。

**请求参数**：无

**响应体**：

| 字段 | 类型 | 说明 |
|---|---|---|
| facts | list[FactEntry] | 需优先检查的事实列表 |

**curl 示例**：

```bash
curl -X GET http://localhost:8000/api/trust-state/suspicious
```

**响应示例**：

```json
{
  "facts": [
    {
      "key": "highest_qps",
      "value": 8500000,
      "trust_state": "invalid",
      "evidence": "来自监控平台 2026-07 大促数据",
      "source_step_id": "step_1",
      "depends_on": []
    },
    {
      "key": "peak_concurrency",
      "value": 1200000,
      "trust_state": "dirty",
      "evidence": "已通过压测验证",
      "source_step_id": "step_2",
      "depends_on": ["highest_qps"]
    }
  ]
}
```

---

### 2.5 回溯

#### 2.5.1 执行回溯

- **方法与路径**：`POST /api/backtracking/execute`
- **描述**：根据指定的回溯级别执行回溯；未指定级别时自动判断。支持五种回溯级别：ACTION / STEP / STAGE / GLOBAL / CROSS_TURN。

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| plan | Plan | 是 | 当前 Plan |
| error_info | string | 否 | 错误信息描述 |
| level | BacktrackingLevel \| null | 否 | 回溯级别，为 null 时自动判断 |
| failure_tracing_result | object \| null | 否 | 失败回溯结果 |
| step_id | string | 否 | 失败步骤 ID（ACTION/STEP 级别使用） |
| decision_id | string | 否 | 决策节点 ID（STEP 级别使用） |
| stage_checkpoint_id | string | 否 | 阶段 Checkpoint ID（STAGE 级别使用） |
| contamination | CrossTurnContamination \| null | 否 | 跨轮次污染记录（CROSS_TURN 级别使用） |

**响应体**：

| 字段 | 类型 | 说明 |
|---|---|---|
| result | BacktrackingResult | 回溯结果 |
| level | BacktrackingLevel | 实际执行的回溯级别 |

**curl 示例**（指定 STEP 级别）：

```bash
curl -X POST http://localhost:8000/api/backtracking/execute \
  -H "Content-Type: application/json" \
  -d '{
    "plan": {
      "goal": {
        "user_goal": "数据迁移",
        "success_criteria": ["迁移完成"],
        "adjective_standards": {}
      },
      "choice": {
        "selected_path": "直接全量迁移",
        "reason": "数据量小",
        "candidate_paths": [],
        "steps": [
          {"id": "step_1", "objective": "导出数据", "reason": "", "status": "done"},
          {"id": "step_2", "objective": "导入数据", "reason": "", "status": "failed"}
        ]
      }
    },
    "error_info": "导入工具连接超时",
    "level": "step",
    "step_id": "step_2",
    "decision_id": "step_2"
  }'
```

**响应示例**：

```json
{
  "result": {
    "level": "step",
    "success": true,
    "rollback_to": "step_2",
    "new_plan_steps": [
      {"id": "step_2", "objective": "使用备用导入工具导入数据", "status": "pending"}
    ],
    "reused_results": ["step_1 导出的数据文件"],
    "expanded": false,
    "next_level": null
  },
  "level": "step"
}
```

**curl 示例**（CROSS_TURN 级别）：

```bash
curl -X POST http://localhost:8000/api/backtracking/execute \
  -H "Content-Type: application/json" \
  -d '{
    "plan": {
      "goal": {
        "user_goal": "用户画像分析",
        "success_criteria": ["输出画像报告"],
        "adjective_standards": {}
      },
      "choice": {
        "selected_path": "基于历史数据聚类",
        "reason": "有历史数据",
        "candidate_paths": [],
        "steps": []
      }
    },
    "error_info": "发现历史数据中存在错误事实污染",
    "level": "cross_turn",
    "contamination": {
      "error_fact_key": "user_preference",
      "introduced_turn": 5,
      "affected_results": ["turn_5_cluster_result", "turn_6_summary"],
      "affected_summaries": ["用户偏好摘要 v3"],
      "affected_user_profile": ["preference_tags"],
      "affected_fact_table": ["user_preference"]
    }
  }'
```

---

#### 2.5.2 渐进式扩大回溯

- **方法与路径**：`POST /api/backtracking/progressive`
- **描述**：渐进式扩大回溯范围：ACTION -> STEP -> STAGE -> GLOBAL，每次扩大前通过 TCC 判断新计划可行性。

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| plan | Plan | 是 | 当前 Plan |
| error_info | string | 否 | 错误信息描述 |
| failure_tracing_result | object \| null | 否 | 失败回溯结果 |

**响应体**：

| 字段 | 类型 | 说明 |
|---|---|---|
| result | BacktrackingResult | 回溯结果（含是否扩大及下一级别信息） |

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/backtracking/progressive \
  -H "Content-Type: application/json" \
  -d '{
    "plan": {
      "goal": {
        "user_goal": "部署应用",
        "success_criteria": ["应用可访问"],
        "adjective_standards": {}
      },
      "choice": {
        "selected_path": "K8s 部署",
        "reason": "环境支持",
        "candidate_paths": [],
        "steps": [
          {"id": "step_1", "objective": "构建镜像", "reason": "", "status": "done"},
          {"id": "step_2", "objective": "部署到 K8s", "reason": "", "status": "failed"}
        ]
      }
    },
    "error_info": "K8s 集群资源不足"
  }'
```

**响应示例**：

```json
{
  "result": {
    "level": "stage",
    "success": true,
    "rollback_to": "step_1",
    "new_plan_steps": [
      {"id": "step_1", "objective": "构建镜像并申请更多资源", "status": "pending"},
      {"id": "step_2", "objective": "部署到 K8s", "status": "pending"}
    ],
    "reused_results": ["step_1 的镜像构建产物"],
    "expanded": true,
    "next_level": "global"
  }
}
```

---

#### 2.5.3 跳跃式快速回溯

- **方法与路径**：`POST /api/backtracking/jump`
- **描述**：通过预定义规则匹配错误模式，直接定位回溯位置，跳过渐进扩大的开销。

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| error_pattern | string | 是 | 错误模式描述 |
| jump_rules | list[JumpRule] \| null | 否 | 跳跃回溯规则列表，为 null 时使用默认规则 |

**响应体**：

| 字段 | 类型 | 说明 |
|---|---|---|
| result | BacktrackingResult \| null | 回溯结果，未匹配时为 null |
| matched | boolean | 是否匹配到规则 |

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/backtracking/jump \
  -H "Content-Type: application/json" \
  -d '{
    "error_pattern": "数据库连接超时",
    "jump_rules": [
      {
        "error_pattern": "数据库连接超时",
        "rollback_position": "step_db_init",
        "new_plan_template": "增加连接池配置和重试机制",
        "similarity_threshold": 0.8
      }
    ]
  }'
```

**响应示例**（匹配成功）：

```json
{
  "result": {
    "level": "stage",
    "success": true,
    "rollback_to": "step_db_init",
    "new_plan_steps": [
      {"id": "step_db_init", "objective": "增加连接池配置和重试机制", "status": "pending"}
    ],
    "reused_results": [],
    "expanded": false,
    "next_level": null
  },
  "matched": true
}
```

**响应示例**（未匹配）：

```json
{
  "result": null,
  "matched": false
}
```

---

### 2.6 候选路径

#### 2.6.1 注册决策节点

- **方法与路径**：`POST /api/candidate-paths/register`
- **描述**：注册决策节点，记录决策节点的已选路径和候选路径列表，支持后续路径切换。

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| decision_id | string | 是 | 决策节点 ID |
| selected | string | 是 | 当前选择的路径 |
| candidates | list[CandidatePath] | 否 | 候选路径列表 |

**响应体**：

| 字段 | 类型 | 说明 |
|---|---|---|
| success | boolean | 是否注册成功 |
| decision_id | string | 决策节点 ID |
| selected | string | 当前选择的路径 |
| candidate_count | int | 候选路径数量 |

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/candidate-paths/register \
  -H "Content-Type: application/json" \
  -d '{
    "decision_id": "decision_db_choice",
    "selected": "mysql",
    "candidates": [
      {
        "path": "mysql",
        "status": "available",
        "reason": "",
        "failure_id": ""
      },
      {
        "path": "postgresql",
        "status": "available",
        "reason": "",
        "failure_id": ""
      },
      {
        "path": "tidb",
        "status": "available",
        "reason": "",
        "failure_id": ""
      }
    ]
  }'
```

**响应示例**：

```json
{
  "success": true,
  "decision_id": "decision_db_choice",
  "selected": "mysql",
  "candidate_count": 3
}
```

---

#### 2.6.2 快速路径切换

- **方法与路径**：`POST /api/candidate-paths/switch/{decision_id}`
- **描述**：获取决策节点的下一个可用候选路径并切换到该路径。

**路径参数**：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| decision_id | string | 是 | 决策节点 ID |

**响应体**：

| 字段 | 类型 | 说明 |
|---|---|---|
| success | boolean | 是否切换成功 |
| new_path | string | 切换后的新路径名称 |

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/candidate-paths/switch/decision_db_choice
```

**响应示例**：

```json
{
  "success": true,
  "new_path": "postgresql"
}
```

---

#### 2.6.3 获取失败路径记录

- **方法与路径**：`GET /api/candidate-paths/failed`
- **描述**：获取所有失败路径记录，包含失败原因和恢复状态。

**请求参数**：无

**响应体**：

| 字段 | 类型 | 说明 |
|---|---|---|
| failed_paths | list[FailurePathRecord] | 失败路径记录列表 |

**curl 示例**：

```bash
curl -X GET http://localhost:8000/api/candidate-paths/failed
```

**响应示例**：

```json
{
  "failed_paths": [
    {
      "path": "mysql",
      "failure_reason": "并发连接数超过限制",
      "failure_turn": 3,
      "recovered": false,
      "recovery_checked_at": ""
    },
    {
      "path": "redis_single",
      "failure_reason": "单节点内存不足",
      "failure_turn": 5,
      "recovered": true,
      "recovery_checked_at": "2026-07-26T10:30:00Z"
    }
  ]
}
```

---

### 2.7 评估

#### 2.7.1 离线 Plan 分析

- **方法与路径**：`POST /api/evaluation/offline`
- **描述**：离线分析 Plan 质量（围绕 G4C 五个维度）。

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| plan | Plan | 是 | 待分析的 Plan 对象 |

**响应体**：

| 字段 | 类型 | 说明 |
|---|---|---|
| analysis | object | G4C 五维度分析结果 |

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/evaluation/offline \
  -H "Content-Type: application/json" \
  -d '{
    "plan": {
      "goal": {
        "user_goal": "优化数据库查询性能",
        "success_criteria": ["查询延迟降低 50%"],
        "adjective_standards": {}
      },
      "choice": {
        "selected_path": "添加索引",
        "reason": "通过 EXPLAIN 发现全表扫描",
        "candidate_paths": [],
        "steps": []
      }
    }
  }'
```

**响应示例**：

```json
{
  "analysis": {
    "goal_analysis": {
      "score": 0.85,
      "strengths": ["成功标准可量化"],
      "weaknesses": ["缺少形容词标准定义"]
    },
    "context_analysis": {
      "score": 0.7,
      "strengths": ["已知事实清晰"],
      "weaknesses": ["未识别关键约束"]
    },
    "choice_analysis": {
      "score": 0.9,
      "strengths": ["路径选择有证据支持"],
      "weaknesses": []
    },
    "checkpoint_analysis": {
      "score": 0.4,
      "strengths": [],
      "weaknesses": ["缺少 Checkpoint 定义"]
    },
    "correction_analysis": {
      "score": 0.3,
      "strengths": [],
      "weaknesses": ["未定义任何纠正规则"]
    },
    "overall_score": 0.63,
    "recommendations": [
      "增加 Checkpoint 覆盖关键步骤",
      "为常见失败场景定义 Correction 规则"
    ]
  }
}
```

---

#### 2.7.2 记录 Replan 事件

- **方法与路径**：`POST /api/evaluation/replan/event`
- **描述**：记录 Replan 事件，收集单次 Replan 事件的完整信息用于后续效果评估。相同 event_id 的事件将更新而非重复记录。

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| event | ReplanEvent | 是 | Replan 事件记录 |

**ReplanEvent 结构**：

| 字段 | 类型 | 说明 |
|---|---|---|
| event_id | string | 事件 ID |
| timestamp | string | 事件时间戳 |
| plan_id | string | Plan ID |
| trigger | string | 触发原因 |
| failure_step_id | string | 失败步骤 |
| root_cause_step_id | string | 定位的根因步骤 |
| actual_root_cause | string | 实际根因（人工标注或故障注入） |
| root_cause_correct | boolean \| null | 根因定位是否正确 |
| replan_start_step_id | string | Replan 起始步骤 |
| actual_replan_start | string | 实际合理的 Replan 起点 |
| replan_start_correct | boolean \| null | Replan 起点是否合理 |
| total_results | int | 中间结果总数 |
| trusted_results | int | 可信结果数 |
| reused_results | int | 复用结果数 |
| recovered | boolean | 是否恢复成功 |
| path_history | list[string] | 路径切换历史 |

**响应体**：

| 字段 | 类型 | 说明 |
|---|---|---|
| success | boolean | 是否记录成功 |
| event_id | string | 事件 ID |
| total_events | int | 当前总事件数 |

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/evaluation/replan/event \
  -H "Content-Type: application/json" \
  -d '{
    "event": {
      "event_id": "evt_001",
      "timestamp": "2026-07-26T10:00:00Z",
      "plan_id": "plan_001",
      "trigger": "tool_failure",
      "failure_step_id": "step_3",
      "root_cause_step_id": "step_1",
      "actual_root_cause": "",
      "root_cause_correct": null,
      "replan_start_step_id": "step_2",
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

**响应示例**：

```json
{
  "success": true,
  "event_id": "evt_001",
  "total_events": 1
}
```

---

#### 2.7.3 获取 Replan 五项指标

- **方法与路径**：`GET /api/evaluation/replan/metrics`
- **描述**：获取 Replan 效果评估五项指标，包括根因定位准确率、Replan 起点准确率、结果复用率、Replan 恢复成功率、Replan 振荡率及基础统计。

**请求参数**：无

**响应体**：

| 字段 | 类型 | 说明 |
|---|---|---|
| root_cause_accuracy | float | 根因定位准确率 |
| replan_start_accuracy | float | Replan 起点准确率 |
| result_reuse_rate | float | 现有结果复用率 |
| recovery_success_rate | float | Replan 恢复成功率 |
| oscillation_rate | float | Replan 振荡率 |
| total_replan_count | int | 总 Replan 次数 |
| total_failure_cases | int | 总失败案例数 |

**curl 示例**：

```bash
curl -X GET http://localhost:8000/api/evaluation/replan/metrics
```

**响应示例**：

```json
{
  "root_cause_accuracy": 0.82,
  "replan_start_accuracy": 0.75,
  "result_reuse_rate": 0.68,
  "recovery_success_rate": 0.90,
  "oscillation_rate": 0.05,
  "total_replan_count": 20,
  "total_failure_cases": 18
}
```

---

#### 2.7.4 获取评估报告

- **方法与路径**：`GET /api/evaluation/replan/report`
- **描述**：获取 Replan 评估报告，返回文本格式报告，包含五项指标及改进建议。

**请求参数**：无

**响应体**：

| 字段 | 类型 | 说明 |
|---|---|---|
| report | string | 评估报告文本 |

**curl 示例**：

```bash
curl -X GET http://localhost:8000/api/evaluation/replan/report
```

**响应示例**：

```json
{
  "report": "Replan 效果评估报告\n====================\n\n一、五项核心指标\n1. 根因定位准确率：82%\n2. Replan 起点准确率：75%\n3. 结果复用率：68%\n4. 恢复成功率：90%\n5. 振荡率：5%\n\n二、改进建议\n1. 根因定位准确率偏低，建议增强 Checkpoint 覆盖以提供更多追溯线索\n2. Replan 起点选择可进一步优化，建议结合失败回溯结果辅助决策\n3. 结果复用率有提升空间，建议完善可信状态管理机制"
}
```

---

#### 2.7.5 导入人工标注

- **方法与路径**：`POST /api/evaluation/replan/annotate`
- **描述**：导入人工标注结果。通过 event_id 匹配并更新事件的标注字段（root_cause_correct / replan_start_correct 等）。

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| annotations | list[dict] | 是 | 标注列表，每项包含 event_id 和标注字段 |

**响应体**：

| 字段 | 类型 | 说明 |
|---|---|---|
| success | boolean | 是否导入成功 |
| annotated_count | int | 标注数量 |

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/evaluation/replan/annotate \
  -H "Content-Type: application/json" \
  -d '{
    "annotations": [
      {
        "event_id": "evt_001",
        "root_cause_correct": true,
        "actual_root_cause": "step_1 的数据源配置错误",
        "replan_start_correct": true,
        "actual_replan_start": "step_2"
      },
      {
        "event_id": "evt_002",
        "root_cause_correct": false,
        "actual_root_cause": "step_2 的缓存失效",
        "replan_start_correct": false,
        "actual_replan_start": "step_1"
      }
    ]
  }'
```

**响应示例**：

```json
{
  "success": true,
  "annotated_count": 2
}
```

---

#### 2.7.6 导出测试集

- **方法与路径**：`GET /api/evaluation/replan/test-set`
- **描述**：导出 Replan 评估测试集。导出所有事件的关键字段用于人工标注或故障注入评估，root_cause_correct 和 replan_start_correct 设为 None 等待标注。

**请求参数**：无

**响应体**：

| 字段 | 类型 | 说明 |
|---|---|---|
| test_set | list[dict] | 测试集列表 |
| total | int | 测试集总数 |

**curl 示例**：

```bash
curl -X GET http://localhost:8000/api/evaluation/replan/test-set
```

**响应示例**：

```json
{
  "test_set": [
    {
      "event_id": "evt_001",
      "plan_id": "plan_001",
      "trigger": "tool_failure",
      "failure_step_id": "step_3",
      "root_cause_step_id": "step_1",
      "root_cause_correct": null,
      "replan_start_step_id": "step_2",
      "replan_start_correct": null,
      "recovered": true
    },
    {
      "event_id": "evt_002",
      "plan_id": "plan_002",
      "trigger": "assumption_violation",
      "failure_step_id": "step_5",
      "root_cause_step_id": "step_2",
      "root_cause_correct": null,
      "replan_start_step_id": "step_3",
      "replan_start_correct": null,
      "recovered": false
    }
  ],
  "total": 2
}
```

---

### 2.8 DAG

#### 2.8.1 验证 DAG 结构

- **方法与路径**：`POST /api/dag/validate`
- **描述**：验证 DAG 结构（循环依赖检测、节点引用有效性）。

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| dag | DAGPlan | 是 | 待验证的 DAG 结构 |

**响应体**：

| 字段 | 类型 | 说明 |
|---|---|---|
| valid | boolean | 是否有效（无错误时为 true） |
| errors | list[string] | 错误信息列表 |
| cycles | list[list[string]] | 检测到的环列表 |
| topological_order | list[string] | 拓扑排序结果 |

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/dag/validate \
  -H "Content-Type: application/json" \
  -d '{
    "dag": {
      "nodes": [
        {"id": "node_1", "objective": "数据采集", "reason": "起始步骤", "depends_on": [], "status": "pending"},
        {"id": "node_2", "objective": "数据清洗", "reason": "依赖原始数据", "depends_on": ["node_1"], "status": "pending"},
        {"id": "node_3", "objective": "数据分析", "reason": "依赖清洗后数据", "depends_on": ["node_2"], "status": "pending"},
        {"id": "node_4", "objective": "报告生成", "reason": "依赖分析结果", "depends_on": ["node_3"], "status": "pending"}
      ],
      "edges": [
        {"src": "node_1", "dst": "node_2", "attrs": {}},
        {"src": "node_2", "dst": "node_3", "attrs": {}},
        {"src": "node_3", "dst": "node_4", "attrs": {}}
      ]
    }
  }'
```

**响应示例**（验证通过）：

```json
{
  "valid": true,
  "errors": [],
  "cycles": [],
  "topological_order": ["node_1", "node_2", "node_3", "node_4"]
}
```

**响应示例**（存在环依赖）：

```json
{
  "valid": false,
  "errors": [
    "检测到环依赖：node_2 -> node_3 -> node_2"
  ],
  "cycles": [["node_2", "node_3", "node_2"]],
  "topological_order": []
}
```

---

## 3. 数据模型

### 3.1 Plan

G4C 复合 Plan 对象，是可检查、可纠正、可执行的运行时对象。

| 字段 | 类型 | 说明 |
|---|---|---|
| goal | Goal | 目标与成功标准 |
| context | Context | 上下文与约束 |
| choice | Choice | 路径决策与步骤 |
| checkpoint | list[Checkpoint] | Checkpoint 列表 |
| correction | list[Correction] | 纠正规则列表 |
| mode | PlanMode | Plan 模式（`linear` / `dag`），默认 `linear` |
| status | PlanStatus | 执行状态（`draft`/`ready`/`running`/`completed`/`failed`/`aborted`），默认 `draft` |
| dag | DAGPlan \| null | DAG 结构，仅 mode=dag 时有效 |
| check_results | list[CheckResult] | Checkpoint 执行结果列表 |
| current_step_index | int | 当前执行步骤索引，默认 0 |
| iteration_count | int | 迭代生成循环次数，默认 0 |

#### Goal（目标）

| 字段 | 类型 | 说明 |
|---|---|---|
| user_goal | string | 用户目标描述 |
| success_criteria | list[string] | 成功标准列表，每项必须可验证 |
| adjective_standards | dict[string, string] | 形容词标准定义，将模糊形容词映射为可量化标准 |

#### Context（上下文）

| 字段 | 类型 | 说明 |
|---|---|---|
| known_facts | list[string] | 已知事实列表 |
| missing_info | list[string] | 缺失信息列表 |
| constraints | Constraints | 约束集（硬约束 + 软约束） |

**Constraints 结构**：

| 字段 | 类型 | 说明 |
|---|---|---|
| hard | list[string] | 硬约束列表，不可违反 |
| soft | list[string] | 软约束列表，应当满足 |

#### Choice（路径决策）

| 字段 | 类型 | 说明 |
|---|---|---|
| selected_path | string | 选择的路径描述 |
| reason | string | 选择原因，必须基于上下文中的事实或约束（证据驱动） |
| candidate_paths | list[string] | 候选路径列表 |
| steps | list[Step] | 步骤列表 |

**Step 结构**：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 步骤唯一标识 |
| objective | string | 步骤目标 |
| reason | string | 步骤存在原因，支持追溯 |
| status | string | 步骤状态：`pending` / `running` / `done` / `failed` / `skipped` |

#### Checkpoint（检查点）

| 字段 | 类型 | 说明 |
|---|---|---|
| step_id | string | 关联的步骤 ID |
| checks | list[string] | 检查项列表，每项为具体可验证的检查条件 |

**CheckResult（检查结果）**：

| 字段 | 类型 | 说明 |
|---|---|---|
| step_id | string | 关联的步骤 ID |
| check_point | string | 检查项 |
| passed | boolean | 是否通过 |
| result | string | 检查结果描述 |
| evidences | list[CheckEvidence] | 证据列表 |

#### Correction（纠正）

| 字段 | 类型 | 说明 |
|---|---|---|
| condition | string | 触发条件描述 |
| action | CorrectionAction | 纠正动作 |

**CorrectionAction 结构**：

| 字段 | 类型 | 说明 |
|---|---|---|
| type | CorrectionType | 纠正策略类型：`retry`/`replan`/`clarify`/`rollback`/`abort` |
| retry_granularity | RetryGranularity \| null | 重试粒度（仅 type=retry 有效）：`step`/`partial_flow`/`full_restart` |
| target_step_id | string \| null | 目标步骤 ID，用于回滚或部分重试 |
| params | dict | 附加参数 |
| message | string | 纠正动作描述 |

---

### 3.2 ReplanResult

Replan 执行结果，包含步骤变更分类（保留/修改/移除）、新 Plan 和更新后的控制信息。

| 字段 | 类型 | 说明 |
|---|---|---|
| retained_steps | list[StepChange] | 保留的步骤及原因 |
| modified_steps | list[StepChange] | 修改的步骤及原因 |
| removed_steps | list[StepChange] | 移除的步骤及原因 |
| new_plan | Plan \| null | Replan 后的新 Plan |
| replan_info | ReplanInfo | 更新后的 Replan 控制信息 |

**StepChange 结构**：

| 字段 | 类型 | 说明 |
|---|---|---|
| step_id | string | 步骤 ID |
| reason | string | 变更原因（证据驱动） |
| change_type | string | 变更类型：`retained` / `modified` / `removed` |
| modification_detail | string | 修改详情，仅 modified 时有效 |

**ReplanInfo 结构**：

| 字段 | 类型 | 说明 |
|---|---|---|
| max_replan_total | int | 最大允许 Replan 次数，默认 3 |
| used_replan_total | int | 已使用 Replan 次数，默认 0 |

---

### 3.3 TCCResult

TCC Replan 完整结果，包含三个阶段的执行结果。

| 字段 | 类型 | 说明 |
|---|---|---|
| phase | TCCPhase | 最终阶段：`try` / `confirm` / `cancel` |
| try_result | TryResult \| null | Try 阶段结果 |
| confirm_result | ConfirmResult \| null | Confirm 阶段结果 |
| cancel_result | CancelResult \| null | Cancel 阶段结果 |
| new_plan | Plan \| null | 最终新 Plan（成功时返回） |

**TryResult 结构**：

| 字段 | 类型 | 说明 |
|---|---|---|
| validations | list[TryValidation] | 验证结果列表 |
| all_passed | boolean | 是否全部通过 |
| temp_data | dict | Try 产生的临时数据（存放在临时空间） |
| failed_assumptions | list[string] | 失败假设列表 |
| unavailable_tools | list[string] | 不可用工具列表 |

**TryValidation 结构**：

| 字段 | 类型 | 说明 |
|---|---|---|
| target_step_id | string | 待验证的目标步骤 ID |
| validation_type | TryValidationType | 验证类型：`tool_availability`/`data_accessibility`/`assumption_validation`/`key_dependency` |
| passed | boolean | 是否通过 |
| result | string | 验证结果描述 |
| evidence | string | 验证证据 |

**ConfirmResult 结构**：

| 字段 | 类型 | 说明 |
|---|---|---|
| executed | boolean | 是否已执行 |
| try_results_written | boolean | Try 结果是否已写入上下文 |
| reused_try_data | boolean | 是否复用了 Try 数据 |
| execution_summary | string | 执行摘要 |

**CancelResult 结构**：

| 字段 | 类型 | 说明 |
|---|---|---|
| temp_data_cleaned | boolean | 临时数据是否已清理 |
| failed_assumptions_marked | list[string] | 已标记的失败假设 |
| unavailable_tools_marked | list[string] | 已标记的不可用工具 |
| should_continue_replan | boolean | 是否继续 Replan |
| has_alternative_solutions | boolean | 是否存在替代方案 |
| abort_reason | string \| null | 终止原因（不继续 Replan 时） |

---

### 3.4 FailureTracingResult

失败回溯结果，包含四个关键点定义和反向追溯链。核心概念：失败点 ≠ 根因点。

| 字段 | 类型 | 说明 |
|---|---|---|
| failure_point | TracingPoint | 失败点：错误暴露的位置 |
| root_cause_point | TracingPoint \| null | 根因点：错误最初引入的位置 |
| rollback_point | TracingPoint \| null | 回滚点：状态恢复位置 |
| replan_start_point | TracingPoint \| null | Replan 起始点：重新规划的起始位置 |
| tracing_chain | list[TracingPoint] | 反向追溯链，从失败点逐层向上 |
| checkpoint_reliable | boolean | Checkpoint 是否可靠，默认 true |

**TracingPoint 结构**：

| 字段 | 类型 | 说明 |
|---|---|---|
| step_id | string | 步骤 ID |
| reason | string | 确定该点的原因 |
| checkpoint_id | string \| null | 关联的 Checkpoint ID |
| action | string | 失败点专用：失败的动作 |
| error | string | 失败点专用：错误信息 |

---

### 3.5 TrustState（枚举）

中间结果可信状态，分为五个级别。

| 枚举值 | 说明 |
|---|---|
| `verified` | 已验证，当前可信 |
| `available` | 可用，暂未完全验证（默认状态） |
| `suspicious` | 可疑，可能存在问题，需重新检查 |
| `invalid` | 无效，已确认错误 |
| `dirty` | 受污染，依赖于 INVALID 结果 |

**FactEntry（事实条目）结构**：

| 字段 | 类型 | 说明 |
|---|---|---|
| key | string | 事实键名 |
| value | any | 事实值 |
| trust_state | TrustState | 可信状态 |
| evidence | string | 证据来源 |
| source_step_id | string | 产生该事实的步骤 ID |
| depends_on | list[string] | 依赖的其他事实键名列表 |

**TrustStateChange（状态变更记录）结构**：

| 字段 | 类型 | 说明 |
|---|---|---|
| key | string | 事实键名 |
| old_state | TrustState | 旧状态 |
| new_state | TrustState | 新状态 |
| reason | string | 变更原因 |
| cascaded | boolean | 是否为级联标记 |

---

### 3.6 BacktrackingLevel（枚举）

回溯级别，从最小到最大回溯范围排列，渐进式扩大策略按此顺序逐步升级。

| 枚举值 | 说明 |
|---|---|
| `action` | 动作级（重试），不修改 Plan，直接重试 |
| `step` | 步骤级（切换工具），切换到下一个候选路径 |
| `stage` | 阶段级（回到阶段入口），以 Checkpoint 为阶段边界重新规划 |
| `global` | 全局级，作废所有中间结果，从初始状态开始 |
| `cross_turn` | 跨轮次级，处理被错误事实污染的历史数据 |

**BacktrackingResult（回溯结果）结构**：

| 字段 | 类型 | 说明 |
|---|---|---|
| level | BacktrackingLevel | 回溯级别 |
| success | boolean | 是否回溯成功 |
| rollback_to | string | 回滚到的位置（step_id 或 stage_id） |
| new_plan_steps | list[dict] | 新的计划步骤 |
| reused_results | list[string] | 复用的中间结果 |
| expanded | boolean | 是否扩大了回溯范围 |
| next_level | BacktrackingLevel \| null | 下一个扩大级别 |

---

### 3.7 ReplanMetrics

Replan 效果评估指标，聚合五项核心指标和基础统计。

| 字段 | 类型 | 说明 |
|---|---|---|
| root_cause_accuracy | float | 根因定位准确率 |
| replan_start_accuracy | float | Replan 起点准确率 |
| result_reuse_rate | float | 现有结果复用率 |
| recovery_success_rate | float | Replan 恢复成功率 |
| oscillation_rate | float | Replan 振荡率 |
| total_replan_count | int | 总 Replan 次数 |
| total_failure_cases | int | 总失败案例数 |

---

## 4. 错误处理

所有接口在发生错误时返回统一的 JSON 错误格式，HTTP 状态码标识错误类型。

### 错误响应格式

```json
{
  "detail": "错误详情描述"
}
```

### HTTP 状态码

| 状态码 | 说明 | 触发场景 |
|---|---|---|
| 400 | Bad Request | 输入无效或约束违反。例如：添加硬约束时缺少用户输入证据、CROSS_TURN 级别回溯缺少 contamination 参数、不支持的回溯级别 |
| 404 | Not Found | 资源不存在。例如：更新可信状态时事实键名不存在、路径切换时决策节点无可用候选路径 |
| 422 | Unprocessable Entity | 请求体无法解析或字段验证失败（FastAPI 默认行为） |
| 500 | Internal Server Error | 服务器内部错误。例如：LLM 服务调用失败、依赖服务异常 |

### 常见错误示例

**约束违反（400）**：

```json
{
  "detail": "添加硬约束需要用户输入作为证据"
}
```

**资源不存在（404）**：

```json
{
  "detail": "事实键名 'unknown_key' 不存在"
}
```

**决策节点无可用候选路径（404）**：

```json
{
  "detail": "Decision node decision_db_choice has no available candidate paths"
}
```

**缺少必要参数（400）**：

```json
{
  "detail": "cross_turn level backtracking requires contamination parameter"
}
```