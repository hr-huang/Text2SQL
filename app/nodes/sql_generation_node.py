# app/nodes/sql_generation_node.py

from app.prompts.sql_generation_prompt import (
    SQL_GENERATION_SYSTEM_PROMPT,
    build_sql_generation_user_prompt,
)
from app.schemas.state import Text2SQLState
from app.services.llm_service import LLMService


def sql_generation_node(state: Text2SQLState) -> dict:
    llm = LLMService()

    result = llm.generate_json(
        system_prompt=SQL_GENERATION_SYSTEM_PROMPT,
        user_prompt=build_sql_generation_user_prompt(
            question=state["question"],
            metrics=state.get("metrics", []),
            dimensions=state.get("dimensions", []),
            filters=state.get("filters", {}),
            time_range=state.get("time_range", {}),
            sort=state.get("sort", {}),
            limit=state.get("limit"),
            candidate_tables=state.get("candidate_tables", []),
            candidate_columns=state.get("candidate_columns", []),
            context_from_previous=state.get("context_from_previous"),
        ),
    )

    return {
        "generated_sql": result.get("sql"),
        "sql_generation_reason": result.get("reason", ""),
        "confidence": float(result.get("confidence", 0.7)),
    }