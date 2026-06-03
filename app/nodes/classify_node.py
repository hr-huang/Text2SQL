# app/nodes/classify_node.py

from app.prompts.classify_prompt import (
    CLASSIFY_SYSTEM_PROMPT,
    build_classify_user_prompt,
)
from app.schemas.state import Text2SQLState
from app.services.llm_service import LLMService


def classify_node(state: Text2SQLState) -> dict:
    llm = LLMService()

    result = llm.generate_json(
        system_prompt=CLASSIFY_SYSTEM_PROMPT,
        user_prompt=build_classify_user_prompt(state["question"]),
    )

    return {
        "complexity": result.get("complexity", "simple"),
        "complexity_reason": result.get("reason", ""),
    }
