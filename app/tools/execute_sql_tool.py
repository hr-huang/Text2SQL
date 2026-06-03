# app/tools/execute_sql_tool.py

from typing import Any

from app.services.db_service import DBService
from app.services.sql_service import SQLService


class ExecuteSQLTool:
    name = "execute_sql"
    description = "校验并执行只读 SQL"

    def __init__(self):
        self.db_service = DBService()
        self.sql_service = SQLService()

    def run(
        self,
        datasource_id: str,
        sql: str,
        candidate_tables: list[dict[str, Any]],
        candidate_columns: list[dict[str, Any]],
        max_rows: int = 500,
    ) -> dict[str, Any]:
        validation = self.sql_service.validate_sql(
            sql=sql,
            candidate_tables=candidate_tables,
            candidate_columns=candidate_columns,
        )

        if not validation["valid"]:
            return {
                "success": False,
                "rows": [],
                "error": f"SQL 校验失败：{validation['error']}",
                "validated_sql": None,
            }

        db_result = self.db_service.execute_readonly_sql(
            datasource_id=datasource_id,
            sql=validation["normalized_sql"],
            max_rows=max_rows,
        )

        return {
            "success": db_result["success"],
            "rows": db_result["rows"],
            "error": db_result["error"],
            "validated_sql": validation["normalized_sql"],
        }