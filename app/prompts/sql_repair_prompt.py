# app/prompts/sql_repair_prompt.py

import json
from typing import Any

SQL_REPAIR_SYSTEM_PROMPT = """
你是 SQL 修复 Agent，通过 Function Calling 选择下一步行动。

你有四个可用函数：
- schema_lookup: 查询某张表的字段结构。当报错提示"字段不存在"或"表不存在"时优先调用
- rewrite_sql: 根据观察结果改写 SQL。修正后调用此函数提交新 SQL
- execute_sql: 执行当前 SQL。改写完成后调用此函数验证修复结果
- give_up: 多次修复失败后放弃，必须提供原因

修复策略：
1. 如果是字段/表名错误 → schema_lookup 查正确字段 → rewrite_sql → execute_sql
2. 如果是语法错误 → 直接 rewrite_sql → execute_sql
3. 如果执行成功 → 结束
4. 如果 3 次 execute_sql 都失败 → give_up

注意：只能生成 SELECT 查询，禁止修改数据。
"""


def build_sql_repair_user_prompt(
    question: str,
    datasource_id: str,
    current_sql: str,
    last_error: str,
    candidate_tables: list[dict[str, Any]],
    candidate_columns: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    execute_attempts: int,
) -> str:
    payload = {
        "question": question,
        "datasource_id": datasource_id,
        "current_sql": current_sql,
        "last_error": last_error,
        "candidate_tables": [t["table_name"] for t in candidate_tables],
        "observations_history": observations,
        "execute_attempts": f"{execute_attempts}/3",
    }

    return (
        f"当前状态：\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        f"请选择下一步要调用的函数。"
    )
