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

    llm = LLMService()

    result = llm.generate_json(
        system_prompt=DECOMPOSE_SYSTEM_PROMPT,
        user_prompt=build_decompose_user_prompt(question, table_names),
    )

    can_single_sql = bool(result.get("can_single_sql", True))
    sub_questions = result.get("sub_questions", [])

    if can_single_sql or not sub_questions:
        return {"sub_questions": []}

    return {"sub_questions": sub_questions}
