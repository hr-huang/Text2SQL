"""测试数据库安全限制（LIMIT 强制 + 只读）"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.db_service import DBService


class TestEnsureLimit:
    def test_no_limit(self):
        db = DBService()
        result = db._ensure_limit("SELECT * FROM products", max_rows=100)
        assert "LIMIT 100" in result

    def test_has_limit(self):
        db = DBService()
        result = db._ensure_limit("SELECT * FROM products LIMIT 50", max_rows=100)
        assert result == "SELECT * FROM products LIMIT 50"

    def test_subquery_with_limit(self):
        """子查询已有 LIMIT，AST 遍历能检测到，不重复追加"""
        db = DBService()
        result = db._ensure_limit(
            "SELECT * FROM (SELECT * FROM orders LIMIT 10)",
            max_rows=500,
        )
        # 子查询里的 LIMIT 也算 LIMIT，不再追加外层
        # 避免外层 LIMIT 截断子查询数据导致错误结果
        assert "LIMIT 500" not in result

    def test_with_semicolon(self):
        db = DBService()
        result = db._ensure_limit("SELECT * FROM products;", max_rows=200)
        assert "LIMIT 200" in result
        assert not result.endswith(";LIMIT")
