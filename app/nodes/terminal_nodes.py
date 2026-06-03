# app/nodes/terminal_nodes.py
"""Terminal nodes for early-exit paths in the Text2SQL workflow.

These handle three non-happy-path scenarios that were previously inline
code blocks in graph.py:

1. Non-data questions (chit-chat, general knowledge)
2. SQL that fails security validation
3. SQL execution failure after all repair attempts exhausted
"""

from app.schemas.state import Text2SQLState


def answer_non_data_node(state: Text2SQLState) -> dict:
    """Handle non-data questions — polite refusal with intent info."""
    return {
        "generated_sql": None,
        "validated_sql": None,
        "execution_result": [],
        "execution_error": None,
        "final_answer": (
            f"我判断这个问题不是数据查询问题。"
            f"意图类型：{state.get('intent', 'unknown')}。"
            f"原因：{state.get('intent_reason', '')}"
        ),
        "confidence": 0.8,
        "warnings": [],
    }


def answer_validation_failed_node(state: Text2SQLState) -> dict:
    """Handle SQL validation failure — report the error without executing."""
    return {
        "execution_result": [],
        "execution_error": None,
        "final_answer": (
            "SQL 已生成，但没有通过安全校验，因此不会执行。\n\n"
            f"生成的 SQL：\n{state.get('generated_sql', '')}\n\n"
            f"校验失败原因：{state.get('sql_validation_error', '')}\n\n"
            "当前版本只对'执行失败'的 SQL 进入 ReAct 修复。"
        ),
        "warnings": [
            "sql validation failed, execution skipped",
            *state.get("sql_validation_warnings", []),
        ],
    }


def answer_exec_failed_node(state: Text2SQLState) -> dict:
    """Handle SQL execution failure after all repair attempts exhausted."""
    return {
        "final_answer": (
            "SQL 执行失败，并且 ReAct 修复后仍未成功。\n\n"
            f"最后的 SQL：\n{state.get('validated_sql') or state.get('generated_sql', '')}\n\n"
            f"失败原因：{state.get('execution_error', '')}\n\n"
            f"修复尝试次数：{state.get('repair_attempts', 0)}\n"
            f"修复过程：{state.get('repair_observations', [])}"
        ),
        "warnings": [
            "sql execution failed after repair",
            *state.get("sql_validation_warnings", []),
        ],
    }
