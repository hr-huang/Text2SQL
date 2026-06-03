# app/workflow/trace_wrapper.py
"""Node wrapper that automatically records trace entries for LangGraph nodes.

In the old hand-written graph.py, add_trace() was called after every node.
With LangGraph, nodes don't control when they're called or what happens
after. This decorator wraps each node so trace recording happens inside
the node function itself — transparent to the graph definition.
"""

from typing import Any, Callable

from app.schemas.state import Text2SQLState
from app.utils.trace_utils import add_trace


def traced(node_name: str) -> Callable:
    """Decorator: wrap a node function to auto-record its output via add_trace.

    Usage:
        @traced("intent")
        def intent_node(state: Text2SQLState) -> dict:
            ...
            return {"intent": "data_query", ...}

    The decorator intercepts the returned dict, strips empty/null values,
    records the non-empty ones via add_trace, and returns the dict with an
    updated debug_trace key.
    """

    def decorator(
        fn: Callable[[Text2SQLState], dict],
    ) -> Callable[[Text2SQLState], dict]:
        def wrapper(state: Text2SQLState) -> dict:
            result = fn(state)

            # Only record non-trivial output fields
            trace_output = {
                k: v
                for k, v in result.items()
                if v not in (None, "", [], {})
            }

            if trace_output:
                state = add_trace(state, node=node_name, output=trace_output)
                result["debug_trace"] = state.get("debug_trace", [])

            return result

        return wrapper

    return decorator
