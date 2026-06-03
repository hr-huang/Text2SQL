# app/prompts/classify_prompt.py

CLASSIFY_SYSTEM_PROMPT = """
你判断用户的数据查询问题是「简单」还是「复杂」。

简单（simple）：
  - 一句 SELECT + JOIN + GROUP BY + ORDER BY 就能回答
  - 只有一个统计目标（单个 COUNT/SUM/AVG）
  - 例如："一共有多少位艺术家？""每个国家的客户数量？""2010年每个月的销售额？"

复杂（complex）：
  - 包含"和/以及/分别"，且有多个独立的统计维度
    例如："过去一年每个月的新增客户数和订单量？" → 新增客户数(来自customers) + 订单量(来自orders)，两个不同表的不同指标
  - 需要子查询或窗口函数（"高于平均""排名前X中的Y""除了...之外"）
  - 必须先查出中间结果，再基于中间结果查第二步
  - 例如："消费最高的10个客户分别买了哪些音乐类型？""比平均消费额高的客户住在哪些城市？"

如果用户问题完全不涉及数据查询（闲聊、问候等），返回 not_data。

输出 JSON：
{
  "complexity": "simple" | "complex" | "not_data",
  "reason": "一句话说明判断理由"
}
"""


def build_classify_user_prompt(question: str) -> str:
    return f"问题：{question}"
