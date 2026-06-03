# app/nodes/sql_repair_node.py

from app.agents.react_sql_repair_agent import ReactSQLRepairAgent
from app.schemas.state import Text2SQLState


def sql_repair_node(state: Text2SQLState) -> dict:
    agent = ReactSQLRepairAgent(max_execute_attempts=3)

    failed_sql = state.get("validated_sql") or state.get("generated_sql")

    if not failed_sql:
        return {
            "execution_result": [],
            "execution_error": "没有可修复的 SQL",
            "repair_attempts": 0,
            "repair_observations": [],
        }

    result = agent.run(
        question=state["question"],
        datasource_id=state["datasource_id"],
        failed_sql=failed_sql,
        error_message=state.get("execution_error") or "未知 SQL 执行错误",
        candidate_tables=state.get("candidate_tables", []),
        candidate_columns=state.get("candidate_columns", []),
    )

    if result["success"]:
        return {
            "repair_attempts": result["repair_attempts"],
            "repair_observations": result["observations"],
            "validated_sql": result["sql"],
            "execution_result": result["rows"],
            "execution_error": None,
        }
    else:
        return {
            "repair_attempts": result["repair_attempts"],
            "repair_observations": result["observations"],
            "execution_result": [],
            "execution_error": result["error"],
        }