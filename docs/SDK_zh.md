# XPlan Python SDK（中文）

> XPlan G4C Plan 服务的 Pythonic、类型安全的异步客户端。

SDK 封装了 XPlan FastAPI 服务暴露的全部 REST 接口，并复用 `xplan.models`
中的 Pydantic 模型，调用方可直接传入模型实例，无需手动处理 JSON。

- **异步优先**：基于 `httpx.AsyncClient` 构建，与 FastAPI / 异步代码库无缝配合。
- **类型安全**：入参和返回值均为 Pydantic 模型 / 类型化字典。
- **统一错误**：所有失败均抛出 `XPlanError` 的子类。
- **单一入口**：`run_plan()` 编排完整 G4C 生命周期；细粒度方法供进阶控制。

## 目录

- [安装](#安装)
- [快速开始](#快速开始)
- [客户端配置](#客户端配置)
- [主入口：run_plan](#主入口run_plan)
- [方法参考](#方法参考)
  - [Plan 操作](#plan-操作)
  - [约束管理](#约束管理)
  - [评估](#评估)
  - [指标与 DAG](#指标与-dag)
  - [可信状态](#可信状态)
  - [回溯](#回溯)
  - [候选路径](#候选路径)
  - [TAO 循环](#tao-循环)
- [错误处理](#错误处理)
- [模型 vs 字典](#模型-vs-字典)
- [同步用法](#同步用法)
- [实战示例](#实战示例)

---

## 安装

SDK 随 `xplan` 包一同发布。在仓库根目录下以 editable 模式安装即可：

```bash
pip install -e .
```

依赖（`httpx`、`pydantic>=2.9`）会自动安装。

## 快速开始

```python
import asyncio
from xplan.sdk import XPlanClient

async def main():
    # 作为异步上下文管理器使用，HTTP 客户端会自动关闭
    async with XPlanClient(base_url="http://localhost:8000") as client:
        # 1. 健康检查
        print(await client.health_check())

        # 2. 运行完整 G4C 生命周期（主入口）
        result = await client.run_plan(
            user_input="帮我优化简历，目标是阿里 Java 后端",
        )
        print(result["status"])          # completed / failed / aborted / clarify_needed
        print(result["replan_count"])    # 触发的 Replan 次数
        print(result["verification_score"])

asyncio.run(main())
```

## 客户端配置

```python
from xplan.sdk import XPlanClient

client = XPlanClient(
    base_url="http://localhost:8000",  # XPlan 服务地址
    api_key="可选的-bearer-token",     # 作为 Authorization: Bearer <key> 发送
    timeout=120.0,                     # 请求超时（秒）
)
```

| 参数       | 类型                  | 默认值                  | 说明                                            |
|------------|-----------------------|--------------------------|-------------------------------------------------|
| `base_url` | `str`                 | `http://localhost:8000`  | XPlan 服务地址。                                 |
| `api_key`  | `str \| None`         | `None`                   | 可选的 bearer token。                            |
| `timeout`  | `float`               | `120.0`                  | 默认请求超时（秒）。                             |
| `client`   | `httpx.AsyncClient`   | `None`                   | 可选的预配置客户端（由调用方负责关闭）。          |

客户端是异步上下文管理器（`async with XPlanClient(...) as c:`）。若手动
创建，结束时需调用 `await client.close()`。

## 主入口：`run_plan`

`run_plan` 是**主接口**，内部编排完整的 G4C 流水线：

1. **生成** Plan（可选启用 生成-评估-纠偏 迭代循环）。
2. **评估** Plan 的 G4C 五维质量（可选，受阈值门控）。
3. **执行** Plan，逐步运行 Checkpoint。
4. Checkpoint 失败时编排恢复：
   - **失败回溯** —— 定位根因（失败点 ≠ 根因点）。
   - **可信状态** —— 将失败结果标记为 `invalid`，下游级联标记为 `dirty`。
   - **回溯** —— 渐进式扩大（动作 → 步骤 → 阶段 → 全局）。
   - **Replan** —— 通过 `ReplanEngine` 或 TCC Replan 进行受控纠偏。
   - **评估** —— 记录 Replan 事件，用于效果度量。
5. 返回 `OrchestratorResult`，含最终 Plan、执行轨迹、Replan 次数与评估分数。

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
    enable_tcc_replan=False,   # 仅高风险场景设为 True
    max_replan_count=3,
)

result = await client.run_plan(
    user_input="...",
    conversation_history="...",  # 可选
    config=config,               # 可选，默认值已较合理
)
```

| `OrchestratorConfig` 字段          | 默认值  | 说明                                            |
|-------------------------------------|---------|--------------------------------------------------|
| `use_iteration`                     | `True`  | 是否使用 生成-评估-纠偏 迭代循环。                |
| `max_iterations`                    | `3`     | 迭代循环最大次数。                                |
| `verify_before_execute`             | `True`  | 执行前是否评估 Plan。                             |
| `verification_threshold`            | `0.8`   | 评估分数阈值（0–1）。                             |
| `enable_failure_tracing`            | `True`  | Checkpoint 失败时是否启用失败回溯。               |
| `enable_trust_state`                | `True`  | 执行期间是否启用可信状态管理。                    |
| `enable_progressive_backtracking`   | `True`  | 失败时是否启用渐进式回溯。                        |
| `enable_tcc_replan`                 | `False` | 是否启用 TCC Replan（高风险场景）。               |
| `max_replan_count`                  | `3`     | 执行期间最大 Replan 次数。                        |
| `use_tao`                           | `False` | 是否通过 TAO 受控状态循环执行步骤。                |
| `tao_max_loops`                     | `10`    | 每步 TAO 内层循环最大轮数。                        |
| `tao_max_time`                      | `300.0` | 每步 TAO 最大执行时间（秒）。                      |
| `tao_supervisor_interval`           | `3`     | TAO 外层监督循环触发间隔（内层轮数）。              |
| `tao_supervisor_interval_seconds`   | `0.0`   | TAO 异步外层监督循环间隔（秒）。                    |

返回的 `OrchestratorResult` 字典字段：

| 字段                  | 类型                       | 说明                                                |
|-----------------------|----------------------------|------------------------------------------------------|
| `plan`                | `Plan`                     | 最终 Plan（若发生 Replan 可能与初始不同）。          |
| `status`              | `str`                      | `completed` / `failed` / `aborted` / `clarify_needed`。 |
| `step_records`        | `list[StepExecutionRecord]` | 每步执行轨迹。                                       |
| `replan_count`        | `int`                      | 总 Replan 次数。                                     |
| `iteration_count`     | `int`                      | Plan 生成迭代次数。                                  |
| `verification_score`  | `float \| None`            | Plan 评估分数（0–1）。                               |
| `verification_passed` | `bool \| None`             | 评估是否通过阈值。                                   |
| `errors`              | `list[str]`                | 执行期间遇到的错误。                                 |
| `clarify_message`     | `str \| None`              | 当 `status == "clarify_needed"` 时的澄清消息。       |

---

## 方法参考

所有方法均为 `async`，与 `/api` 下的 REST 接口一一对应。

### Plan 操作

#### `generate_plan(user_input, conversation_history="", use_iteration=False) -> dict`
`POST /api/plan/generate` —— 生成 G4C Plan。

```python
res = await client.generate_plan(
    user_input="优化简历",
    use_iteration=True,
)
plan = res["plan"]
```

当 `use_iteration=True` 时，响应还包含 `verification_results` 与 `iterations`。

#### `verify_plan(plan) -> dict`
`POST /api/plan/verify` —— 评估 Plan 的 G4C 五维质量。

```python
res = await client.verify_plan(plan)
print(res["verification"])
```

#### `execute_plan(plan) -> dict`
`POST /api/plan/execute` —— 逐步执行 Plan 并运行 Checkpoint。

```python
res = await client.execute_plan(plan)
executed_plan = res["plan"]
print(executed_plan["status"])   # completed / aborted / ...
```

#### `iterate_plan(user_input, conversation_history="") -> dict`
`POST /api/plan/iterate` —— 通过 生成-评估-纠偏 循环迭代生成 Plan。
返回 `plan`、`verification_results`、`iterations`。

#### `trace_failure(plan, failure_step_id, failure_info="", step_records=None) -> dict`
`POST /api/plan/trace` —— 触发失败回溯与根因定位。

核心理念：**失败点 ≠ 根因点**。回溯器从失败点构建反向追踪链，定位真正的
根因点，并给出回滚点和 Replan 起点建议。

```python
res = await client.trace_failure(
    plan=plan,
    failure_step_id="step-3",
    failure_info="checkpoint 失败：QPS 估算无依据",
    step_records=[{"step_id": "step-3", "output": {...}}],
)
result = res["result"]
print(result["root_cause_point"])     # 真正的根因点
print(result["rollback_point"])       # 状态恢复位置
print(result["replan_start_point"])   # Replan 起点
```

#### `replan(plan, error_info="", user_input="", conversation_history="") -> dict`
`POST /api/plan/replan` —— 触发 Replan（受控纠偏）。

流程：检测触发 → 代码判定 → LLM 判定 → 执行 Replan。

#### `tcc_replan(plan, conversation_history="") -> dict`
`POST /api/plan/tcc-replan` —— 执行 TCC Replan（Try / Confirm / Cancel）。

仅适用于高失败成本、高外部依赖、高副作用风险场景。响应 `result` 含
`try`、`confirm`、`cancel` 三阶段。

### 约束管理

硬约束不可违反；软约束应尽量满足。**约束修改必须有用户输入作为证据** ——
Agent 不能自行修改约束。

#### `add_hard_constraint(constraint, user_input) -> dict`
#### `add_soft_constraint(constraint, user_input) -> dict`
#### `get_constraints() -> dict`

```python
await client.add_hard_constraint(
    constraint="不能虚构项目事实",
    user_input="请不要编造我没做过的事情",
)
await client.add_soft_constraint(constraint="尽量量化结果", user_input="...")
print(await client.get_constraints())
# {"hard": [...], "soft": [...]}
```

### 评估

#### `offline_analysis(plan) -> dict`
`POST /api/evaluation/offline` —— 围绕 G4C 五维离线分析 Plan。

#### `record_replan_event(event) -> dict`
`POST /api/evaluation/replan/event` —— 记录 Replan 事件用于评估。
相同 `event_id` 的事件会被更新而非重复记录。

#### `get_replan_metrics() -> dict`
`GET /api/evaluation/replan/metrics` —— Replan 效果五指标：
根因定位准确率、Replan 起点准确率、已有结果复用率、Replan 恢复成功率、
Replan 振荡率。

#### `get_replan_report() -> dict`
`GET /api/evaluation/replan/report` —— 文本格式的评估报告，含改进建议。

#### `annotate_replan(annotations) -> dict`
`POST /api/evaluation/replan/annotate` —— 导入人工标注。每条需含 `event_id`
以及标注字段（如 `root_cause_correct` / `replan_start_correct`）。

#### `export_replan_test_set() -> dict`
`GET /api/evaluation/replan/test-set` —— 导出 Replan 评估测试集
（所有事件的关键字段，标注字段置为 `null`）。

### 指标与 DAG

#### `get_metrics() -> dict`
`GET /api/metrics` —— 在线监控指标：
`plan_completion_rate`、`step_success_rate`、`replan_rate`、
`user_correction_rate`、`task_success_rate`、`average_iteration_count`。

#### `validate_dag(dag) -> dict`
`POST /api/dag/validate` —— 校验 DAG 结构（环检测 + 拓扑排序）。
返回 `valid`、`errors`、`cycles`、`topological_order`。

```python
from xplan.models import DAGPlan, DAGNode, DAGEdge

dag = DAGPlan(nodes=[DAGNode(...)], edges=[DAGEdge(...)])
res = await client.validate_dag(dag)
print(res["valid"], res["cycles"], res["topological_order"])
```

### 可信状态

可信状态为中间结果打标，使回溯定位根因时优先检查可疑/脏数据，跳过已验证
数据。

| 状态        | 含义                                                       |
|-------------|------------------------------------------------------------|
| `verified`  | 已确认正确（根因搜索时跳过）。                              |
| `available` | 默认状态；可用但尚未验证。                                  |
| `suspicious`| 需优先检查。                                                |
| `invalid`   | 已确认错误 —— 级联标记所有下游事实为 `dirty`。              |
| `dirty`     | 依赖了 invalid 事实（传递性污染）。                         |

#### `add_fact(key, value, evidence="", source_step_id="", depends_on=None) -> dict`
#### `get_facts() -> dict`
#### `update_trust_state(key, new_state, reason="") -> dict`
设 `new_state="invalid"` 时会触发 BFS 级联标记，响应包含所有变更记录。

#### `get_trust_state_report() -> dict`
#### `get_suspicious_and_dirty() -> dict`

```python
await client.add_fact(
    key="highest_qps",
    value=12000,
    evidence="用户访谈 2026-07-26",
    source_step_id="step-1",
    depends_on=["cluster_size"],
)
# 后续将其标记为 invalid —— 下游事实自动变为 dirty
changes = await client.update_trust_state("highest_qps", "invalid", reason="用户撤回")
print(changes["changes"])
```

### 回溯

五个回溯层级，由小到大：`action` → `step` → `stage` → `global` → `cross_turn`。

#### `execute_backtracking(plan, error_info="", level=None, failure_tracing_result=None, step_id="", decision_id="", stage_checkpoint_id="", contamination=None) -> dict`
`POST /api/backtracking/execute` —— 按指定层级执行回溯。
`level=None` 时由服务端自动判定。`cross_turn` 需提供 `contamination`。

#### `progressive_backtracking(plan, error_info="", failure_tracing_result=None) -> dict`
`POST /api/backtracking/progressive` —— 渐进式扩大回溯
（动作 → 步骤 → 阶段 → 全局）。每次扩大前通过 TCC 校验新 Plan 可行性。

#### `jump_backtracking(error_pattern, jump_rules=None) -> dict`
`POST /api/backtracking/jump` —— 按预定义规则跳级回溯。
直接根据模式匹配定位回溯位置，跳过渐进式扩大的开销。响应含 `matched: bool`。

### 候选路径

决策节点保留候选路径，使失败时切换路径快速 —— 无需重新生成 Plan。

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
# llm-extract 失败后，切换到下一个可用候选
new_path = await client.switch_candidate_path("extract-facts")
print(new_path["new_path"])   # regex-extract
```

### TAO 循环

TAO（Think-Action-Observation）是步骤级受控状态循环。Plan 定义宏观路径，
TAO 决定每个具体步骤如何推进并解释反馈。

#### `run_tao(user_input, plan=None, candidate_actions=None, max_loops=10, max_time=300.0) -> dict`
`POST /api/tao/run` -- 运行完整 TAO 受控状态循环。

```python
from xplan.models import ActionCandidate, ActionType

result = await client.run_tao(
    user_input="帮我优化简历中的项目经历",
    candidate_actions=[
        ActionCandidate(name="read_resume", type=ActionType.TOOL_CALL, description="读取简历"),
        ActionCandidate(name="write_resume", type=ActionType.TOOL_CALL, description="输出优化后的简历"),
    ],
    max_loops=6,
)
print(result["exit_type"])    # finish / clarify / replan / interrupt
print(result["used_loops"])
print(result["final_output"])
```

#### `tao_think(state) -> dict`
`POST /api/tao/think` -- 原子 Think 接口。

对给定状态运行一轮 Think，产出结构化 ThinkResult（五类判断：目标、状态、路径、停止、风险）
加循环控制器的出口决策。调用方需在多次调用间维护 TAOState。

#### `tao_act(state, action_name, params=None) -> dict`
`POST /api/tao/act` -- 原子 Action 执行接口。

执行候选空间中的指定动作。非法动作和不满足前置条件的动作返回 400 错误。

#### `tao_observe(state, record, expectation="") -> dict`
`POST /api/tao/observe` -- 原子 Observation 解释接口。

将 Action 原始输出解释为结构化 Observation，包含证据绑定的事实提取。

#### `record_tao_evaluation_event(event) -> dict`
`POST /api/evaluation/tao/event` -- 记录 TAO 评估事件。

#### `get_tao_metrics() -> dict`
`GET /api/evaluation/tao/metrics` -- 获取聚合的 TAO 评估指标
（Think/Action/Observation/整体）。

#### `get_tao_report() -> dict`
`GET /api/evaluation/tao/report` -- 获取 TAO 评估报告，含指标、异常样本和优化建议。

#### `annotate_tao(annotations) -> dict`
`POST /api/evaluation/tao/annotate` -- 导入人工金标答案标注。

#### `export_tao_test_set() -> dict`
`GET /api/evaluation/tao/test-set` -- 导出 TAO 评估测试集。

#### `tao_llm_judge(request) -> dict`
`POST /api/evaluation/tao/judge` -- 对单个 TAO 轮次运行 LLM as Judge 评估。

### 通过 `run_plan` 启用 TAO

TAO 也可以在主编排流程中按步骤启用：

```python
from xplan.models import OrchestratorConfig

config = OrchestratorConfig(
    use_tao=True,
    tao_max_loops=10,
    tao_max_time=300.0,
    tao_supervisor_interval=3,
)
result = await client.run_plan(user_input="...", config=config)
# step_records 中每步会显示 tao_used=True、tao_loops、tao_exit
```

---

## 错误处理

所有 SDK 失败均抛出 `XPlanError` 的子类。捕获基类可处理任意 SDK 错误，
捕获具体子类可做更细粒度控制。

| 异常              | 触发场景                                            |
|-------------------|-----------------------------------------------------|
| `XPlanError`      | 所有 SDK 错误的基类。                                |
| `ConnectionError` | 无法连接到 XPlan 服务。                              |
| `TimeoutError`    | 请求超时。                                           |
| `APIError`        | 服务端返回非 2xx。提供 `status_code` 与 `detail`。   |
| `ValidationError` | 响应无法解析为目标模型。                             |

```python
from xplan.sdk import XPlanClient, APIError, ConnectionError, XPlanError

try:
    result = await client.run_plan(user_input="...")
except ConnectionError:
    # 服务不可达
    raise
except APIError as exc:
    if exc.status_code == 400:
        print("请求错误：", exc.detail)
    elif exc.status_code >= 500:
        print("服务端错误：", exc.detail)
    raise
except XPlanError:
    # 兜底捕获其他 SDK 错误
    raise
```

> 注意：`xplan.sdk.ConnectionError` / `xplan.sdk.TimeoutError` 会遮蔽同名的
> Python 内建异常。若同一模块中两者都需要，请用别名导入。

## 模型 vs 字典

SDK 既接受 Pydantic 模型实例，也接受普通字典 —— 哪个方便用哪个。模型在
内部通过 `model_dump(mode="json")` 序列化，枚举与日期等会被正确处理。

```python
# 使用模型（推荐：IDE 提示与校验更佳）
from xplan.models import Plan, Goal, Context, Choice, Step

plan = Plan(
    goal=Goal(user_goal="...", success_criteria=[...]),
    context=Context(known_facts=[...]),
    choice=Choice(selected_path="...", reason="...", steps=[Step(...)]),
)
await client.verify_plan(plan)

# 使用字典（适合快速脚本）
await client.verify_plan({
    "goal": {"user_goal": "...", "success_criteria": [...]},
    "context": {"known_facts": [...]},
    "choice": {"selected_path": "...", "reason": "...", "steps": [...]},
})
```

响应默认返回解析后的 JSON 字典。若要将其校验为模型，直接使用 Pydantic：

```python
from xplan.models import OrchestratorResult

res = await client.run_plan(user_input="...")
result = OrchestratorResult.model_validate(res)
print(result.plan.goal.user_goal)
```

## 同步用法

SDK 异步优先，但可在同步代码中通过 `asyncio.run` 驱动：

```python
import asyncio
from xplan.sdk import XPlanClient

def run(user_input: str) -> dict:
    async def _run():
        async with XPlanClient() as client:
            return await client.run_plan(user_input=user_input)
    return asyncio.run(_run())

print(run("帮我优化简历"))
```

长时间运行的同步应用中，建议保持单一事件循环并复用客户端，而非每次调用
都重建。

## 实战示例

### 自定义配置的完整生命周期

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

### 手动控制：生成 → 评估 → 执行

适用于需要在各阶段之间检查或修改 Plan 的场景。

```python
async def manual_control(client: XPlanClient, goal: str):
    gen = await client.generate_plan(user_input=goal, use_iteration=True)
    plan = gen["plan"]

    verification = await client.verify_plan(plan)
    if not verification["verification"]["passed"]:
        # 迭代或修复 Plan
        ...

    executed = await client.execute_plan(plan)
    return executed["plan"]
```

### 失败恢复循环

```python
async def recover(client: XPlanClient, plan: dict, failed_step: str, error: str):
    # 1. 回溯定位根因（失败点 != 根因点）
    trace = await client.trace_failure(plan, failed_step, error)
    root = trace["result"]["root_cause_point"]

    # 2. 将失败事实标记为 invalid —— 下游事实自动变为 dirty
    if root and root.get("step_id"):
        await client.update_trust_state(root["step_id"], "invalid", reason=error)

    # 3. 渐进式回溯（动作 -> 步骤 -> 阶段 -> 全局）
    bt = await client.progressive_backtracking(
        plan, error_info=error, failure_tracing_result=trace["result"]
    )
    return bt["result"]
```

### 评估 Replan 效果

```python
async def evaluate(client: XPlanClient):
    # 前提：已通过 record_replan_event(...) 收集事件
    metrics = await client.get_replan_metrics()
    print("根因定位准确率：", metrics["root_cause_accuracy"])
    print("Replan 起点准确率：", metrics["replan_start_accuracy"])
    print("已有结果复用率：", metrics["result_reuse_rate"])
    print("Replan 恢复成功率：", metrics["replan_recovery_success_rate"])
    print("Replan 振荡率：", metrics["replan_oscillation_rate"])

    # 导出测试集用于人工标注
    test_set = await client.export_replan_test_set()
    # ... 离线标注后回导 ...
    await client.annotate_replan(annotations=[
        {"event_id": "evt-1", "root_cause_correct": True, "replan_start_correct": False},
    ])
```

---

## 相关文档

- [README_zh.md](../README_zh.md) —— 项目概览与部署。
- [API_zh.md](API_zh.md) —— 原始 REST API 参考。
- 源码：[`src/xplan/sdk/`](../src/xplan/sdk)
