# app/utils/trace_utils.py

from typing import Any

from app.schemas.state import Text2SQLState


def add_trace(
    state: Text2SQLState,
    node: str,
    output: dict[str, Any],
) -> Text2SQLState:
    """
    给 state 追加一条调试记录。

    node:
        当前执行的节点名。

    output:
        当前节点产生的重要结果。
        不建议把整个 state 全塞进去，否则太乱。
    """

    if "debug_trace" not in state:
        state["debug_trace"] = []

    state["debug_trace"].append({
        "step": len(state["debug_trace"]) + 1,
        "node": node,
        "output": output,
    })

    return state