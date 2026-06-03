"""测试 Workflow 图编译和状态"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.workflow.state_helpers import create_initial_state
from app.workflow.graph import (
    route_after_classify,
    route_after_execute,
    route_after_intent,
    route_after_repair,
    route_after_validate,
)
from scripts.run_evaluation import compare_results


def test_create_initial_state():
    """创建初始状态结构完整"""
    state = create_initial_state(
        user_id="test",
        question="有多少客户？",
        datasource_id="ecommerce_db",
    )
    assert state["question"] == "有多少客户？"
    assert state["datasource_id"] == "ecommerce_db"
    assert isinstance(state["candidate_tables"], list)
    assert isinstance(state["candidate_columns"], list)


class TestCompareResults:
    def test_identical(self):
        assert compare_results([{"a": 1}], [{"a": 1}]) is True

    def test_different_length(self):
        assert compare_results([{"a": 1}], [{"a": 1}, {"a": 2}]) is False

    def test_order_sensitive_match(self):
        assert compare_results(
            [{"a": 3}, {"a": 1}, {"a": 2}],
            [{"a": 3}, {"a": 1}, {"a": 2}],
            order_sensitive=True,
        ) is True

    def test_order_sensitive_mismatch(self):
        assert compare_results(
            [{"a": 1}, {"a": 2}],
            [{"a": 2}, {"a": 1}],
            order_sensitive=True,
        ) is False

    def test_order_insensitive(self):
        assert compare_results(
            [{"a": 2}, {"a": 1}],
            [{"a": 1}, {"a": 2}],
            order_sensitive=False,
        ) is True

    def test_column_name_difference(self):
        """列名不同但数据等价时用 common_keys 交集"""
        assert compare_results(
            [{"count": 5, "name": "A"}],
            [{"cnt": 5, "name": "A"}],
            order_sensitive=False,
        ) is True

    def test_empty_both(self):
        assert compare_results([], []) is True


class TestWorkflowRouting:
    def test_non_data_question_routes_to_terminal_answer(self):
        assert route_after_intent({"is_data_question": False}) == "answer_non_data"

    def test_data_question_routes_to_classify(self):
        assert route_after_intent({"is_data_question": True}) == "classify"

    def test_complex_question_routes_to_decompose(self):
        assert route_after_classify({"complexity": "complex"}) == "decompose"

    def test_simple_question_routes_to_semantic(self):
        assert route_after_classify({"complexity": "simple"}) == "semantic"

    def test_validation_error_routes_to_failed_answer(self):
        assert route_after_validate({"sql_validation_error": "bad sql"}) == "answer_validation_failed"

    def test_valid_sql_routes_to_execute(self):
        assert route_after_validate({"sql_validation_error": None}) == "execute"

    def test_execute_success_routes_to_answer(self):
        assert route_after_execute({"execution_error": None}) == "answer"

    def test_execute_failure_under_limit_routes_to_repair(self):
        assert route_after_execute({"execution_error": "no such column", "repair_attempts": 2}) == "sql_repair"

    def test_execute_failure_at_limit_routes_to_failed_answer(self):
        assert route_after_execute({"execution_error": "no such column", "repair_attempts": 3}) == "answer_exec_failed"

    def test_repair_success_routes_to_execute(self):
        assert route_after_repair({"execution_error": None}) == "execute"

    def test_repair_failure_routes_to_failed_answer(self):
        assert route_after_repair({"execution_error": "still broken"}) == "answer_exec_failed"
