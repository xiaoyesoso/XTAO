# XTAO

> 基于 G4C 方法论的 Agent 规划与执行框架

**English**: [README_en.md](README_en.md)

XTAO 是一套面向 Agent 的**规划（Plan）与执行（Execution）**框架。它不仅解决「如何生成一份好 Plan」的问题，还解决「Plan 在执行过程中如何感知偏差、定位根因、自我修正」的问题。

框架的核心由三部分组成：

- **G4C**（Goal、Context、Choice、Checkpoint、Correction）负责把 Plan 从「步骤列表」升级为**可检查、可纠偏、可执行的运行时对象**。
- **TAO**（Think-Action-Observation，思考-行动-观察）负责**步骤级执行**，让 Agent 每走一步都先思考、再行动、再观察。
- **Replan** 负责在执行偏离时做**可控修正**，覆盖 Step / Partial / Global 三种粒度。

G4C 系统性消除 Agent 执行过程中的目标不确定性、上下文不确定性、路径不确定性、过程不确定性与失败不确定性。

![G4C 五要素架构图](docs/images/g4c_architecture.png)

> 上图展示了 G4C 的五个要素如何围绕 Plan  runtime 对象工作。更完整的项目解读可参考 [docs/wechat_article_xplan.md](docs/wechat_article_xplan.md)。

---

## 目录

- [XTAO](#xtao)
  - [目录](#目录)
  - [功能特性](#功能特性)
  - [技术栈](#技术栈)
  - [项目结构](#项目结构)
  - [快速开始](#快速开始)
    - [本地开发](#本地开发)
    - [Docker 部署](#docker-部署)
  - [环境变量](#环境变量)
  - [API 概览](#api-概览)
    - [健康检查与监控](#健康检查与监控)
    - [Plan 管理](#plan-管理)
    - [约束管理](#约束管理)
    - [可信状态管理](#可信状态管理)
    - [回溯](#回溯)
    - [候选路径](#候选路径)
    - [评估](#评估)
    - [TAO（Think-Action-Observation）](#taothink-action-observation)
    - [TAO Action 设计说明](#tao-action-设计说明)
  - [Python SDK](#python-sdk)
  - [测试](#测试)
  - [G4C 方法论简述](#g4c-方法论简述)
    - [关键设计原则](#关键设计原则)
  - [TAO 简介](#tao-简介)
  - [相关文档](#相关文档)
  - [开源协议](#开源协议)

---

## 功能特性

- **G4C 五要素**：Goal（目标）、Context（上下文）、Choice（路径选择）、Checkpoint（检查点）、Correction（纠偏），逐一对应五类不确定性的消解。
- **Replan 机制**：触发检测 + 代码与大模型双重判定 + 三种粒度（步骤级 / 局部级 / 全局级），全程 evidence-based，判断与执行分离。
- **TCC Replan 高级方案**：借鉴分布式事务的 Try / Confirm / Cancel 三阶段，适用于高失败成本、高外部依赖、高副作用风险场景。
- **失败回溯与根因定位**：基于四点定义——失败点 / 根因点 / 回滚点 / Replan 起点，核心原则为「失败点 ≠ 根因点」。
- **可信状态管理**：对中间结果标记 `Verified / Available / Suspicious / Invalid / Dirty` 五种状态，支持依赖链级联标记。
- **回溯层级**：动作级 / 步骤级 / 阶段性 / 全局 / 跨轮次五种粒度，支持渐进扩展与跳跃式回溯。
- **候选路径保留与快速路径切换**：记录决策节点的候选路径，失败时无需重新规划即可快速切换。
- **迭代式 Plan 生成**：生成-评估-修正循环，逐步收敛到高质量 Plan。
- **DAG 式 Plan 生成（可选）**：支持有向无环图结构，含环检测与拓扑排序；线性 Plan 为默认模式。
- **Plan 质量评估**：离线分析（G4C 五维度）+ 线上监控（Prometheus 指标）。
- **Replan 效果评估**：根因准确率、Replan 起点准确率、结果复用率、Replan 恢复成功率、Replan 振荡率五项指标。
- **TAO（Think-Action-Observation）执行引擎**：步骤级受控状态循环，每轮包含五类结构化判断（目标、状态、路径、停止、风险），候选动作空间管理，证据绑定事实提取，可选双层监督循环检测目标漂移。
- **TAO 质量评估**：Think/Action/Observation/整体四层指标，支持 LLM as Judge 评估与人工标注对比。

---

## 技术栈

- **Python 3.11+**
- **FastAPI** —— 异步 Web 框架
- **Pydantic v2** —— 数据模型校验
- **httpx** —— 异步 LLM 调用
- **OpenAI 兼容 LLM API**（SiliconFlow DeepSeek）
- **prometheus-client** —— 在线监控指标
- **pytest / pytest-asyncio** —— 测试

---

## 项目结构

```
XTAO/
├── src/
│   └── xtao/
│       ├── main.py                # FastAPI 应用入口
│       ├── api/
│       │   └── routes.py          # REST API 路由定义
│       ├── models/                # G4C 数据模型（Pydantic）
│       │   ├── plan.py            # Plan 复合对象
│       │   ├── goal.py            # Goal
│       │   ├── context.py         # Context
│       │   ├── choice.py          # Choice
│       │   ├── checkpoint.py      # Checkpoint / CheckResult
│       │   ├── correction.py      # Correction（5 种纠偏策略）
│       │   ├── dag.py             # DAG 节点 / 边 / Plan
│       │   ├── replan.py          # Replan 相关模型
│       │   ├── tcc.py             # TCC 三阶段模型
│       │   ├── trust_state.py     # 可信状态模型
│       │   ├── backtracking.py    # 回溯层级模型
│       │   ├── tracing.py         # 失败回溯模型
│       │   └── tao.py                   # TAO 数据模型（TAOState、ThinkResult、ActionCandidate 等）
│       ├── prompts/               # Prompt 模块（每个 G4C 要素一个）
│       │   ├── goal_prompt.py
│       │   ├── context_prompt.py
│       │   ├── choice_prompt.py
│       │   ├── checkpoint_prompt.py
│       │   ├── correction_prompt.py
│       │   ├── dag_prompt.py
│       │   ├── replan_prompt.py
│       │   ├── tcc_prompt.py
│       │   ├── tracing_prompt.py
│       │   ├── aggregator.py      # 聚合所有模块 Prompt
│       │   └── constants.py       # 共享常量
│       ├── services/              # 服务层
│       │   ├── llm_service.py     # LLMService（httpx 异步，重试）
│       │   ├── rag_service.py     # RAGService（知识库检索）
│       │   ├── constraint_manager.py       # 约束管理（硬/软）
│       │   ├── trust_state_manager.py      # 可信状态管理
│       │   ├── candidate_path_manager.py   # 候选路径管理
│       │   └── tao_state_manager.py        # TAO 运行时状态管理
│       ├── engine/                # 核心引擎
│       │   ├── plan_generator.py          # 7 步 G4C 生成
│       │   ├── plan_verifier.py           # G4C 五维度评分
│       │   ├── plan_executor.py           # 逐步执行 + 检查点 + 纠偏
│       │   ├── correction_handler.py      # 5 种纠偏策略
│       │   ├── dag_validator.py           # 环检测 + 拓扑排序
│       │   ├── iteration_loop.py          # 生成-评估-修正循环
│       │   ├── replan_engine.py           # Replan 引擎
│       │   ├── tcc_replan.py              # TCC Replan
│       │   ├── backtracking_engine.py     # 回溯引擎
│       │   ├── cross_turn_tracker.py      # 跨轮次追踪
│       │   ├── failure_tracer.py          # 失败回溯与根因定位
│       │   ├── orchestrator.py            # 主编排引擎（主接口实现）
│       │   ├── tao_engine.py              # TAO 受控状态循环引擎
│       │   ├── tao_think_engine.py        # 五类结构化 Think 判断
│       │   ├── tao_action_runtime.py      # Action 抽象与执行（筛选、高可用包装器）
│       │   ├── tao_observation_interpreter.py # 原始输出转结构化 Observation
│       │   ├── tao_loop_controller.py     # 循环出口 + 死循环/停滞检测
│       │   └── tao_massive_action_filter.py # 海量 Action 多级筛选流水线
│       ├── sdk/                   # Python SDK（REST API 异步客户端）
│       │   ├── client.py                 # XTAOClient（覆盖全部细粒度 REST 接口）
│       │   └── exceptions.py             # XTAOError / APIError / ConnectionError 等
│       └── evaluation/            # 质量评估
│           ├── metrics.py                 # Prometheus 指标
│           ├── offline_analyzer.py        # 离线 G4C 分析
│           ├── replan_evaluator.py        # Replan 效果评估
│           ├── user_correction_detector.py # 用户纠偏检测
│           └── tao_evaluator.py        # TAO 质量评估（Think/Action/Observation 指标）
├── tests/                         # 单元测试与集成测试
│   ├── test_plan.py                # G4C 核心单元测试
│   ├── test_tao.py                 # TAO 模型/引擎/筛选/循环安全单元测试
│   ├── test_backtracking.py        # 回溯引擎单元测试
│   ├── test_tracing.py             # 失败回溯单元测试
│   ├── test_live.py                # 真实 LLM 集成测试
│   └── test_tao_live.py            # TAO 真实模型端到端测试
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── requirements.txt
└── .env.example
```

---

## 快速开始

### 本地开发

```bash
# 克隆仓库
git clone <repo-url>
cd XTAO

# 安装依赖
pip install -e .

# 配置环境变量
cp .env.example .env
# 编辑 .env 填写 LLM API key

# 启动服务
python -m uvicorn xtao.main:app --host 0.0.0.0 --port 8000
```

启动后访问交互式文档：`http://localhost:8000/docs`

### Docker 部署

```bash
cp .env.example .env
# 编辑 .env 填写实际配置

docker compose up -d
```

---

## 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `BASE_URL` | LLM API 地址 | `http://localhost:11434/v1` |
| `API_KEY` | LLM API 密钥 | （必填） |
| `FLASH_LLM_MODEL` | 快速 LLM 模型 | `deepseek-ai/DeepSeek-V4-Flash` |
| `PRO_LLM_MODEL` | Pro LLM 模型 | `deepseek-ai/DeepSeek-V4-Pro` |
| `RAG_ENABLED` | 启用 RAG 检索 | `false` |
| `PROMETHEUS_ENABLED` | 启用 Prometheus 监控 | `false` |
| `TCC_ENABLED` | 启用 TCC Replan 模式 | `false` |
| `MAX_REPLAN_TOTAL` | 最大 Replan 次数 | `3` |
| `HOST` | 服务监听地址 | `0.0.0.0` |
| `PORT` | 服务监听端口 | `8000` |

---

## API 概览

所有接口统一前缀 `/api`。**`POST /api/plan/run` 是主入口** —— 内部编排完整 G4C 生命周期（生成 → 评估 → 执行 → 纠偏，含失败回溯、可信状态、回溯、Replan、评估）。其余接口暴露各子系统供细粒度控制。完整接口参考见 [docs/API_zh.md](docs/API_zh.md)。

### 健康检查与监控

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| GET | `/api/metrics` | 获取在线监控指标 |

### Plan 管理

| 方法 | 路径 | 说明 |
|---|---|---|
| **POST** | **`/api/plan/run`** | **主编排入口**（完整 G4C 生命周期） |
| POST | `/api/plan/generate` | 生成 G4C Plan（支持迭代模式） |
| POST | `/api/plan/verify` | 评估 Plan 质量（G4C 五维度） |
| POST | `/api/plan/execute` | 执行 Plan（逐步 + 检查点 + 纠偏） |
| POST | `/api/plan/iterate` | 迭代式 Plan 生成（生成-评估-修正循环） |
| POST | `/api/plan/trace` | 失败回溯与根因定位（四点定义） |
| POST | `/api/plan/replan` | 触发 Replan（双重判定 + 三种粒度） |
| POST | `/api/plan/tcc-replan` | 执行 TCC Replan（Try/Confirm/Cancel） |
| POST | `/api/dag/validate` | DAG 结构验证（环检测 + 拓扑排序） |

### 约束管理

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/constraints/hard` | 添加硬约束（需用户输入作为证据） |
| POST | `/api/constraints/soft` | 添加软约束 |
| GET | `/api/constraints` | 获取全部约束列表 |

### 可信状态管理

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/trust-state/facts` | 添加事实条目（默认 AVAILABLE） |
| GET | `/api/trust-state/facts` | 获取所有事实条目 |
| POST | `/api/trust-state/update` | 更新可信状态（INVALID 触发级联标记） |
| GET | `/api/trust-state/report` | 获取可信状态报告（各状态统计） |
| GET | `/api/trust-state/suspicious` | 获取需优先检查的 Suspicious/Dirty 事实 |

### 回溯

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/backtracking/execute` | 执行回溯（支持五种层级，可自动判定） |
| POST | `/api/backtracking/progressive` | 渐进扩展回溯（ACTION→STEP→STAGE→GLOBAL） |
| POST | `/api/backtracking/jump` | 跳跃回溯（按规则匹配直接定位） |

### 候选路径

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/candidate-paths/register` | 注册决策节点及其候选路径 |
| POST | `/api/candidate-paths/switch/{decision_id}` | 快速路径切换 |
| GET | `/api/candidate-paths/failed` | 获取失败路径记录 |

### 评估

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/evaluation/offline` | 离线 Plan 分析（G4C 五维度） |
| POST | `/api/evaluation/replan/event` | 记录 Replan 事件 |
| GET | `/api/evaluation/replan/metrics` | 获取 Replan 五项指标 |
| GET | `/api/evaluation/replan/report` | 获取 Replan 评估报告 |
| POST | `/api/evaluation/replan/annotate` | 导入手工标注结果 |
| GET | `/api/evaluation/replan/test-set` | 导出 Replan 评估测试集 |

TAO 评估接口（`/api/evaluation/tao/event`、`/api/evaluation/tao/metrics`、`/api/evaluation/tao/report`、`/api/evaluation/tao/annotate`、`/api/evaluation/tao/test-set`、`/api/evaluation/tao/judge`）见 [TAO（Think-Action-Observation）](#taothink-action-observation) 分类。

### TAO（Think-Action-Observation）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/tao/run` | 运行完整 TAO 受控状态循环 |
| POST | `/api/tao/think` | 原子 Think 接口（五类结构化判断） |
| POST | `/api/tao/act` | 原子 Action 执行接口 |
| POST | `/api/tao/observe` | 原子 Observation 解释接口 |
| POST | `/api/evaluation/tao/event` | 记录 TAO 评估事件 |
| GET | `/api/evaluation/tao/metrics` | 获取 TAO 评估指标（Think/Action/Observation/整体） |
| GET | `/api/evaluation/tao/report` | 获取 TAO 评估报告 |
| POST | `/api/evaluation/tao/annotate` | 导入 TAO 人工标注 |
| GET | `/api/evaluation/tao/test-set` | 导出 TAO 测试集 |
| POST | `/api/evaluation/tao/judge` | TAO LLM as Judge 评估 |

### TAO Action 设计说明

TAO 中的 Action 是面向目标的操作封装，不是原始工具。良好的 Action 设计能显著提升 Think 准确率与循环稳定性：

- **业务完整性**：Action 是一个业务上完整的操作，内部可调用一个或多个工具，也可启动子 Agent。
- **正交性**：职责边界清晰，尽量减少 Action 之间的重叠。
- **子 Agent 封装**：复杂子任务可封装为子 Agent，通过 Action 启动。
- **元数据驱动选择**：填写 `tags`、`intents`、`applicable_scenarios`、`permissions`、`cost`、`risk`、`alternatives` 等字段，帮助引擎筛选候选并选择正确的 Action。
- **执行前校验**：运行时会检查 Action 是否在候选空间、必填参数是否提供、权限是否满足、参数是否符合 schema。

完整筛选流水线见 [docs/API_zh.md](docs/API_zh.md)，使用示例见 [docs/SDK_zh.md](docs/SDK_zh.md)。

---

## Python SDK

`xtao.sdk` 提供类型安全的异步客户端，封装全部 REST 接口，并复用 `xtao.models` 中的 Pydantic 模型，可直接传入模型实例。

```python
import asyncio
from xtao.sdk import XTAOClient

async def main():
    async with XTAOClient(base_url="http://localhost:8000") as client:
        result = await client.run_plan(user_input="帮我优化简历")
        print(result["status"], result["replan_count"])

asyncio.run(main())
```

```python
# 启用 TAO 循环执行步骤
from xtao.models import OrchestratorConfig

config = OrchestratorConfig(use_tao=True, tao_max_loops=10)
result = await client.run_plan(user_input="...", config=config)
```

SDK 主方法是 `XTAOClient.run_plan()`；其他方法镜像全部细粒度 REST 接口（generate、verify、execute、trace、replan、tcc_replan、constraints、可信状态、回溯、候选路径、评估、metrics、DAG、TAO）。完整 SDK 文档：[docs/SDK_zh.md](docs/SDK_zh.md)（中文）/ [docs/SDK.md](docs/SDK.md)（English）。

---

## 测试

```bash
# 运行全部测试
python -m pytest tests/ -v

# 仅运行单元测试
python -m pytest tests/test_plan.py -v

# TAO 单元测试
python -m pytest tests/test_tao.py -v

# TAO 真实模型端到端测试（需要 API_KEY）
python tests/test_tao_live.py
```

---

## G4C 方法论简述

Plan 不是步骤列表，而是**可检查、可纠偏、可执行的运行时对象**。G4C 定义了一个好 Plan 的五个必备要素：

| 要素 | 核心问题 | 消解的不确定性 |
|---|---|---|
| **Goal** | 要达成什么？成功的标准是什么？ | 目标不确定性 |
| **Context** | 已知什么？缺失什么？ | 上下文不确定性 |
| **Choice** | 为什么选这条路？有哪些备选？ | 路径不确定性 |
| **Checkpoint** | 如何判断步骤正确？ | 过程不确定性 |
| **Correction** | 偏离时怎么办？ | 失败不确定性 |

### 关键设计原则

- **硬约束 vs 软约束**：硬约束不可违反，软约束应尽量满足；两者在每次 LLM 调用时注入系统 Prompt。
- **约束只能由用户输入修改**：Agent 不可自主修改约束。
- **基于证据的路径选择**：选择理由必须引用上下文中的事实或约束。
- **Checkpoint 三规则**：设置于里程碑、关键中间产物、易错步骤。
- **5 种纠偏策略**：Retry、Replan、Clarify、Rollback、Abort。
- **线性 Plan 为默认**：DAG Plan 为可选高级模式。

---

## TAO 简介

**TAO** 是 **Think（思考）- Action（行动）- Observation（观察）** 的缩写，是 XTAO 中负责**步骤级执行**的受控状态循环引擎。

如果说 G4C 和 Replan 解决的是「宏观 Plan 如何生成与修正」的问题，TAO 解决的就是「Plan 的每一步具体怎么执行」的问题。每一轮 TAO 循环都包含五个结构化判断：目标判断、状态判断、路径判断、停止判断和风险判断。

![TAO 循环图](docs/images/tao_loop.png)

TAO 中的 Action 不是原始工具调用，而是面向目标的操作封装。执行前会经过多级候选筛选，执行后会通过 Observation Interpreter 将原始输出转换为带证据绑定的事实。TAO 支持可选的双层监督循环，用于检测目标漂移、约束违反与停滞不前。

更详细的 TAO 设计说明见 [docs/API_zh.md](docs/API_zh.md)，使用示例见 [docs/SDK_zh.md](docs/SDK_zh.md)。

---

## 相关文档

- [docs/API_zh.md](docs/API_zh.md) —— 完整 REST API 中文参考
- [docs/API.md](docs/API.md) —— 完整 REST API 英文参考
- [docs/SDK_zh.md](docs/SDK_zh.md) —— Python SDK 中文文档
- [docs/SDK.md](docs/SDK.md) —— Python SDK 英文文档
- [docs/wechat_article_xplan.md](docs/wechat_article_xplan.md) —— 项目复盘长文，包含 G4C、Replan、失败回溯、信任状态、TCC、TAO 的完整解读与配图

设计配图存放在 [docs/images/](docs/images/)。

---

## 开源协议

[MIT](LICENSE)
