# app/workflow/graph.py
"""Text2SQL workflow built on LangGraph StateGraph.

Nodes are plain functions (state) -> dict returning partial state updates.
The graph is compiled once at startup and reused for all requests.

Graph structure:

    START
      │
      ▼
detect_intent ──(非数据)──► answer_non_data ──► END
      │
      └─(数据)────► classify ──(simple)──► semantic → schema
                        │                                         │
                        │(complex)                                ▼
                        ▼                                      sql_gen → validate → ...
                     decompose ──(当前走老路)──► semantic
                        │
                        └─ sub_questions 存入 state，由 orchestrator 消费
"""

from langgraph.graph import StateGraph, START, END

from app.nodes.intent_node import intent_node
from app.nodes.classify_node import classify_node
from app.nodes.decompose_node import decompose_node
from app.workflow.orchestrator import orchestrator_node
from app.nodes.semantic_parse_node import semantic_parse_node
from app.nodes.schema_retrieval_node import schema_retrieval_node
from app.nodes.sql_generation_node import sql_generation_node
from app.nodes.sql_review_node import sql_review_node
from app.nodes.self_reflection_node import self_reflection_node
from app.nodes.sql_validation_node import sql_validation_node
from app.nodes.sql_execution_node import sql_execution_node
from app.nodes.sql_repair_node import sql_repair_node
from app.nodes.answer_node import answer_node
from app.nodes.terminal_nodes import (
    answer_non_data_node,
    answer_validation_failed_node,
    answer_exec_failed_node,
)
from app.schemas.state import Text2SQLState
from app.workflow.trace_wrapper import traced

# ═══════════════════════════════════════════════════════════════════
# Routing functions — called by conditional edges
# ═══════════════════════════════════════════════════════════════════


def route_after_intent(state: Text2SQLState) -> str:
    """After intent detection: classify data questions, reject others."""
    if state.get("is_data_question"):
        return "classify"
    return "answer_non_data"


def route_after_classify(state: Text2SQLState) -> str:
    """After classify: decompose complex questions, skip for simple ones.

    Complex questions route: classify → decompose → orchestrator → END

    force_decompose（评测开关）会跳过 classify 的复杂度判断直接进入 decompose，
    用来衡量编排路径的成功率——即使 LLM 认为单条 SQL 也能解。
    """
    if state.get("force_decompose") or state.get("complexity") == "complex":
        return "decompose"
    return "semantic"


def route_after_decompose(state: Text2SQLState) -> str:
    """After decompose: only go to orchestrator if we actually got sub-questions.

    decompose_node returns an empty sub_questions list when the LLM decides the
    question can be answered with a single SQL. Without this fallback the graph
    would reach orchestrator, which returns {} for empty sub_questions, and end
    the run with no SQL and no answer.
    """
    if state.get("sub_questions"):
        return "orchestrator"
    return "semantic"


def route_after_validate(state: Text2SQLState) -> str:
    """After SQL validation: execute if valid, report failure otherwise."""
    if state.get("sql_validation_error"):
        return "answer_validation_failed"
    return "execute"


def route_after_execute(state: Text2SQLState) -> str:
    """After SQL execution: answer if success, repair if failed (under 3 attempts)."""
    if not state.get("execution_error"):
        return "answer"
    if state.get("repair_attempts", 0) < 3:
        return "sql_repair"
    return "answer_exec_failed"


def route_after_repair(state: Text2SQLState) -> str:
    """After repair attempt: retry execution if successful, give up otherwise."""
    if state.get("execution_error"):
        return "answer_exec_failed"
    return "execute"


# ═══════════════════════════════════════════════════════════════════
# Graph construction
# ═══════════════════════════════════════════════════════════════════


def compile_graph():
    """Build and compile the Text2SQL StateGraph.

    Called once at application startup. Returns a CompiledGraph that can
    be invoked with graph.invoke(state) or streamed with graph.astream(state).
    """
    builder = StateGraph(Text2SQLState)

    # ── Core pipeline nodes (wrapped with auto-tracing) ──
    builder.add_node("detect_intent", traced("detect_intent")(intent_node))
    builder.add_node("classify", traced("classify")(classify_node))
    builder.add_node("decompose", traced("decompose")(decompose_node))
    builder.add_node("orchestrator", traced("orchestrator")(orchestrator_node))
    builder.add_node("semantic", traced("semantic")(semantic_parse_node))
    builder.add_node("schema", traced("schema")(schema_retrieval_node))
    builder.add_node("sql_gen", traced("sql_gen")(sql_generation_node))
    builder.add_node("sql_review", traced("sql_review")(sql_review_node))
    builder.add_node("self_reflection", traced("self_reflection")(self_reflection_node))
    builder.add_node("validate", traced("validate")(sql_validation_node))
    builder.add_node("execute", traced("execute")(sql_execution_node))
    builder.add_node("sql_repair", traced("sql_repair")(sql_repair_node))
    builder.add_node("answer", traced("answer")(answer_node))

    # ── Terminal nodes (early-exit paths, auto-traced) ──
    builder.add_node(
        "answer_non_data", traced("answer_non_data")(answer_non_data_node)
    )
    builder.add_node(
        "answer_validation_failed",
        traced("answer_validation_failed")(answer_validation_failed_node),
    )
    builder.add_node(
        "answer_exec_failed", traced("answer_exec_failed")(answer_exec_failed_node)
    )

    # ── Edges ──

    # Entry: START → detect_intent
    builder.add_edge(START, "detect_intent")

    # detect_intent → classify | answer_non_data
    builder.add_conditional_edges(
        "detect_intent",
        route_after_intent,
        {
            "classify": "classify",
            "answer_non_data": "answer_non_data",
        },
    )
    builder.add_edge("answer_non_data", END)

    # classify → decompose (complex) or semantic (simple)
    builder.add_conditional_edges(
        "classify",
        route_after_classify,
        {
            "decompose": "decompose",
            "semantic": "semantic",
        },
    )
    # decompose → orchestrator (有子问题) 或 semantic (可用单 SQL 回答，回落单条链路)
    builder.add_conditional_edges(
        "decompose",
        route_after_decompose,
        {
            "orchestrator": "orchestrator",
            "semantic": "semantic",
        },
    )
    builder.add_edge("orchestrator", END)

    # Serial chain: semantic → schema → sql_gen → sql_review → self_reflection → validate
    builder.add_edge("semantic", "schema")
    builder.add_edge("schema", "sql_gen")
    builder.add_edge("sql_gen", "sql_review")
    builder.add_edge("sql_review", "self_reflection")
    builder.add_edge("self_reflection", "validate")

    # validate → execute | answer_validation_failed
    builder.add_conditional_edges(
        "validate",
        route_after_validate,
        {
            "execute": "execute",
            "answer_validation_failed": "answer_validation_failed",
        },
    )
    builder.add_edge("answer_validation_failed", END)

    # execute → answer | sql_repair | answer_exec_failed
    builder.add_conditional_edges(
        "execute",
        route_after_execute,
        {
            "answer": "answer",
            "sql_repair": "sql_repair",
            "answer_exec_failed": "answer_exec_failed",
        },
    )
    builder.add_edge("answer", END)

    # sql_repair → execute (retry) | answer_exec_failed (give up)
    builder.add_conditional_edges(
        "sql_repair",
        route_after_repair,
        {
            "execute": "execute",
            "answer_exec_failed": "answer_exec_failed",
        },
    )
    builder.add_edge("answer_exec_failed", END)

    return builder.compile()


# ═══════════════════════════════════════════════════════════════════
# Module-level graph singleton — set once at startup
# ═══════════════════════════════════════════════════════════════════

_graph = None  # type: ignore


def get_graph():
    """Return the compiled graph. Raises RuntimeError if not yet compiled."""
    if _graph is None:
        raise RuntimeError(
            "Graph not compiled yet. Call compile_graph() at startup "
            "(see app/main.py startup event)."
        )
    return _graph


def set_graph(compiled_graph):
    """Store the compiled graph (called from main.py startup event)."""
    global _graph
    _graph = compiled_graph


# ═══════════════════════════════════════════════════════════════════
# Backward-compatible wrapper
# ═══════════════════════════════════════════════════════════════════


def run_text2sql_workflow(state: Text2SQLState) -> Text2SQLState:
    """Run the Text2SQL workflow synchronously.

    Backward-compatible wrapper used by existing callers (API route,
    evaluation script). Under the hood it calls graph.invoke().
    """
    graph = get_graph()
    return graph.invoke(state)  # type: ignore[return-value]
