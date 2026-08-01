"""测试 G4C Plan 生成的各个步骤。"""

import asyncio
import os

from dotenv import load_dotenv

from xtao.services import LLMService, RAGService
from xtao.engine import PlanGenerator
from xtao.models import Constraints

load_dotenv()


async def test():
    llm = LLMService(
        api_base=os.getenv("BASE_URL"),
        api_key=os.getenv("API_KEY"),
        model=os.getenv("FLASH_LLM_MODEL"),
        timeout=120.0,
    )
    rag = RAGService(enabled=False)
    gen = PlanGenerator(llm, rag, max_iterations=1)

    print("1. Testing Goal generation...")
    try:
        goal = await gen.generate_goal("帮我优化简历中的项目经历", "")
        print("   Goal OK:", goal.user_goal)
        print("   Criteria:", goal.success_criteria)
    except Exception as e:
        print("   Goal FAILED:", e)
        return

    print("2. Testing Context generation...")
    try:
        ctx = await gen.generate_context("", Constraints())
        print("   Context OK, known_facts:", len(ctx.known_facts))
        print("   missing_info:", len(ctx.missing_info))
    except Exception as e:
        print("   Context FAILED:", e)
        return

    print("3. Testing Choice generation...")
    try:
        choice = await gen.generate_choice(goal, ctx)
        print("   Choice OK:", choice.selected_path)
        print("   Steps:", len(choice.steps))
    except Exception as e:
        print("   Choice FAILED:", e)
        return

    print("4. Testing Checkpoint generation...")
    try:
        cps = await gen.generate_checkpoints(choice.steps)
        print("   Checkpoints OK:", len(cps), "checkpoints")
    except Exception as e:
        print("   Checkpoints FAILED:", e)
        return

    print("5. Testing Correction generation...")
    try:
        plan_dict = {
            "goal": goal.model_dump(),
            "context": ctx.model_dump(),
            "choice": choice.model_dump(),
        }
        corrs = await gen.generate_corrections(plan_dict, "")
        print("   Corrections OK:", len(corrs), "corrections")
    except Exception as e:
        print("   Corrections FAILED:", e)
        return

    print("\nALL STEPS PASSED!")


if __name__ == "__main__":
    asyncio.run(test())
