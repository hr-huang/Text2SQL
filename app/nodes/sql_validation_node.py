# app/nodes/sql_validation_node.py

from app.schemas.state import Text2SQLState
from app.services.sql_service import SQLService


def sql_validation_node(state: Text2SQLState) -> dict:
    sql_service = SQLService()

    result = sql_service.validate_sql(
        sql=state.get("generated_sql"),
        candidate_tables=state.get("candidate_tables", []),
        candidate_columns=state.get("candidate_columns", []),
    )

    if result["valid"]:
        return {
            "validated_sql": result["normalized_sql"],
            "sql_validation_error": None,
            "sql_validation_warnings": result.get("warnings", []),
        }
    else:
        return {
            "validated_sql": None,
            "sql_validation_error": result["error"],
            "sql_validation_warnings": result.get("warnings", []),
        }