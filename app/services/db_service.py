# app/services/db_service.py

import sqlite3
from pathlib import Path
from typing import Any


class DBService:
    def __init__(self):
        project_root = Path(__file__).resolve().parents[2]

        self.datasource_map = {
            "ecommerce_db": project_root / "data" / "ecommerce.db",
        }

    def execute_readonly_sql(
        self,
        datasource_id: str,
        sql: str,
        max_rows: int = 500,
    ) -> dict[str, Any]:
        db_path = self.datasource_map.get(datasource_id)

        if db_path is None:
            return {
                "success": False,
                "rows": [],
                "error": (
                    f"未知数据源：{datasource_id}；"
                    f"当前已配置数据源：{list(self.datasource_map.keys())}"
                ),
            }

        if not db_path.exists():
            return {
                "success": False,
                "rows": [],
                "error": f"数据库文件不存在：{db_path}",
            }

        try:
            safe_sql = self._ensure_limit(sql, max_rows)

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row

            cursor = conn.execute(safe_sql)
            rows = [dict(row) for row in cursor.fetchall()]

            conn.close()

            return {
                "success": True,
                "rows": rows,
                "error": None,
            }

        except Exception as e:
            return {
                "success": False,
                "rows": [],
                "error": str(e),
            }

    def _ensure_limit(self, sql: str, max_rows: int) -> str:
        """用 sqlglot AST 遍历精确检查 SQL 是否已有 LIMIT"""
        import sqlglot
        from sqlglot import exp
        try:
            parsed = sqlglot.parse(sql, read="sqlite")
            if not parsed:
                return f"{sql.strip().rstrip(';')} LIMIT {max_rows}"
            for node in parsed[0].walk():
                if isinstance(node, exp.Limit):
                    return sql  # 已有 LIMIT
        except Exception:
            pass
        return sql.strip().rstrip(";") + f" LIMIT {max_rows}"