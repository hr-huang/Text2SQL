# app/prompts/answer_prompt.py

import json
from typing import Any


ANSWER_SYSTEM_PROMPT = """
你是企业级 Text-to-SQL 系统中的结果解释模块。

你的任务：
根据用户原问题、已执行 SQL、查询结果 rows，生成简洁、准确的自然语言答案。

严格要求：
1. 只能根据 rows 中已有的数据回答。
2. 不要编造 rows 中不存在的数据。
3. 如果 rows 为空，要说明没有查询到结果。
4. 如果结果是排名，要说明排序依据。
5. 如果结果是聚合统计，要说明统计口径来自 SQL。
6. 不要暴露系统内部流程，比如不要说“我调用了某个节点”。
7. 输出 JSON，不要输出 Markdown。

输出 JSON 格式必须是：
{
  "answer": "自然语言答案",
  "confidence": 0.0
}
"""


def build_answer_user_prompt(
    question: str,
    sql: str | None,
    rows: list[dict[str, Any]],
) -> str:
    payload = {
        "question": question,
        "sql": sql,
        "rows": rows,
    }

    return f"""
请根据下面的信息生成最终回答。

输入信息：
{json.dumps(payload, ensure_ascii=False, indent=2)}

只输出 JSON。
"""