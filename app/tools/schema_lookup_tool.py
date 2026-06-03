# app/tools/schema_lookup_tool.py

from typing import Any

from app.services.schema_service import SchemaService


class SchemaLookupTool:
    name = "schema_lookup"
    description = "查询指定数据源中某张表的字段结构"

    def __init__(self):
        self.schema_service = SchemaService()

    def run(self, datasource_id: str, table_name: str) -> dict[str, Any]:
        return self.schema_service.get_table_schema(
            datasource_id=datasource_id,
            table_name=table_name,
        )