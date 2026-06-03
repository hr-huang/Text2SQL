"""测试 SQL 验证和安全检查"""
import sys
from pathlib import Path

# 确保项目根在 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.db_service import DBService
from app.services.sql_service import SQLService


def test_ensure_limit_adds_limit():
    """无 LIMIT 的 SQL 自动追加"""
    db = DBService()
    sql = db._ensure_limit("SELECT * FROM products", max_rows=500)
    assert "LIMIT 500" in sql


def test_ensure_limit_keeps_existing_limit():
    """已有 LIMIT 的不重复追加"""
    db = DBService()
    sql = db._ensure_limit("SELECT * FROM products LIMIT 10", max_rows=500)
    assert sql == "SELECT * FROM products LIMIT 10"


def test_sql_validation_valid():
    """合法 SQL 通过验证"""
    svc = SQLService()
    result = svc.validate_sql(
        "SELECT name FROM products WHERE unit_price > 100",
        candidate_tables=[{"table_name": "products"}],
        candidate_columns=[{"table_name": "products", "column_name": "name"}, {"table_name": "products", "column_name": "unit_price"}],
    )
    assert result.get("valid") is True


def test_sql_validation_dangerous():
    """危险 SQL 被拦截"""
    svc = SQLService()
    result = svc.validate_sql(
        "DROP TABLE products",
        candidate_tables=[{"table_name": "products"}],
        candidate_columns=[],
    )
    assert result.get("valid") is False


def test_sql_validation_rejects_multi_statement():
    """禁止多语句，避免拼接注入绕过只读限制"""
    svc = SQLService()
    result = svc.validate_sql(
        "SELECT name FROM products; SELECT name FROM users",
        candidate_tables=[{"table_name": "products"}, {"table_name": "users"}],
        candidate_columns=[],
    )
    assert result.get("valid") is False
    assert "一条 SQL" in result.get("error", "")


def test_sql_validation_does_not_block_keyword_inside_column_name():
    """AST 校验不应因为字段名包含 delete 等字符串而误杀"""
    svc = SQLService()
    result = svc.validate_sql(
        "SELECT delete_count FROM products",
        candidate_tables=[{"table_name": "products"}],
        candidate_columns=[],
    )
    assert result.get("valid") is True


def test_sql_validation_allows_cte_select():
    """允许只读 CTE，但 CTE 内引用的真实表仍需在候选表内"""
    svc = SQLService()
    result = svc.validate_sql(
        "WITH recent AS (SELECT name FROM products) SELECT name FROM recent",
        candidate_tables=[{"table_name": "products"}],
        candidate_columns=[],
    )
    assert result.get("valid") is True


def test_sql_validation_allows_readonly_subquery():
    """允许只读子查询"""
    svc = SQLService()
    result = svc.validate_sql(
        "SELECT name FROM (SELECT name FROM products) AS p",
        candidate_tables=[{"table_name": "products"}],
        candidate_columns=[],
    )
    assert result.get("valid") is True
