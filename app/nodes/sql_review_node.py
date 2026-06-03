"""sql_review_node — 封装 SQLReviewAgent 为 LangGraph 节点（v2: 传入候选 schema）"""

from app.agents.sql_review_agent import SQLReviewAgent
from app.schemas.state import Text2SQLState


def sql_review_node(state: Text2SQLState) -> dict:
    """对生成的 SQL 做语义审查，注入 RAG 候选 schema 做逐列核对"""
    question = state["question"]
    sql = state.get("generated_sql") or ""

    if not sql:
        return {"sql_review_passed": False, "sql_review_issues": ["SQL 为空，跳过审查"]}

    agent = SQLReviewAgent()
    result = agent.review(
        question=question,
        sql=sql,
        datasource_id=state["datasource_id"],
        candidate_tables=state.get("candidate_tables", []),
        candidate_columns=state.get("candidate_columns", []),
        candidate_relationships=state.get("candidate_relationships"),
    )

    return {
        "generated_sql": result["sql"],          # 可能是修正后的 SQL
        "sql_review_passed": result["approved"],
        "sql_review_issues": result["issues"],
        "sql_review_confidence": result["confidence"],
    }
