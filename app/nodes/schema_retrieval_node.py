# app/nodes/schema_retrieval_node.py

from app.schemas.state import Text2SQLState
from app.services.schema_service import SchemaService


def schema_retrieval_node(state: Text2SQLState) -> dict:
    schema_service = SchemaService()

    result = schema_service.search_relevant_schema(
        datasource_id=state["datasource_id"],
        question=state["question"],
        metrics=state.get("metrics", []),
        dimensions=state.get("dimensions", []),
        filters=state.get("filters", {}),
    )

    return {
        "candidate_tables": result["candidate_tables"],
        "candidate_columns": result["candidate_columns"],
        "candidate_relationships": result.get("candidate_relationships", []),
    }
