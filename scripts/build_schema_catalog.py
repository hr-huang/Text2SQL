# scripts/build_schema_catalog.py
"""通用 Schema 提取脚本 — 支持命令行参数，适配任意 SQLite 数据库

用法:
  python scripts/build_schema_catalog.py                                          # 使用默认路径
  python scripts/build_schema_catalog.py data/mydb.db my_datasource_id             # 自定义
  python scripts/build_schema_catalog.py data/mydb.db my_datasource_id -o out.json # 指定输出
"""

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "data"


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def get_tables(conn: sqlite3.Connection) -> list[str]:
    cursor = conn.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
    """)
    return [row[0] for row in cursor.fetchall()]


def get_columns(conn: sqlite3.Connection, table_name: str) -> list[dict[str, Any]]:
    cursor = conn.execute(f"PRAGMA table_info({quote_identifier(table_name)})")
    columns = []
    for row in cursor.fetchall():
        cid, name, col_type, not_null, default_value, pk = row
        columns.append({
            "column_name": name, "type": col_type,
            "not_null": bool(not_null), "default_value": default_value,
            "is_primary_key": bool(pk), "sample_values": [],
        })
    return columns


def get_sample_values(conn, table_name, column_name, limit=5) -> list[Any]:
    try:
        sql = f"SELECT DISTINCT {quote_identifier(column_name)} FROM {quote_identifier(table_name)} WHERE {quote_identifier(column_name)} IS NOT NULL LIMIT {limit}"
        return [row[0] for row in conn.execute(sql).fetchall()]
    except Exception:
        return []


def infer_relationships(conn, tables) -> list[dict[str, Any]]:
    relationships = []
    for table in tables:
        table_name = table["table_name"]
        for fk in conn.execute(f"PRAGMA foreign_key_list({quote_identifier(table_name)})").fetchall():
            _, _, ref_table, from_col, to_col, _, _, _ = fk
            relationships.append({
                "left_table": ref_table, "left_column": to_col,
                "right_table": table_name, "right_column": from_col,
                "join_condition": f"{ref_table}.{to_col} = {table_name}.{from_col}",
                "description": f"{ref_table} 和 {table_name} 通过 {to_col} 关联",
            })
    return relationships


def build_schema_catalog(db_path: Path, datasource_id: str) -> dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(f"数据库文件不存在：{db_path}")

    conn = sqlite3.connect(str(db_path))
    table_names = get_tables(conn)
    tables = []

    for table_name in table_names:
        columns = get_columns(conn, table_name)
        enriched = []
        for col in columns:
            samples = get_sample_values(conn, table_name, col["column_name"])
            enriched.append({**col, "business_name": col["column_name"], "description": "", "sample_values": samples})

        pk = next((c["column_name"] for c in enriched if c.get("is_primary_key")), None)
        tables.append({"table_name": table_name, "business_name": table_name, "description": "", "primary_key": pk, "columns": enriched})

    catalog = {
        "datasource_id": datasource_id, "db_type": "sqlite",
        "description": f"SQLite database: {db_path.name}",
        "tables": tables,
        "relationships": infer_relationships(conn, tables),
    }
    conn.close()
    return catalog


def main():
    # 命令行参数解析
    args = sys.argv[1:]
    db_path = Path(args[0]) if len(args) > 0 else PROJECT_ROOT / "data" / "ecommerce.db"
    datasource_id = args[1] if len(args) > 1 else db_path.stem + "_db"
    output_path = Path(args[2]) if len(args) > 2 else OUTPUT_DIR / "schema_catalog.json"
    if len(args) > 3 and args[2] == "-o":
        output_path = Path(args[3])

    db_path = db_path if db_path.is_absolute() else PROJECT_ROOT / db_path
    output_path = output_path if output_path.is_absolute() else PROJECT_ROOT / output_path

    print(f"数据库: {db_path}")
    print(f"数据源ID: {datasource_id}")
    print(f"输出: {output_path}")

    catalog = build_schema_catalog(db_path, datasource_id)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 已生成: {output_path}")
    print(f"   表: {len(catalog['tables'])} 张 | 字段: {sum(len(t['columns']) for t in catalog['tables'])} 个 | 关系: {len(catalog['relationships'])} 条")
    for t in catalog["tables"]:
        print(f"   - {t['table_name']}: {len(t['columns'])} 列")


if __name__ == "__main__":
    main()
