"""orchestrator — 复杂问题编排执行，复用所有 graph 节点（含 Review & Repair Agent）"""

from app.nodes.schema_retrieval_node import schema_retrieval_node
from app.nodes.semantic_parse_node import semantic_parse_node
from app.nodes.sql_generation_node import sql_generation_node
from app.nodes.sql_review_node import sql_review_node
from app.nodes.sql_validation_node import sql_validation_node
from app.nodes.sql_execution_node import sql_execution_node
from app.nodes.sql_repair_node import sql_repair_node
from app.schemas.state import Text2SQLState
from app.services.llm_service import LLMService

# ── Merge prompt ──

MERGE_SYSTEM_PROMPT = """
你是数据分析师。用户问了一个复杂问题，系统拆成了多个子问题并执行。
现在汇总所有子问题结果，用自然语言回答用户的原始问题。
要求：清晰完整、数据具体、失败步骤如实说明。输出 JSON：{"answer":"...","confidence":0.0}
"""


def _build_merge_user_prompt(original_question: str, sub_results: list[dict]) -> str:
    steps_text = []
    for i, r in enumerate(sub_results, 1):
        status = "OK" if not r.get("error") else f"FAIL: {r['error']}"
        steps_text.append(
            f"Step{i}: {r['question']}\n  SQL: {r.get('sql','N/A')}\n  Status: {status}\n  Rows: {len(r.get('rows',[]))}"
        )
    return f"Original: {original_question}\n\nResults:\n" + "\n\n".join(steps_text) + "\n\nSummarize."


def _topological_sort(sub_questions: list[dict]) -> list[dict]:
    sorted_list = []
    remaining = list(sub_questions)
    resolved: set[int] = set()
    while remaining:
        ready = [q for q in remaining if all(d in resolved for d in q.get("depends_on", []))]
        if not ready:
            sorted_list.extend(remaining)
            break
        for q in ready:
            sorted_list.append(q)
            resolved.add(q["id"])
            remaining.remove(q)
    return sorted_list


def orchestrator_node(state: Text2SQLState) -> dict:
    sub_questions = state.get("sub_questions", [])
    if not sub_questions:
        return {}

    llm = LLMService()
    sorted_questions = _topological_sort(sub_questions)
    sub_results: list[dict] = []
    context_entries: list[dict] = []

    for sub_q in sorted_questions:
        # ═══ 复用 graph 节点——和简单路径完全一致 ═══

        # ① schema_retrieval（为每个子问题单独检索）
        schema_state = schema_retrieval_node({
            **state,
            "question": sub_q["question"],
        })
        # ② semantic_parse
        semantic_state = semantic_parse_node({
            **state,
            "question": sub_q["question"],
        })
        # ③ sql_generation（注入前序上下文）
        sql_state = sql_generation_node({
            **state,
            "question": sub_q["question"],
            "metrics": semantic_state.get("metrics", []),
            "dimensions": semantic_state.get("dimensions", []),
            "filters": semantic_state.get("filters", {}),
            "time_range": semantic_state.get("time_range", {}),
            "sort": semantic_state.get("sort", {}),
            "limit": semantic_state.get("limit"),
            "candidate_tables": schema_state.get("candidate_tables", []),
            "candidate_columns": schema_state.get("candidate_columns", []),
            "context_from_previous": context_entries if context_entries else None,
        })
        # ④ sql_review（Review Agent 审查语义，传入候选 schema）
        review_state = sql_review_node({
            **state,
            "question": sub_q["question"],
            "generated_sql": sql_state.get("generated_sql"),
            "candidate_tables": schema_state.get("candidate_tables", []),
            "candidate_columns": schema_state.get("candidate_columns", []),
            "candidate_relationships": schema_state.get("candidate_relationships", []),
        })
        # ⑤ validate
        validate_state = sql_validation_node({
            **state,
            "generated_sql": review_state.get("generated_sql"),
            "candidate_tables": schema_state.get("candidate_tables", []),
            "candidate_columns": schema_state.get("candidate_columns", []),
        })
        # ⑥ execute
        exec_state = sql_execution_node({
            **state,
            "validated_sql": validate_state.get("validated_sql"),
        })
        # ⑦ repair（执行失败 → 走 ReAct Repair Agent，最多重试 3 次）
        retry_count = 0
        while exec_state.get("execution_error") and retry_count < 3:
            retry_count += 1
            repair_state = sql_repair_node({
                **state,
                "question": sub_q["question"],
                "validated_sql": validate_state.get("validated_sql"),
                "generated_sql": review_state.get("generated_sql"),
                "execution_error": exec_state.get("execution_error"),
                "candidate_tables": schema_state.get("candidate_tables", []),
                "candidate_columns": schema_state.get("candidate_columns", []),
                "repair_attempts": retry_count,
            })
            exec_state = sql_execution_node({
                **state,
                "validated_sql": repair_state.get("validated_sql"),
            })

        # ═══ 记录结果 ═══
        step_result = {
            "sub_id": sub_q["id"],
            "question": sub_q["question"],
            "sql": exec_state.get("validated_sql") or review_state.get("generated_sql"),
            "rows": exec_state.get("execution_result", []),
            "error": exec_state.get("execution_error"),
        }
        sub_results.append(step_result)

        if not exec_state.get("execution_error"):
            context_entries.append({
                "step": sub_q["id"],
                "question": sub_q["question"],
                "sql": step_result["sql"],
                "result_summary": str(exec_state.get("execution_result", [])[:5]),
            })
        else:
            context_entries.append({
                "step": sub_q["id"],
                "status": "failed",
                "error": exec_state["execution_error"],
            })

    # ═══ Reflection + Merge ═══
    failures = {r["sub_id"] for r in sub_results if r.get("error")}
    if failures:
        for sq in sorted_questions:
            if set(sq.get("depends_on", [])) & failures:
                sub_results.append({
                    "sub_id": sq["id"],
                    "question": sq["question"],
                    "sql": None,
                    "rows": [],
                    "error": f"前置步骤 {list(failures)} 失败，跳过",
                })

    merge_result = llm.generate_json(
        system_prompt=MERGE_SYSTEM_PROMPT,
        user_prompt=_build_merge_user_prompt(state["question"], sub_results),
    )

    return {
        "sub_results": sub_results,
        "final_answer": merge_result.get("answer", "Failed to merge."),
        "confidence": float(merge_result.get("confidence", 0.8)),
        "generated_sql": None,
        "validated_sql": None,
        "execution_result": [],
        "execution_error": None,
    }
