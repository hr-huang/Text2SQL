# app/nodes/self_reflection_node.py
"""Self-reflection node: LLM self-evaluates the generated SQL's risk.

Sits between sql_review and validate. Adds warnings to state.warnings so
front-end can surface them, but does NOT block execution — the existing
validate → execute → repair loop catches real errors.
"""

from app.prompts.self_reflection_prompt import (
    SELF_REFLECTION_SYSTEM_PROMPT,
    build_self_reflection_user_prompt,
)
from app.schemas.state import Text2SQLState
from app.services.llm_service import LLMService


def self_reflection_node(state: Text2SQLState) -> dict:
    sql = state.get("generated_sql")
    if not sql:
        return {
            "warnings": (state.get("warnings") or []) + ["[self_reflection] SQL 为空，跳过自评"],
        }

    llm = LLMService()
    result = llm.generate_json(
        system_prompt=SELF_REFLECTION_SYSTEM_PROMPT,
        user_prompt=build_self_reflection_user_prompt(
            question=state["question"],
            generated_sql=sql,
            candidate_tables=state.get("candidate_tables", []),
            candidate_columns=state.get("candidate_columns", []),
            sql_review_issues=state.get("sql_review_issues"),
        ),
    )

    risk = result.get("risk_level", "low")
    new_warnings = list(state.get("warnings") or [])
    issues = result.get("issues") or []
    suggestions = result.get("suggestions") or []
    front_warnings = result.get("warnings") or []

    if risk == "high":
        new_warnings.append(
            f"[self_reflection] SQL 自评为 high risk：{'；'.join(issues[:3]) or '具体问题见 issues'}"
        )
    elif risk == "medium" and issues:
        new_warnings.append(
            f"[self_reflection] 自评发现潜在风险：{'；'.join(issues[:2])}"
        )
    for w in front_warnings:
        new_warnings.append(f"[self_reflection] {w}")

    return {
        "self_reflection": {
            "risk_level": risk,
            "issues": issues,
            "suggestions": suggestions,
            "confidence": float(result.get("confidence", 0.7)),
        },
        "warnings": new_warnings,
    }