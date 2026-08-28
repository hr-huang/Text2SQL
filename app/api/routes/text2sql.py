# app/api/routes/text2sql.py

import json
import asyncio

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.schemas.request import Text2SQLRequest
from app.schemas.response import Text2SQLResponse
from app.workflow.graph import get_graph
from app.workflow.state_helpers import create_initial_state

router = APIRouter()


@router.get("/schema")
def get_schema(datasource_id: str = "ecommerce_db"):
    """返回数据库 Schema 摘要 — 前端 Schema 浏览器使用"""
    from app.services.schema_service import SchemaService
    svc = SchemaService()
    result = svc.build_all_candidate_schema(datasource_id)
    tables = []
    for t in result.get("candidate_tables", []):
        cols = [c for c in result.get("candidate_columns", []) if c["table_name"] == t["table_name"]]
        tables.append({
            "table_name": t["table_name"],
            "business_name": t.get("business_name", t["table_name"]),
            "primary_key": t.get("primary_key"),
            "row_count": _estimate_row_count(datasource_id, t["table_name"]),
            "columns": [{
                "column_name": c["column_name"],
                "type": c.get("type", ""),
                "is_primary_key": c.get("is_primary_key", False),
                "sample_values": c.get("sample_values", [])[:3],
            } for c in cols],
        })
    return {"datasource_id": datasource_id, "tables": tables}


def _estimate_row_count(datasource_id: str, table_name: str) -> int:
    from app.services.db_service import DBService
    try:
        db = DBService()
        r = db.execute_readonly_sql(datasource_id, f"SELECT COUNT(*) FROM {table_name}")
        return r["rows"][0]["COUNT(*)"] if r["success"] else 0
    except Exception:
        return 0

# ── 节点名 → 中文标签映射 ──
NODE_LABELS = {
    "detect_intent": "🔍 意图识别",
    "classify": "🏷️ 复杂度分类",
    "decompose": "🧩 拆解问题",
    "orchestrator": "🎯 编排执行",
    "semantic": "📝 语义解析",
    "schema": "🗄️ Schema 检索",
    "sql_gen": "⚡ 生成 SQL",
    "validate": "🛡️ SQL 校验",
    "execute": "▶️ 执行查询",
    "sql_repair": "🔧 ReAct 修复",
    "answer": "💬 汇总回答",
}


@router.post("/text2sql", response_model=Text2SQLResponse)
def text2sql(req: Text2SQLRequest) -> Text2SQLResponse:
    state = create_initial_state(
        user_id=req.user_id,
        question=req.question,
        datasource_id=req.datasource_id,
        session_id=req.session_id,
    )

    graph = get_graph()
    final_state = graph.invoke(state)

    return Text2SQLResponse(
        answer=final_state["final_answer"],
        sql=final_state.get("validated_sql") or final_state.get("generated_sql"),
        rows=final_state.get("execution_result", []),
        confidence=final_state.get("confidence", 0.0),
        trace_id=final_state["trace_id"],
        warnings=final_state.get("warnings", []),
        debug_trace=final_state.get("debug_trace", []),
    )


@router.post("/text2sql/stream")
async def text2sql_stream(req: Text2SQLRequest):
    """SSE 流式端点 — LangGraph 每完成一个节点推送一次事件"""

    async def generate():
        state = create_initial_state(
            user_id=req.user_id,
            question=req.question,
            datasource_id=req.datasource_id,
            session_id=req.session_id,
        )

        graph = get_graph()

        # 1. 推送开始事件
        yield f"data: {json.dumps({'type':'start','question':req.question}, ensure_ascii=False)}\n\n"

        # 2. LangGraph astream 逐个节点推送
        total_tokens = 0
        from app.services.llm_service import LLMService
        try:
            async for event in graph.astream(state, stream_mode="updates"):
                for node_name, node_output in event.items():
                    label = NODE_LABELS.get(node_name, node_name)
                    payload = {"type": "node", "node": node_name, "label": label}

                    if isinstance(node_output, dict):
                        if "generated_sql" in node_output:
                            payload["sql"] = node_output["generated_sql"]
                        if "validated_sql" in node_output:
                            payload["sql"] = node_output["validated_sql"]
                        if "final_answer" in node_output:
                            payload["answer"] = node_output["final_answer"]
                        if "execution_result" in node_output:
                            payload["row_count"] = len(node_output["execution_result"])
                            payload["rows"] = node_output["execution_result"][:20]
                        if "confidence" in node_output:
                            payload["confidence"] = node_output["confidence"]
                        if "complexity" in node_output:
                            payload["complexity"] = node_output["complexity"]
                        if "warnings" in node_output:
                            payload["warnings"] = node_output["warnings"]
                        if "self_reflection" in node_output:
                            payload["self_reflection"] = node_output["self_reflection"]

                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type':'error','message':str(e)}, ensure_ascii=False)}\n\n"

        # 2.5 推送一次总成本汇总
        stats = LLMService.get_stats()
        yield f"data: {json.dumps({'type':'cost_summary','tokens':stats.get('total_tokens',0),'calls':stats.get('calls',0)}, ensure_ascii=False)}\n\n"

        # 3. 推送完成事件
        yield f"data: {json.dumps({'type':'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
