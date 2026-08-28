# app/utils/trace_utils.py
"""Debug trace helpers for LangGraph nodes.

Each trace entry records: node name, wall-clock duration, delta token usage,
output summary, optional tool calls and error. Front-end reads debug_trace
to render the workflow visualization with cost + token overlays.
"""

import time
from typing import Any

from app.schemas.state import Text2SQLState


def add_trace(
    state: Text2SQLState,
    node: str,
    output: dict[str, Any] | None = None,
    *,
    duration_ms: int | None = None,
    prompt_tokens_delta: int | None = None,
    completion_tokens_delta: int | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    error: str | None = None,
) -> Text2SQLState:
    """Append a trace entry to state.debug_trace.

    Output-only mode (legacy): pass only node + output.
    Full mode: pass duration_ms / token deltas / tool_calls / error.
    """
    if "debug_trace" not in state:
        state["debug_trace"] = []

    entry: dict[str, Any] = {
        "step": len(state["debug_trace"]) + 1,
        "node": node,
        "timestamp": time.time(),
    }
    if duration_ms is not None:
        entry["duration_ms"] = duration_ms
    if prompt_tokens_delta or completion_tokens_delta:
        entry["token_usage"] = {
            "prompt": prompt_tokens_delta or 0,
            "completion": completion_tokens_delta or 0,
            "total": (prompt_tokens_delta or 0) + (completion_tokens_delta or 0),
        }
    if tool_calls:
        entry["tool_calls"] = tool_calls
    if error:
        entry["error"] = error
    if output:
        # Strip empty values for readability.
        entry["output"] = {
            k: v for k, v in output.items()
            if v not in (None, "", [], {})
        }

    state["debug_trace"].append(entry)
    return state