# app/nodes/answer_node.py

from app.prompts.answer_prompt import (
    ANSWER_SYSTEM_PROMPT,
    build_answer_user_prompt,
)
from app.schemas.state import Text2SQLState
from app.services.llm_service import LLMService


def answer_node(state: Text2SQLState) -> dict:
    rows = state.get("execution_result", [])

    if not rows:
        return {
            "final_answer": "没有查询到符合条件的数据。",
            "confidence": 0.6,
        }

    llm = LLMService()

    result = llm.generate_json(
        system_prompt=ANSWER_SYSTEM_PROMPT,
        user_prompt=build_answer_user_prompt(
            question=state["question"],
            sql=state.get("validated_sql"),
            rows=rows,
        ),
    )

    return {
        "final_answer": result.get("answer", "查询完成，但结果解释生成失败。"),
        "confidence": float(result.get("confidence", state.get("confidence", 0.7))),
    }