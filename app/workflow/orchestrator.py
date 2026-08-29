"""orchestrator — 复杂问题编排执行，复用所有 graph 节点（含 Review & Repair Agent）"""

import json

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


#: merge 时每个子问题最多把多少行实际数据喂给 LLM
MERGE_ROW_PREVIEW = 30


def _build_merge_user_prompt(original_question: str, sub_results: list[dict]) -> str:
    steps_text = []
    for i, r in enumerate(sub_results, 1):
        rows = r.get("rows") or []
        status = "OK" if not r.get("error") else f"FAIL: {r['error']}"
        # 必须带上实际数据——只给行数的话 LLM 无法回答"是哪些/分别是多少"类问题
        preview = json.dumps(rows[:MERGE_ROW_PREVIEW], ensure_ascii=False)
        truncated = (
            f"\n  (共 {len(rows)} 行，以上为前 {MERGE_ROW_PREVIEW} 行)"
            if len(rows) > MERGE_ROW_PREVIEW else ""
        )
        steps_text.append(
            f"Step{i}: {r['question']}\n"
            f"  SQL: {r.get('sql','N/A')}\n"
            f"  Status: {status}\n"
            f"  Rows: {len(rows)}\n"
            f"  Data: {preview}{truncated}"
        )
    return (
        f"Original: {original_question}\n\nResults:\n"
        + "\n\n".join(steps_text)
        + "\n\nSummarize. 用上面 Data 里的真实数据回答，不要说'无法列出'。"
    )


#: 传给下一个子问题的前序结果行数上限（覆盖 Top10/Top20 场景）
CONTEXT_ROW_PREVIEW = 20


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
    failed_steps: set[int] = set()

    for sub_q in sorted_questions:
        # 依赖的前置步骤失败 → 本步直接跳过，不执行也不浪费 LLM 调用
        failed_deps = set(sub_q.get("depends_on", [])) & failed_steps
        if failed_deps:
            sub_results.append({
                "sub_id": sub_q["id"],
                "question": sub_q["question"],
                "sql": None,
                "rows": [],
                "error": f"前置步骤 {sorted(failed_deps)} 失败，跳过",
            })
            continue

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
        # ⑤ validate：优先用 Review 后的 SQL；若被拒且 Review 改写了 SQL，
        #    回退到 sql_gen 的原始 SQL 再验一次——Review 修正不该把能跑的 SQL 改坏
        review_sql = review_state.get("generated_sql")
        raw_sql = sql_state.get("generated_sql")
        validate_state = sql_validation_node({
            **state,
            "generated_sql": review_sql,
            "candidate_tables": schema_state.get("candidate_tables", []),
            "candidate_columns": schema_state.get("candidate_columns", []),
        })
        if validate_state.get("sql_validation_error") and raw_sql and raw_sql != review_sql:
            fallback = sql_validation_node({
                **state,
                "generated_sql": raw_sql,
                "candidate_tables": schema_state.get("candidate_tables", []),
                "candidate_columns": schema_state.get("candidate_columns", []),
            })
            if not fallback.get("sql_validation_error"):
                validate_state = fallback
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
                # 修复基准用原始 SQL（Review 可能已改坏）；validate 失败时尤其如此
                "generated_sql": raw_sql or review_state.get("generated_sql"),
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
        if validate_state.get("sql_validation_error"):
            step_result["validation_error"] = validate_state["sql_validation_error"]
        sub_results.append(step_result)

        if exec_state.get("execution_error"):
            failed_steps.add(sub_q["id"])
            context_entries.append({
                "step": sub_q["id"],
                "status": "failed",
                "error": exec_state["execution_error"],
            })
        else:
            prev_rows = exec_state.get("execution_result", []) or []
            # 用 JSON 而非 Python repr，LLM 更容易解析；
            # 行数放宽到 20 以覆盖 "Top10 客户/品类" 这类需要完整 ID 列表的场景
            context_entries.append({
                "step": sub_q["id"],
                "question": sub_q["question"],
                "sql": step_result["sql"],
                "result_summary": json.dumps(
                    prev_rows[:CONTEXT_ROW_PREVIEW], ensure_ascii=False
                ) + (
                    f" ...(共 {len(prev_rows)} 行)"
                    if len(prev_rows) > CONTEXT_ROW_PREVIEW else ""
                ),
            })

    # ═══ Merge ═══
    # （依赖失败的步骤已在循环中跳过并记录占位结果，这里不再重复传播）
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
