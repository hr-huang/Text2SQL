"""ReAct SQL Repair Agent — 基于 OpenAI Function Calling 的工具调度"""
from typing import Any

from app.prompts.sql_repair_prompt import (
    SQL_REPAIR_SYSTEM_PROMPT,
    build_sql_repair_user_prompt,
)
from app.services.llm_service import LLMService
from app.tools.schema_lookup_tool import SchemaLookupTool
from app.tools.execute_sql_tool import ExecuteSQLTool


# ── Function Calling 工具定义 ──
REPAIR_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "schema_lookup",
            "description": "查询指定数据源中某张表的完整字段结构（字段名、类型、样本值）",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "要查询的表名",
                    }
                },
                "required": ["table_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rewrite_sql",
            "description": "根据错误信息和观察结果，改写当前 SQL，修正错误",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "修正后的 SELECT 查询语句",
                    }
                },
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_sql",
            "description": "执行当前 SQL，校验通过后运行并返回结果。调用此函数前应先确保 SQL 已修正",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "give_up",
            "description": "判断当前错误无法修复，放弃修复。仅在多次尝试失败后使用",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "放弃修复的原因",
                    }
                },
                "required": ["reason"],
            },
        },
    },
]


class ReactSQLRepairAgent:
    """基于 Function Calling 的 ReAct SQL 修复 Agent。

    与旧版区别：不再让 LLM 返回 {"action":"xxx"} 字符串再 if-else 匹配，
    而是通过 OpenAI 原生 Function Calling 让 LLM 直接选择工具并生成参数。
    工具名不会拼错、参数 schema 被 API 层校验。
    """

    def __init__(self, max_execute_attempts: int = 3, max_total_calls: int = 10):
        self.llm = LLMService()
        self.max_execute_attempts = max_execute_attempts
        self.max_total_calls = max_total_calls  # 兜底：所有工具调用总数上限

        self.tools = {
            "schema_lookup": SchemaLookupTool(),
            "execute_sql": ExecuteSQLTool(),
        }

    def run(
        self,
        question: str,
        datasource_id: str,
        failed_sql: str,
        error_message: str,
        candidate_tables: list[dict[str, Any]],
        candidate_columns: list[dict[str, Any]],
    ) -> dict[str, Any]:
        current_sql = failed_sql
        last_error = error_message
        execute_attempts = 0
        total_calls = 0
        observations: list[dict[str, Any]] = []

        while execute_attempts < self.max_execute_attempts and total_calls < self.max_total_calls:
            total_calls += 1
            # ① LLM 通过 Function Calling 选择下一步
            decision = self.llm.generate_with_tools(
                system_prompt=SQL_REPAIR_SYSTEM_PROMPT,
                user_prompt=build_sql_repair_user_prompt(
                    question=question,
                    datasource_id=datasource_id,
                    current_sql=current_sql,
                    last_error=last_error,
                    candidate_tables=candidate_tables,
                    candidate_columns=candidate_columns,
                    observations=observations,
                    execute_attempts=execute_attempts,
                ),
                tools=REPAIR_TOOLS,
                tool_choice="auto",
            )

            tool_name = decision.get("tool_name")
            args = decision.get("arguments", {})

            if not tool_name:
                # LLM 没选工具（可能返回了纯文本），重试
                last_error = f"LLM 未选择工具，回复: {decision.get('content', '')[:200]}"
                continue

            # ② 执行选中的工具
            if tool_name == "schema_lookup":
                table_name = args.get("table_name")
                if not table_name:
                    observations.append({"tool": tool_name, "error": "缺少 table_name"})
                    last_error = "schema_lookup 缺少 table_name"
                    continue

                result = self.tools["schema_lookup"].run(
                    datasource_id=datasource_id, table_name=table_name
                )
                observations.append({
                    "tool": tool_name,
                    "args": args,
                    "result": result,
                })

            elif tool_name == "rewrite_sql":
                new_sql = args.get("sql")
                if not new_sql:
                    observations.append({"tool": tool_name, "error": "缺少 sql"})
                    last_error = "rewrite_sql 缺少 sql"
                    continue

                current_sql = new_sql
                observations.append({
                    "tool": tool_name,
                    "args": args,
                    "result": {"current_sql": current_sql},
                })

            elif tool_name == "execute_sql":
                result = self.tools["execute_sql"].run(
                    datasource_id=datasource_id,
                    sql=current_sql,
                    candidate_tables=candidate_tables,
                    candidate_columns=candidate_columns,
                    max_rows=500,
                )
                execute_attempts += 1
                observations.append({
                    "tool": tool_name,
                    "args": {"sql": current_sql},
                    "result": result,
                })

                if result["success"]:
                    return {
                        "success": True,
                        "sql": result["validated_sql"],
                        "rows": result["rows"],
                        "error": None,
                        "repair_attempts": execute_attempts,
                        "observations": observations,
                    }
                last_error = result["error"]

            elif tool_name == "give_up":
                reason = args.get("reason", "Agent 判断无法修复")
                observations.append({
                    "tool": tool_name,
                    "args": args,
                    "result": reason,
                })
                return {
                    "success": False,
                    "sql": current_sql,
                    "rows": [],
                    "error": reason,
                    "repair_attempts": execute_attempts,
                    "observations": observations,
                }

            else:
                observations.append({"tool": tool_name, "error": f"未知工具: {tool_name}"})
                last_error = f"调用了未知工具: {tool_name}"

        return {
            "success": False,
            "sql": current_sql,
            "rows": [],
            "error": f"达到最大修复次数 {self.max_execute_attempts}，仍未成功",
            "repair_attempts": execute_attempts,
            "observations": observations,
        }
