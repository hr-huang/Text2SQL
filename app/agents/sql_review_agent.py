"""SQL Review Agent — 基于 Function Calling 的语义审查。

在 SQL 生成后、执行前，主动检查 SQL 是否正确回答了用户问题。
v2: 注入 RAG 候选 schema，逐列核对存在性 + 语义匹配。
"""

from typing import Any

from app.services.llm_service import LLMService
from app.tools.schema_lookup_tool import SchemaLookupTool

# ── Function Calling 工具定义 ──
REVIEW_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_schema",
            "description": "查询某张表的完整字段结构（候选 schema 只给了摘要，如需全部字段才调用）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {"type": "string", "description": "要查询的表名"}
                },
                "required": ["table_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fix_sql",
            "description": "发现 SQL 有语义问题，输出修正后的 SQL。常见问题：用错列名（vip_level≠rating）、JOIN 路径不对、时间函数写错（DATE('now') vs DATE('now','-1 month')）、漏 JOIN 关键表。",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "修正后的 SELECT 语句"},
                    "reason": {"type": "string", "description": "修正原因，要具体说明错在哪"},
                },
                "required": ["sql", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "approve_sql",
            "description": "审查通过：SQL 中所有列都在候选 schema 中存在，且语义和用户问题匹配。",
            "parameters": {
                "type": "object",
                "properties": {
                    "confidence": {"type": "number", "description": "置信度 0-1"},
                },
                "required": ["confidence"],
            },
        },
    },
]

# ── System prompt（v2：带候选 schema 逐列核对）──
REVIEW_SYSTEM_PROMPT = """
你是 SQL 语义审查 Agent。你会收到：
1. 用户问题
2. 生成的 SQL
3. 候选 schema（RAG 检索出的相关表和字段）+ 表关系

你的任务是逐列核对 SQL，判断是否真正回答了用户问题。

## 审查流程

问题 ─┬─→ 候选 schema（表和字段清单）──┐
       └─→ 生成的 SQL ──────────────────┼─→ Review Agent 逐列核对
                                         │
    ┌────────────────────────────────────┘
    │  ① 列存在性: SQL 中每列都在候选 schema 中？
    │  ② 语义匹配: 问题的关键词和 SQL 列名对应？
    │  ③ JOIN 路径: JOIN 链按候选 relationships 走？
    │  ④ 时间函数: 日期函数参数正确？
    │  ⑤ 聚合粒度: GROUP BY 和 SELECT 一致？
    ▼
  ┌─ 全部通过 → approve_sql
  └─ 有问题 → fix_sql

## 审查步骤

1. **列名存在性**: SQL 中 SELECT/JOIN/WHERE/GROUP BY/HAVING 引用的每一列，
   都必须在候选 schema 中存在。如果某列不在候选 schema 中，调用 check_schema 查看完整表结构。
   如果确实不存在 → fix_sql。

2. **列名语义匹配**: 用户问题里的关键词必须和 SQL 列名对应。
   候选 schema 给出了每张表的字段清单和描述，利用它做跨表语义比对：
   - 把用户问题中的关键概念（"评分""退货""签收"等）提取出来
   - 在候选 schema 中搜索语义最匹配的列
   - 如果 SQL 用的列和候选 schema 中语义最匹配的列不一致 → fix_sql

3. **JOIN 路径**: 多表查询的 JOIN 链是否正确。候选 relationships 给出了外键关系。
   如果 SQL JOIN 的表在候选 relationships 中没有对应关系 → 可能是 JOIN 路径错误。

4. **时间函数**: 日期函数的修饰符参数是否正确：
   - "上月/最近一个月" → 用 DATE('now','-1 month')，不能只用 DATE('now')
   - "今年/本年度" → 用 DATE('now','start of year') 或 strftime('%Y', date) = strftime('%Y','now')
   - "过去一年/最近12个月" → date >= DATE('now','-1 year')

5. **聚合粒度**: GROUP BY 的字段和 SELECT 的非聚合列要一致。
   如果 COUNT 从 JOIN 后的表做，可能会导致重复计数。

如果你不确定某个字段或表结构，先调用 check_schema 查看。
如果 SQL 有问题，调用 fix_sql 输出修正后的 SQL。
如果 SQL 没问题，调用 approve_sql。
"""


def _format_candidate_schema(
    tables: list[dict],
    columns: list[dict],
    relationships: list[dict] | None = None,
) -> str:
    """把候选 schema 格式化为紧凑文本，注入 Review Agent prompt"""
    lines = ["## 候选表"]

    # 收集每张表有哪些列
    table_cols: dict[str, list[str]] = {}
    for col in columns:
        tn = col.get("table_name", "")
        cn = col.get("column_name", "")
        if tn not in table_cols:
            table_cols[tn] = []
        table_cols[tn].append(cn)

    for t in tables:
        tn = t.get("table_name", "")
        cols = table_cols.get(tn, [])
        pk = t.get("primary_key", "")
        desc = t.get("description", "") or t.get("business_name", "")
        lines.append(f"  {tn}: {', '.join(cols[:20])}")
        if pk:
            lines.append(f"    PK={pk}")
        if desc:
            lines.append(f"    desc={desc[:80]}")

    if relationships:
        lines.append("\n## 表关系")
        for r in relationships[:10]:
            lines.append(
                f"  {r.get('left_table','')}.{r.get('left_column','')} "
                f"= {r.get('right_table','')}.{r.get('right_column','')}"
            )

    return "\n".join(lines)


def _build_review_prompt(
    question: str,
    sql: str,
    candidate_schema_text: str,
) -> str:
    return (
        f"用户问题: {question}\n\n"
        f"待审查的 SQL:\n{sql}\n\n"
        f"{candidate_schema_text}\n\n"
        f"请逐列核对：① 每列是否存在于候选 schema？② 列的语义是否和问题匹配？③ JOIN/时间函数是否正确？"
    )


class SQLReviewAgent:
    """SQL 语义审查 Agent。使用 Function Calling 循环审查。"""

    def __init__(self, max_rounds: int = 3):
        self.llm = LLMService()
        self.max_rounds = max_rounds
        self.schema_tool = SchemaLookupTool()

    def review(
        self,
        question: str,
        sql: str,
        datasource_id: str,
        candidate_tables: list[dict] | None = None,
        candidate_columns: list[dict] | None = None,
        candidate_relationships: list[dict] | None = None,
    ) -> dict[str, Any]:
        """审查 SQL，返回 {approved, sql, issues, confidence}"""
        current_sql = sql
        issues: list[str] = []
        rounds = 0

        # 把候选 schema 格式化为文本（一次构建，多轮复用）
        schema_text = _format_candidate_schema(
            candidate_tables or [],
            candidate_columns or [],
            candidate_relationships,
        )

        while rounds < self.max_rounds:
            rounds += 1
            history_text = ""
            if issues:
                history_text = "\n".join(f"上一步: {i}" for i in issues[-3:])
                history_text = f"\n\n历史记录:\n{history_text}\n"

            decision = self.llm.generate_with_tools(
                system_prompt=REVIEW_SYSTEM_PROMPT,
                user_prompt=_build_review_prompt(question, current_sql, schema_text)
                + history_text,
                tools=REVIEW_TOOLS,
                tool_choice="auto",
            )

            tool_name = decision.get("tool_name")
            args = decision.get("arguments", {})

            if tool_name == "check_schema":
                table_name = args.get("table_name", "")
                if table_name:
                    result = self.schema_tool.run(
                        datasource_id=datasource_id, table_name=table_name
                    )
                    issues.append(f"check_schema({table_name}): {result}")
                continue

            elif tool_name == "fix_sql":
                new_sql = args.get("sql", "")
                reason = args.get("reason", "")
                if new_sql:
                    current_sql = new_sql
                    issues.append(f"fix_sql: {reason}")
                continue

            elif tool_name == "approve_sql":
                return {
                    "approved": True,
                    "sql": current_sql,
                    "issues": issues,
                    "confidence": float(args.get("confidence", 0.8)),
                }

        return {
            "approved": len(issues) == 0,
            "sql": current_sql,
            "issues": issues,
            "confidence": 0.5,
        }
