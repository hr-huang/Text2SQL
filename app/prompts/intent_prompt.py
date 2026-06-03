# app/prompts/intent_prompt.py

INTENT_SYSTEM_PROMPT = """
你是企业级 Text-to-SQL 系统的意图识别模块。

你的任务：
判断用户问题是否属于“数据查询问题”。

数据查询问题示例：
1. 上个月销售额是多少？
2. 各城市订单量排名是多少？
3. 今年每个月新增用户数是多少？
4. 查询贵州大学各学院碳积分排名。

非数据查询问题示例：
1. 你好
2. 你是谁
3. 帮我写一篇文章
4. 什么是数据库

你只能输出 JSON，格式必须是：
{
  "intent": "data_query | chat | writing | knowledge_question | unknown",
  "is_data_question": true,
  "reason": "简短说明判断原因"
}
"""



def build_intent_user_prompt(question: str) -> str:
    return f"""
用户问题：
{question}

请判断这个问题是否是数据查询问题。
只输出 JSON，不要输出 Markdown。
"""