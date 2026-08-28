# app/prompts/self_reflection_prompt.py


SELF_REFLECTION_SYSTEM_PROMPT = """
你是 Text-to-SQL 系统的自反思模块。

在 SQL 进入执行阶段前，对生成的 SQL 做一次风险自评。
你的目标：发现潜在的语义/逻辑问题，给下游校验与执行节点提供预警信息。

═══════════════════════════════════
评估维度
═══════════════════════════════════

1. **语义匹配**：SQL 是否真正回答了用户问题？有没有跑题/答偏？
2. **列歧义**：用到的列是否可能被误用（如 vip_level vs rating、status vs is_active）？
3. **聚合正确性**：GROUP BY 是否完整？聚合函数是否选对（COUNT vs SUM vs AVG）？
4. **JOIN 风险**：是否存在笛卡尔积风险？JOIN 路径是否遗漏中间表？
6. **时间边界**：时间过滤是否包含端点？用了正确的时区？
7. **空值处理**：遇到 NULL 会不会导致结果错误？
8. **LIMIT 合理性**：TopN/排名类查询是否带 LIMIT？全表扫描风险？

═══════════════════════════════════
输出 JSON
═══════════════════════════════════

{
  "risk_level": "low" | "medium" | "high",
  "issues": ["具体问题1", "具体问题2"],
  "suggestions": ["改进建议1", "改进建议2"],
  "warnings": ["给用户的提示，比如'该 SQL 涉及大表 JOIN，可能较慢'"],
  "confidence": 0.0
}

只输出 JSON，不要输出 Markdown 或解释。
"""


def build_self_reflection_user_prompt(
    question: str,
    generated_sql: str,
    candidate_tables: list[dict],
    candidate_columns: list[dict],
    sql_review_issues: list[str] | None = None,
) -> str:
    import json

    cols_str = "\n".join(
        f"  {c['table_name']}.{c['column_name']} ({c.get('type','')}) "
        f"{'样本:'+str(c.get('sample_values',[])[:3]) if c.get('sample_values') else ''}"
        for c in candidate_columns
    )
    tables_str = "\n".join(
        f"  {t['table_name']}: {t.get('description','') or t.get('business_name','')}"
        for t in candidate_tables
    )

    review_note = ""
    if sql_review_issues:
        review_note = f"\n\n前置审查节点已发现的问题：\n" + "\n".join(
            f"- {x}" for x in sql_review_issues
        )

    return f"""请对下面的 SQL 做风险自评。

用户问题：
{question}

候选表：
{tables_str}

候选字段：
{cols_str}

生成的 SQL：
```sql
{generated_sql}
```{review_note}

只输出 JSON。"""