# app/nodes/decompose_node.py

from app.prompts.decompose_prompt import (
    DECOMPOSE_SYSTEM_PROMPT,
    build_decompose_user_prompt,
)
from app.schemas.state import Text2SQLState
from app.services.llm_service import LLMService


def decompose_node(state: Text2SQLState) -> dict:
    """LLM 拆解复杂问题为子问题序列。

    classify_node 判 complex → decompose 拆解
    → orchestrator 按依赖顺序执行 → merge 汇总。

    拆解前先获取候选表名，注入 prompt 让 LLM 知道有哪些表可用。
    """
    question = state["question"]

    # 获取候选表名（让 decompose 知道有哪些表）
    from app.services.schema_service import SchemaService
    schema_svc = SchemaService()
    schema = schema_svc.search_relevant_schema(
        datasource_id=state["datasource_id"],
        question=question,
    )
    table_names = [t["table_name"] for t in schema.get("candidate_tables", [])]

    # 枚举/状态字段的真实取值必须给到 decompose。
    # 不传的话 LLM 会在子问题描述里编造值（如把中文 '已签收' 写成 'delivered'），
    # 下游 sql_generation 照着错误描述生成 SQL，整条链路就错了。
    enum_hints: list[tuple[str, str, list]] = []
    for col in schema.get("candidate_columns", []):
        samples = col.get("sample_values") or []
        if not samples or len(samples) > 10:
            continue  # 高基数字段值太多，不值得塞进 prompt
        if all(isinstance(v, str) for v in samples):
            enum_hints.append(
                (col["table_name"], col["column_name"], samples)
            )

    llm = LLMService()

    result = llm.generate_json(
        system_prompt=DECOMPOSE_SYSTEM_PROMPT,
        user_prompt=build_decompose_user_prompt(question, table_names, enum_hints),
    )

    can_single_sql = bool(result.get("can_single_sql", True))
    sub_questions = result.get("sub_questions", [])

    # 强制编排模式（评测用）：只要确实拆出了多个子问题就走 orchestrator，
    # 忽略 LLM 的 can_single_sql 判断。生产环境不设此标志，保留智能判断。
    if state.get("force_decompose"):
        return {"sub_questions": sub_questions if len(sub_questions) >= 2 else []}

    if can_single_sql or not sub_questions:
        return {"sub_questions": []}

    return {"sub_questions": sub_questions}
