# app/nodes/intent_node.py

from app.prompts.intent_prompt import (
    INTENT_SYSTEM_PROMPT,
    build_intent_user_prompt,
)
from app.schemas.state import Text2SQLState
from app.services.llm_service import LLMService


def intent_node(state: Text2SQLState) -> dict:
    question = state["question"]

    llm = LLMService()

    result = llm.generate_json(
        system_prompt=INTENT_SYSTEM_PROMPT,
        user_prompt=build_intent_user_prompt(question),
    )

    return {
        "intent": result.get("intent", "unknown"),
        "is_data_question": bool(result.get("is_data_question", False)),
        "intent_reason": result.get("reason", ""),
    }