"""Live end-to-end TAO test with a real LLM.

Scenario: resume project-experience optimization.
Requires a valid API_KEY in the environment.

The TAO loop demonstrates the full Think -> Action -> Observation cycle:
1. Round 1: Think selects read_resume -> Action reads raw resume -> Observation extracts facts
2. Round 2: Think selects write_optimized_resume -> Action outputs the optimized text -> Observation confirms
3. Round 3: Think decides finish (success criteria satisfied)
"""

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

from xtao.models import ActionCandidate, ActionType, TAOExit
from xtao.services import LLMService
from xtao.engine import TAOEngine
from xtao.engine.tao_action_runtime import TAOActionRuntime
from xtao.evaluation import TAOEvaluator

load_dotenv()

# Enable INFO logging so we can see TAO loop decisions in real time
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("test_tao_live")


async def main() -> None:
    """Run TAO loop live for a resume optimization micro-task."""
    api_key = os.getenv("API_KEY")
    if not api_key:
        print("SKIP: API_KEY not set")
        return

    llm = LLMService(
        api_base=os.getenv("BASE_URL", "https://api.siliconflow.cn/v1"),
        api_key=api_key,
        model=os.getenv("FLASH_LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash"),
        timeout=120.0,
    )

    # Tool 1: read the user's raw project description
    async def read_resume(params: dict) -> str:
        return (
            "项目：电商订单系统\n"
            "技术栈：Java, Spring Boot, MySQL, Redis\n"
            "业务规模：日均 10 万单\n"
            "个人贡献：负责订单核心接口开发与性能优化"
        )

    # Tool 2: write the optimized resume (simply returns the provided content)
    async def write_optimized_resume(params: dict) -> str:
        content = params.get("content", "")
        if not content:
            return "ERROR: empty content"
        return f"优化后的项目经历:\n{content}"

    runtime = TAOActionRuntime()
    runtime.register_executor("read_resume", read_resume)
    runtime.register_executor("write_optimized_resume", write_optimized_resume)

    engine = TAOEngine(
        llm_service=llm,
        action_runtime=runtime,
        supervisor_interval=0,  # disable sync outer loop for the live test
        supervisor_interval_seconds=0,  # disable async outer loop too
    )

    candidates = [
        ActionCandidate(
            name="read_resume",
            type=ActionType.TOOL_CALL,
            description="读取用户原始项目经历，获取项目名称、技术栈、业务规模和个人贡献等信息",
        ),
        ActionCandidate(
            name="write_optimized_resume",
            type=ActionType.TOOL_CALL,
            description="输出优化后的简历项目经历文本，需在 content 参数中提供完整的优化后内容",
        ),
    ]

    user_input = "帮我优化简历中的项目经历，使其适合 Java 后端面试"
    logger.info("Starting TAO live test: %s", user_input)

    result = await engine.run(
        user_input=user_input,
        candidate_actions=candidates,
        max_loops=6,
        max_time=180.0,
    )

    # Print summary
    print(f"Exit: {result.exit_type.value}")
    print(f"Loops: {result.used_loops}")
    print(f"Actions: {result.total_actions}")
    print(f"Final output: {(result.final_output or '')[:500]}")
    print(f"Clarify message: {(result.clarify_message or '')[:500]}")
    print(f"Exit reason: {result.exit_reason[:200]}")

    # Print exit history for debugging
    for i, rec in enumerate(result.exit_history):
        print(f"  History[{i}]: exit={rec.exit_type.value}, overridden={rec.overridden}, reason={rec.reason[:100]}")

    # Record evaluation event
    evaluator = TAOEvaluator(llm_service=llm)
    event = evaluator.record_from_result(
        result,
        task_id="resume_optimization",
        user_input=user_input,
    )
    print(f"Evaluation event recorded: {event.event_id}")

    # A non-interrupt exit is considered success for this smoke test
    assert result.exit_type in (
        TAOExit.FINISH,
        TAOExit.CLARIFY,
    ), f"Unexpected exit: {result.exit_type.value}, reason: {result.exit_reason}"

    logger.info("TAO live test PASSED: exit=%s", result.exit_type.value)


if __name__ == "__main__":
    asyncio.run(main())
