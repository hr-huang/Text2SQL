# app/workflow/state_helpers.py
"""State factory for LangGraph — ensures all TypedDict fields have defaults.

LangGraph requires every key in a total=False TypedDict to have an initial
value when the graph is invoked. This module provides a factory that fills
in sensible defaults for every field in Text2SQLState.
"""

from uuid import uuid4

from app.schemas.state import Text2SQLState


def create_initial_state(
    user_id: str,
    question: str,
    datasource_id: str,
    session_id: str | None = None,
) -> Text2SQLState:
    """Create a fully initialized Text2SQLState for LangGraph invocation.

    This is the single entry point for creating state — the API route and
    evaluation script both use it. All optional fields get explicit defaults
    so LangGraph's StateGraph can compile without missing keys.
    """
    return Text2SQLState(
        trace_id=str(uuid4()),
        user_id=user_id,
        question=question,
        datasource_id=datasource_id,
        session_id=session_id,

        # ── intent ──
        intent="",
        is_data_question=False,
        intent_reason="",

        # ── complexity ──
        complexity="",
        complexity_reason="",

        # ── decompose ──
        sub_questions=[],
        sub_results=[],

        # ── semantic parse ──
        metrics=[],
        dimensions=[],
        filters={},
        time_range={},
        sort={},
        limit=None,

        # ── schema retrieval ──
        candidate_tables=[],
        candidate_columns=[],
        candidate_relationships=[],

        # ── sql generation ──
        generated_sql=None,
        sql_generation_reason="",

        # ── sql validation ──
        validated_sql=None,
        sql_validation_error=None,
        sql_validation_warnings=[],

        # ── sql execution ──
        execution_result=[],
        execution_error=None,

        # ── sql repair ──
        repair_attempts=0,
        repair_observations=[],

        # ── answer ──
        final_answer="",
        confidence=0.0,
        warnings=[],

        # ── trace ──
        debug_trace=[],
    )
