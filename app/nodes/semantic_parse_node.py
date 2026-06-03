# app/nodes/semantic_parse_node.py

from app.prompts.semantic_parse_prompt import (
    SEMANTIC_PARSE_SYSTEM_PROMPT,
    build_semantic_parse_user_prompt,
)
from app.schemas.state import Text2SQLState
from app.services.llm_service import LLMService


def semantic_parse_node(state: Text2SQLState) -> dict:
    question = state["question"]

    llm = LLMService()

    result = llm.generate_json(
        system_prompt=SEMANTIC_PARSE_SYSTEM_PROMPT,
        user_prompt=build_semantic_parse_user_prompt(question),
    )

    return {
        "metrics": result.get("metrics", []),
        "dimensions": result.get("dimensions", []),
        "filters": result.get("filters", {}),
        "time_range": result.get("time_range", {}),
        "sort": result.get("sort", {}),
        "limit": result.get("limit"),
    }