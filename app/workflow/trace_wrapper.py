# app/workflow/trace_wrapper.py
"""Node wrapper that records wall-clock duration + LLM token deltas.

Wraps each LangGraph node so trace emission is transparent to the graph
definition. Pulls LLMService token counters before/after node execution
to attribute cost to the right step.
"""

import time
from typing import Any, Callable

from app.schemas.state import Text2SQLState
from app.services.llm_service import LLMService
from app.utils.trace_utils import add_trace


def traced(node_name: str) -> Callable:
    """Decorator: wrap a node function to auto-record timing + tokens."""

    def decorator(
        fn: Callable[[Text2SQLState], dict],
    ) -> Callable[[Text2SQLState], dict]:
        def wrapper(state: Text2SQLState) -> dict:
            stats_before = LLMService.get_stats()
            t0 = time.perf_counter()
            error: str | None = None
            result: dict[str, Any] = {}

            try:
                result = fn(state)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                duration_ms = int((time.perf_counter() - t0) * 1000)
                stats_after = LLMService.get_stats()
                prompt_delta = (stats_after["input_tokens"] or 0) - (stats_before["input_tokens"] or 0)
                completion_delta = (stats_after["output_tokens"] or 0) - (stats_before["output_tokens"] or 0)

                # Surface agent tool-calls if the node stored any in state.
                tool_calls = None
                if isinstance(result, dict):
                    candidate = result.get("tool_calls")
                    if isinstance(candidate, list) and candidate:
                        tool_calls = candidate

                trace_output = {
                    k: v for k, v in (result or {}).items()
                    if k != "debug_trace" and v not in (None, "", [], {})
                }

                state = add_trace(
                    state,
                    node=node_name,
                    output=trace_output,
                    duration_ms=duration_ms,
                    prompt_tokens_delta=prompt_delta or None,
                    completion_tokens_delta=completion_delta or None,
                    tool_calls=tool_calls,
                    error=error,
                )
                if isinstance(result, dict):
                    result["debug_trace"] = state.get("debug_trace", [])

            return result

        return wrapper

    return decorator