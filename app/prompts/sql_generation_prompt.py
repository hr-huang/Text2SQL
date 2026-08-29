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

示例 9（多表 JOIN 串联：从"评分"到订单金额）:
  用户: 各评级的订单平均金额是多少？
  字段: reviews(review_id,product_id,rating:[1,2,3,4,5]), products(product_id,name), order_details(detail_id,order_id,product_id), orders(order_id,total_amount)
  SQL: SELECT r.rating, AVG(o.total_amount) AS avg_amount FROM reviews r JOIN products p ON r.product_id=p.product_id JOIN order_details od ON p.product_id=od.product_id JOIN orders o ON od.order_id=o.order_id GROUP BY r.rating ORDER BY r.rating
  注意: "评级/评分"对应 reviews.rating，不是 customers.vip_level。需要从 reviews 出发，串 products → order_details → orders 拿到订单金额。

示例 10（多表 JOIN 串联：退货流）:
  用户: 被退货次数最多的5个商品？
  字段: products(product_id,name), return_details(detail_id,return_id,product_id,quantity), returns(return_id,return_date)
  SQL: SELECT p.name, COUNT(r.return_id) AS return_count FROM products p JOIN return_details rd ON p.product_id=rd.product_id JOIN returns r ON rd.return_id=r.return_id GROUP BY p.product_id ORDER BY return_count DESC LIMIT 5
  注意: "退货次数"必须从 returns 主表 COUNT，不能只 JOIN return_details 就完事。

示例 11（状态过滤走事件表：物流签收）:
  用户: 各物流公司的签收率是多少？
  字段: shippers(shipper_id,name), orders(order_id,shipper_id), shipping_tracking(track_id,order_id,status:[已发货,运输中,已签收,派送失败])
  SQL: SELECT s.name, ROUND(SUM(CASE WHEN st.status='已签收' THEN 1 ELSE 0 END)*100.0/COUNT(*), 2) AS sign_rate FROM shippers s JOIN orders o ON s.shipper_id=o.shipper_id JOIN shipping_tracking st ON o.order_id=st.order_id GROUP BY s.shipper_id ORDER BY sign_rate DESC
  注意: "签收状态"在 shipping_tracking 表里，不是 orders.status。订单状态（已付款/已发货等）和物流跟踪状态是分开的两件事。

示例 12（嵌套聚合：每单多少商品）:
  用户: 平均每笔订单包含几个商品？
  字段: order_details(detail_id,order_id,product_id,quantity)
  SQL: SELECT AVG(total_qty) FROM (SELECT order_id, SUM(quantity) AS total_qty FROM order_details GROUP BY order_id)
  注意: "每笔订单包含几个"需要先按 order_id 聚合，再用 AVG。需要子查询。

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
            "前置步骤已执行完毕，结果如下：\n"
            + "\n".join(ctx_lines) + "\n\n"
            "【强制要求】本步骤是上述步骤的后续，你必须用前置结果的数据来约束本查询：\n"
            "  - 若前置结果给出的是 ID 集合（如 Top10 客户ID、Top3 品类ID），"
            "必须用 WHERE 某表.某ID IN (...) 把查询限定在这些 ID 上；\n"
            "  - 若前置结果给出的是阈值/数值，必须用它做过滤或比较；\n"
            "  - 不要重新计算前置步骤已经算出的中间结果，直接引用它给出的值；\n"
            "  - 严禁忽略前置结果而返回全量数据——那样本步骤就失去意义。\n"
            "如果前置步骤已失败，请生成你能生成的最佳 SQL，并在 reason 中注明受限之处。"
        )

    prompt += """

注意：
1. 只能使用上面列出的表和字段。不要猜测字段名。
2. 用 INNER JOIN 而非 LEFT JOIN（除非确实需要包含空值）。
3. 只返回用户问题真正需要的列。
4. 只输出 JSON，不要输出其他内容。"""

    return prompt
