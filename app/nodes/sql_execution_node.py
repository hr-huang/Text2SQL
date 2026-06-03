# app/nodes/sql_execution_node.py

from app.schemas.state import Text2SQLState
from app.services.db_service import DBService


def sql_execution_node(state: Text2SQLState) -> dict:
    db_service = DBService()

    validated_sql = state.get("validated_sql")

    if not validated_sql:
        return {
            "execution_result": [],
            "execution_error": "没有可执行的 validated_sql",
        }

    result = db_service.execute_readonly_sql(
        datasource_id=state["datasource_id"],
        sql=validated_sql,
        max_rows=500,
    )

    if result["success"]:
        return {
            "execution_result": result["rows"],
            "execution_error": None,
        }
    else:
        return {
            "execution_result": [],
            "execution_error": result["error"],
        }