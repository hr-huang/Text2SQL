#!/usr/bin/env python3
"""Analyze an existing evaluation JSON and categorize failure modes.

Reads output/<preset>.json, classifies each failed question by where the
breakdown happened (intent / schema retrieval / semantic parse / SQL
generation / SQL execution / result mismatch / complex decomposition),
and writes a markdown report to output/<preset>/bad_cases.md.

Usage:
    python scripts/analyze_bad_cases.py deepseek_v4_flash
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"


# ── Categorization rules (priority order) ────────────────────────


def _extract_tables(sql: str) -> set[str]:
    """Extract table references from a SQL statement using sqlglot."""
    if not sql or not sql.strip():
        return set()
    try:
        import sqlglot
        from sqlglot import exp
        parsed = sqlglot.parse(sql, read="sqlite")
        if not parsed:
            return set()
        tables = set()
        for node in parsed[0].walk():
            if isinstance(node, exp.Table):
                tables.add(node.name.lower())
        return tables
    except Exception:
        return set()


def _extract_where_columns(sql: str) -> set[str]:
    """Extract column names referenced in WHERE clauses."""
    if not sql or not sql.strip():
        return set()
    try:
        import sqlglot
        from sqlglot import exp
        parsed = sqlglot.parse(sql, read="sqlite")
        if not parsed:
            return set()
        cols = set()
        for node in parsed[0].walk():
            if isinstance(node, exp.Where):
                for col in node.find_all(exp.Column):
                    cols.add(col.name.lower())
        return cols
    except Exception:
        return set()


def _extract_candidate_tables(debug: list[dict]) -> set[str]:
    """Get the candidate tables that schema_retrieval returned (from debug_trace)."""
    for entry in debug:
        if isinstance(entry, dict) and entry.get("node") in {"schema", "schema_retrieval"}:
            output = entry.get("output") or {}
            candidates = output.get("candidate_tables") or []
            return {t.get("table_name", "").lower() for t in candidates if isinstance(t, dict)}
    return set()


def categorize_failure(r: dict) -> str:
    """Classify a single failed question into a failure-mode bucket.

    New categories (vs original):
    - table_out_of_scope: LLM 用了 candidate 之外的表（要么 schema 没召回对，要么 LLM 幻觉）
    - missing_join: 生成的 SQL 表数 < gold 应有的表数（LLM 简化了 JOIN 路径）
    - wrong_filter: WHERE 用了错的列（如 orders.status 替代 shipping_tracking.status）
    - result_mismatch: 跑了但结果不匹配，找不到明确模式
    """
    status = (r.get("status") or "").lower()
    generated_sql = (r.get("generated_sql") or "").strip()
    gold_sql = (r.get("gold_sql") or "").strip()
    difficulty = r.get("difficulty", "")
    debug = r.get("debug_trace") or []

    # 1. 复杂问题子任务失败
    if difficulty == "complex" and (status.startswith("sub_fail") or status == "no_decompose"):
        return "complex_decompose_failure"

    # 2. 执行报错
    if status == "exec_error" or "syntax error" in status or "no such" in status:
        return "execution_error"

    # 3. 没生成 SQL → 要先看走的是哪条路径
    if not generated_sql:
        visited = {e.get("node") for e in debug if isinstance(e, dict)}
        # 走了 decompose / orchestrator 说明被判为复杂题，但编排器没产出 SQL
        if visited & {"decompose", "orchestrator"}:
            return "complex_decompose_failure"
        return "schema_retrieve_failure"

    # 4. 结果不匹配 → 细看 SQL 找根因
    if status == "mismatch":
        gen_tables = _extract_tables(generated_sql)
        gold_tables = _extract_tables(gold_sql)
        gen_where_cols = _extract_where_columns(generated_sql)
        gold_where_cols = _extract_where_columns(gold_sql)
        candidate_tables = _extract_candidate_tables(debug)

        # 4a. LLM 用了候选集之外的表
        if candidate_tables and gen_tables and not gen_tables.issubset(candidate_tables):
            out_of_scope = gen_tables - candidate_tables
            return "table_out_of_scope"  # +reason: 用 {tbls} 但没在候选集里

        # 4b. LLM 漏了必要的 JOIN（表数明显少于 gold）
        if gold_tables and len(gen_tables) < len(gold_tables) - 1:
            return "missing_join"

        # 4c. WHERE 列用错（如 status 取错表）
        # 判断标准：gen 用了 WHERE 列，但跟 gold 的 WHERE 列**没有任何交集** → 用错
        if gold_where_cols and gen_where_cols and not (gen_where_cols & gold_where_cols):
            return "wrong_filter"

        # 4d. 兜底：跑通但结果错，找不到明确模式
        return "result_mismatch"

    # 5. 兜底
    return "other"


def short_status_label(r: dict) -> str:
    status = (r.get("status") or "").lower()
    if status.startswith("sub_fail"):
        return status
    if status == "exec_error":
        return "exec_error"
    if status == "mismatch":
        return "mismatch"
    return status or "unknown"


def render_report(preset: str, data: dict) -> Path:
    results = data.get("results", [])
    failures = [r for r in results if not r.get("match")]

    buckets: dict[str, list[dict]] = defaultdict(list)
    for r in failures:
        cat = categorize_failure(r)
        buckets[cat].append(r)

    total = len(results)
    passed = sum(1 for r in results if r.get("match"))
    accuracy = passed / total * 100 if total else 0

    out_dir = OUTPUT_DIR / preset
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "bad_cases.md"

    cat_labels = {
        "intent_rejection": "意图识别拒答",
        "schema_retrieve_failure": "Schema 检索失败（未召回相关表）",
        "table_out_of_scope": "LLM 用了候选集之外的表",
        "missing_join": "LLM 漏了必要 JOIN",
        "wrong_filter": "WHERE 过滤列用错",
        "sql_generation_failure": "SQL 生成失败",
        "execution_error": "SQL 执行报错",
        "result_mismatch": "结果不匹配（其他原因）",
        "complex_decompose_failure": "复杂题拆解失败",
        "other": "其他",
    }

    lines = []
    lines.append(f"# 失败案例分析 — `{preset}`\n")
    lines.append(f"- 模型: `{preset}`")
    lines.append(f"- 总题数: {total}  |  通过: {passed}  |  失败: {len(failures)}")
    lines.append(f"- **总体准确率: {accuracy:.1f}%**\n")

    lines.append("## 失败分布（按失败阶段归因）\n")
    lines.append("| 阶段 | 失败数 | 占比 |")
    lines.append("|---|---|---|")
    for cat, label in cat_labels.items():
        n = len(buckets.get(cat, []))
        pct = n / len(failures) * 100 if failures else 0
        lines.append(f"| {label} | {n} | {pct:.1f}% |")
    lines.append("")

    for cat, items in buckets.items():
        if not items:
            continue
        lines.append(f"## {cat_labels.get(cat, cat)}（{len(items)} 题）\n")
        for r in items[:8]:
            lines.append(f"### [{r.get('id')}] {r.get('question')}")
            lines.append(f"- 难度: `{r.get('difficulty')}` | 状态: `{short_status_label(r)}`")
            lines.append(f"- 生成 SQL: `{r.get('generated_sql') or 'NONE'}`")
            lines.append(f"- 标准 SQL: `{r.get('gold_sql') or 'NONE'}`")
            gen_n = r.get("rows_count", 0)
            gold_n = r.get("gold_rows_count", 0)
            if gen_n or gold_n:
                lines.append(f"- 行数: 生成={gen_n}  /  标准={gold_n}")
            lines.append("")
        if len(items) > 8:
            lines.append(f"_…还有 {len(items) - 8} 题同类失败，见 `<preset>.json`。_\n")
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


def main():
    if len(sys.argv) < 2:
        candidates = sorted(
            p.stem for p in OUTPUT_DIR.glob("*.json") if p.stem != "comparison"
        )
        if not candidates:
            print("output/ 下没有可用的评测结果文件")
            return 1
        print("用法: python scripts/analyze_bad_cases.py <preset>")
        print("可用的 preset:", ", ".join(candidates))
        return 1

    preset = sys.argv[1]
    src = OUTPUT_DIR / f"{preset}.json"
    if not src.exists():
        print(f"找不到 {src}")
        return 1

    data = json.loads(src.read_text(encoding="utf-8"))
    md_path = render_report(preset, data)
    print(f"已生成: {md_path}")

    results = data.get("results", [])
    failures = [r for r in results if not r.get("match")]
    counter = Counter(categorize_failure(r) for r in failures)
    print("\n失败分布:")
    for cat, n in counter.most_common():
        print(f"  {cat}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())