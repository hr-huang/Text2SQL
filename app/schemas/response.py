# app/schemas/response.py

from pydantic import BaseModel
from typing import Any, Optional


class Text2SQLResponse(BaseModel):
    answer: str
    sql: Optional[str] = None
    rows: list[dict[str, Any]] = []
    confidence: float = 0.0
    trace_id: str
    warnings: list[str] = []
    debug_trace: list[dict[str, Any]] = []