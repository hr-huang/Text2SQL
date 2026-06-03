# app/prompts/sql_generation_prompt.py

import json
from typing import Any


SQL_GENERATION_SYSTEM_PROMPT = """
你是企业级 Text-to-SQL 系统中的 SQL 生成模块。

你的任务：
根据用户问题、候选表、候选字段，生成一条只读 SELECT SQL。

═══════════════════════════════════
核心规则（必须严格遵守）
═══════════════════════════════════

1. 只能使用候选表和候选字段中出现过的表名和字段名。禁止编造。
2. 禁止 SELECT *，必须明确列出需要的字段。
3. 只返回用户问题中真正需要的列。不要多返回无关列。
4. 禁止生成 INSERT、UPDATE、DELETE、DROP、ALTER、TRUNCATE、CREATE。
5. 涉及排名、最高、TopN 必须加 ORDER BY + LIMIT。
6. 涉及时间范围必须加时间过滤条件。
7. 用户问"数量"→ COUNT(*)，问"平均"→ AVG()，问"总和/销售额"→ SUM()。
8. GROUP BY 的字段必须和 SELECT 中的非聚合字段一致。
9. JOIN 时优先用 INNER JOIN，除非用户明确需要包含无关联数据的行。
10. 统计"有多少个X"时，直接 COUNT(*) FROM X 主表，不要从关联表去做 COUNT(DISTINCT)。
11. 订单状态枚举：待付款/已付款/已发货/已完成/已取消/已退货。
12. 只输出 JSON，不要输出 Markdown。

═══════════════════════════════════
Few-shot 示例（模仿这种风格）
═══════════════════════════════════

示例 1:
  用户: 有多少个商品？
  字段: products(product_id,name,category_id,unit_price)
  SQL: SELECT COUNT(*) AS product_count FROM products

示例 2:
  用户: 每个地区的客户数量有多少？
  字段: customers(customer_id,name,city,province,region_id), regions(region_id,name)
  SQL: SELECT r.name, COUNT(c.customer_id) FROM customers c JOIN regions r ON c.region_id=r.region_id GROUP BY r.name ORDER BY COUNT(c.customer_id) DESC

示例 3:
  用户: 女装品类的商品有多少个？
  字段: products(product_id,name,category_id), categories(category_id,name:[服装鞋帽,...])
  SQL: SELECT COUNT(*) FROM products p JOIN categories c ON p.category_id=c.category_id WHERE c.name='服装鞋帽'

示例 4:
  用户: 下单次数最多的3个客户是谁？
  字段: customers(customer_id,name), orders(order_id,customer_id)
  SQL: SELECT c.name, COUNT(o.order_id) FROM customers c JOIN orders o ON c.customer_id=o.customer_id GROUP BY c.customer_id ORDER BY COUNT(o.order_id) DESC LIMIT 3

示例 5:
  用户: 评分低于3分的商品有哪些？
  字段: products(product_id,name), reviews(product_id,rating:[5,4,3,2,1])
  SQL: SELECT p.name, AVG(r.rating) FROM products p JOIN reviews r ON p.product_id=r.product_id GROUP BY p.product_id HAVING AVG(r.rating)<3

示例 6:
  用户: 销售额超过5000元的商品有哪些？
  字段: products(product_id,name), order_details(detail_id,product_id,unit_price,quantity,discount)
  SQL: SELECT p.name, SUM(od.unit_price*od.quantity*(1-od.discount)) as total_sales FROM products p JOIN order_details od ON p.product_id=od.product_id GROUP BY p.product_id HAVING SUM(od.unit_price*od.quantity*(1-od.discount))>5000 ORDER BY total_sales DESC

示例 7:
  用户: 上个月共有多少笔订单？
  字段: orders(order_id,order_date,status)
  SQL: SELECT COUNT(*) FROM orders WHERE order_date >= DATE('now','-1 month','start of month') AND order_date < DATE('now','start of month')

示例 8:
  用户: 不同会员等级的平均订单金额？
  字段: customers(customer_id,vip_level:[普通,银卡,金卡,钻石]), orders(order_id,customer_id,total_amount)
  SQL: SELECT c.vip_level, AVG(o.total_amount) FROM customers c JOIN orders o ON c.customer_id=o.customer_id GROUP BY c.vip_level

输出 JSON 格式：
{
  "sql": "SELECT ...",
  "reason": "简短说明为什么这样生成 SQL",
  "confidence": 0.0
}
"""


def build_sql_generation_user_prompt(
    question: str,
    metrics: list[str],
    dimensions: list[str],
    filters: dict[str, Any],
    time_range: dict[str, Any],
    sort: dict[str, Any],
    limit: int | None,
    candidate_tables: list[dict[str, Any]],
    candidate_columns: list[dict[str, Any]],
    context_from_previous: list[dict[str, Any]] | None = None,
) -> str:
    # 构建简洁的字段视图：表.字段名 (样本值)
    column_lines = []
    for col in candidate_columns:
        samples = col.get("sample_values", [])
        sample_str = ", ".join(str(v) for v in samples[:3]) if samples else ""
        desc = col.get("description", "")
        extra = f" — {desc}" if desc else ""
        if sample_str:
            extra += f" 样本:[{sample_str}]"
        column_lines.append(
            f"  {col['table_name']}.{col['column_name']} ({col.get('type','')}){extra}"
        )

    payload = {
        "question": question,
        "semantic_parse": {
            "metrics": metrics,
            "dimensions": dimensions,
            "filters": filters,
            "time_range": time_range,
            "sort": sort,
            "limit": limit,
        },
        "tables": [
            {
                "table": t["table_name"],
                "purpose": t.get("description", "") or t.get("business_name", ""),
            }
            for t in candidate_tables
        ],
        "columns": "\n".join(column_lines),
    }

    prompt = f"""请根据下面的信息生成 SQL。

输入信息：
{json.dumps(payload, ensure_ascii=False, indent=2)}
"""

    # 如果有前序步骤的上下文，追加到 prompt 中
    if context_from_previous:
        ctx_lines = []
        for ctx in context_from_previous:
            if ctx.get("status") == "failed":
                ctx_lines.append(
                    f"步骤{ctx['step']}: 执行失败 ({ctx.get('error', '未知错误')})"
                    f" — 如果此步骤是你当前查询的前置依赖，请在 WHERE 条件中留占位符并说明"
                )
            else:
                ctx_lines.append(
                    f"步骤{ctx['step']} ({ctx.get('question', '')}):\n"
                    f"  SQL: {ctx.get('sql', '')}\n"
                    f"  结果摘要: {ctx.get('result_summary', '')}"
                )
        prompt += (
            "\n═══════════════════════════════════\n"
            "前置步骤的结果（你的查询可能需要引用这些数据）：\n"
            + "\n".join(ctx_lines) + "\n\n"
            "如果需要在 WHERE 条件中引用前置步骤的结果，请使用 IN (...) 语法。\n"
            "如果前置步骤已失败，请生成你能生成的最佳 SQL，并在 reason 中注明受限之处。"
        )

    prompt += """

注意：
1. 只能使用上面列出的表和字段。不要猜测字段名。
2. 用 INNER JOIN 而非 LEFT JOIN（除非确实需要包含空值）。
3. 只返回用户问题真正需要的列。
4. 只输出 JSON，不要输出其他内容。"""

    return prompt
