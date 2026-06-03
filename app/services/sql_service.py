# app/services/sql_service.py

from typing import Any
import sqlglot
from sqlglot import exp


class SQLService:
    """
    SQLService 负责 SQL 相关的底层能力。

    当前负责：
    1. 判断 SQL 是否只读
    2. 基于 AST 判断 SQL 是否包含危险操作
    3. 判断 SQL 是否只使用候选表
    4. 对执行层提供规范化 SQL 和 warning
    """

    BLOCKED_EXPRESSIONS = (
        exp.Insert,
        exp.Update,
        exp.Delete,
        exp.Drop,
        exp.Create,
        exp.Alter,
        exp.Command,
    )

    def validate_sql(
        self,
        sql: str | None,
        candidate_tables: list[dict[str, Any]],
        candidate_columns: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not sql or not sql.strip():
            return {
                "valid": False,
                "error": "SQL 为空",
                "warnings": [],
                "normalized_sql": None,
            }

        try:
            parsed_list = sqlglot.parse(sql, read="sqlite")
        except Exception as e:
            return {
                "valid": False,
                "error": f"SQL 解析失败：{str(e)}",
                "warnings": [],
                "normalized_sql": None,
            }

        if len(parsed_list) != 1:
            return {
                "valid": False,
                "error": "只允许一条 SQL，禁止多语句",
                "warnings": [],
                "normalized_sql": None,
            }

        parsed = parsed_list[0]

        blocked_node = self._find_blocked_expression(parsed)
        if blocked_node:
            return {
                "valid": False,
                "error": f"SQL 包含危险操作：{blocked_node.key.upper()}",
                "warnings": [],
                "normalized_sql": None,
            }

        if not isinstance(parsed, exp.Select):
            return {
                "valid": False,
                "error": "只允许 SELECT 查询",
                "warnings": [],
                "normalized_sql": None,
            }

        used_tables = self._extract_tables(parsed)
        cte_names = self._extract_cte_names(parsed)
        used_tables = used_tables - cte_names
        allowed_tables = {
            table["table_name"]
            for table in candidate_tables
        }

        unknown_tables = used_tables - allowed_tables

        if unknown_tables:
            return {
                "valid": False,
                "error": f"SQL 使用了不在候选表中的表：{list(unknown_tables)}",
                "warnings": [],
                "normalized_sql": None,
            }

        # 注意：不再做字段级检查。
        # Review Agent 已逐列核对（含 check_schema 查全量表确认列存在性），
        # validate 重复检查字段会导致不一致：Review 确认存在的列可能不在候选字段中

        normalized_sql = parsed.sql(dialect="sqlite")

        warnings = []

        if not parsed.find(exp.Limit):
            warnings.append("SQL 没有 LIMIT，后续执行时建议限制返回行数。")

        return {
            "valid": True,
            "error": None,
            "warnings": warnings,
            "normalized_sql": normalized_sql,
        }

    def _find_blocked_expression(self, parsed):
        for node in parsed.walk():
            if isinstance(node, self.BLOCKED_EXPRESSIONS):
                return node
        return None

    def _extract_tables(self, parsed) -> set[str]:
        tables = set()

        for table in parsed.find_all(exp.Table):
            tables.add(table.name)

        return tables

    def _extract_cte_names(self, parsed) -> set[str]:
        names = set()

        for cte in parsed.find_all(exp.CTE):
            if cte.alias:
                names.add(cte.alias)

        return names

    def _extract_columns(self, parsed) -> set[str]:
        columns = set()

        for column in parsed.find_all(exp.Column):
            columns.add(column.name)

        return columns

    def _extract_aliases(self, parsed) -> set[str]:
        aliases = set()

        for alias in parsed.find_all(exp.Alias):
            aliases.add(alias.alias)

        return aliases
