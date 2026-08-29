# app/schemas/state.py

from typing import Any, Optional, TypedDict


class Text2SQLState(TypedDict, total=False):
    trace_id: str

    user_id: str
    question: str
    datasource_id: str
    session_id: Optional[str]

    intent: str
    is_data_question: bool
    intent_reason: str

    # 问题复杂度分类
    complexity: str
    complexity_reason: str

    # 复杂问题拆解
    sub_questions: list[dict[str, Any]]
    sub_results: list[dict[str, Any]]

    # 评测用：强制走 decompose→orchestrator，即使 LLM 认为单条 SQL 可解。
    # 生产环境不设置，保留智能判断；评测时用来衡量编排路径的成功率。
    force_decompose: bool

    # 语义解析结果
    metrics: list[str]
    dimensions: list[str]
    filters: dict[str, Any]
    time_range: dict[str, Any]
    sort: dict[str, Any]
    limit: Optional[int]

    # Schema 检索结果
    candidate_tables: list[dict[str, Any]]
    candidate_columns: list[dict[str, Any]]
    candidate_relationships: list[dict[str, Any]]

    # SQL 生成结果
    generated_sql: Optional[str]
    sql_generation_reason: str

    # SQL 审查结果
    sql_review_passed: bool
    sql_review_issues: list[str]
    sql_review_confidence: float

    # Self-reflection 自评结果
    self_reflection: dict[str, Any]

    # 复杂问题子步骤上下文（orchestrator 注入）
    context_from_previous: list[dict[str, Any]]

    # SQL 校验结果
    validated_sql: Optional[str]
    sql_validation_error: Optional[str]
    sql_validation_warnings: list[str]

    # SQL 执行结果
    execution_result: list[dict[str, Any]]
    execution_error: Optional[str]

    # SQL 修复结果
    repair_attempts: int
    repair_observations: list[dict[str, Any]]

    final_answer: str
    confidence: float
    warnings: list[str]

    # 调试轨迹
    debug_trace: list[dict[str, Any]]