"""评测脚本：运行评测集，计算执行准确率

输出结构：output/<model_preset>/
  ├── summary.json              # 汇总指标
  ├── questions/
  │   ├── 001.json              # 每题详情（完整 SQL + 结果对比）
  │   └── ...
  └── sql/
      ├── 001.sql               # 每题生成的 SQL（纯文本）
      └── ...

output/comparison.json           # 多模型对比（跑多个模型时自动生成）
"""
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from app.workflow.state_helpers import create_initial_state
from app.workflow.graph import compile_graph

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVAL_PATH    = PROJECT_ROOT / "data" / "eval_questions.json"
DB_PATH      = PROJECT_ROOT / "data" / "ecommerce.db"
OUTPUT_DIR   = PROJECT_ROOT / "output"

# 所有可评测的模型预设
ALL_PRESETS = [
    "deepseek_v4_flash",
    "deepseek_v4_pro",
    "ali_qwen_plus",
    "gemini_flash",
    "gemini_pro",
    "kimi_8k",
    "kimi_32k",
    "mimo_flash",
    "mimo_pro",
    "mimo_2_5_flash",
    "mimo_2_5_pro",
    "gemini_3_1_flash",
]

# 北京时间时区
CST = timezone(timedelta(hours=8))


def get_current_preset() -> str:
    """读取当前 .env 中激活的模型预设名"""
    return os.getenv("LLM_PRESET", "deepseek_v4_flash").lower()


def run_eval_set(questions, graph):
    """跑评测集，返回详细结果"""
    results = []
    passed = 0
    total_time = 0

    for i, q in enumerate(questions):
        print(f"  [{i+1}/{len(questions)}] {q['id']} {q['question'][:40]}...", end=" ", flush=True)
        state = create_initial_state(
            user_id="eval",
            question=q["question"],
            datasource_id="ecommerce_db",
            session_id=f"eval_{q['id']}",
        )

        t0 = time.time()
        try:
            final = graph.invoke(state)
        except Exception as e:
            results.append({
                "id": q["id"],
                "question": q["question"],
                "difficulty": q["difficulty"],
                "status": "error",
                "error": str(e)[:300],
                "generated_sql": "",
                "gold_sql": q["gold_sql"],
                "match": False,
                "generated_rows": [],
                "gold_rows": [],
                "rows_count": 0,
                "gold_rows_count": 0,
                "complexity": "?",
                "elapsed": round(time.time() - t0, 2),
            })
            print("ERROR", flush=True)
            continue

        elapsed = time.time() - t0
        total_time += elapsed

        is_complex = q.get("difficulty") == "complex"
        generated_sql = final.get("validated_sql") or final.get("generated_sql") or ""
        rows = final.get("execution_result", [])
        has_error = bool(final.get("execution_error"))
        complexity = final.get("complexity", "?")

        # ── 复杂题：查子问题执行成功率 ──
        if is_complex:
            sub_results = final.get("sub_results", [])
            if not sub_results:
                match = False
                status = "no_decompose"
            else:
                ok = sum(1 for r in sub_results if not r.get("error") and len(r.get("rows", [])) > 0)
                fail = len(sub_results) - ok
                match = fail == 0  # 全部子问题成功才算通过
                status = "pass" if match else f"sub_fail({ok}/{len(sub_results)})"
            gold_rows = []
        else:
            # ── 简单/中等：SQL 执行结果对比 ──
            gold_rows = execute_gold_sql(q["gold_sql"])
            match = compare_results(rows, gold_rows, order_sensitive=q.get("order_sensitive", False))
            status = "pass" if match else ("exec_error" if has_error else "mismatch")

        if match:
            passed += 1

        results.append({
            "id": q["id"],
            "question": q["question"],
            "difficulty": q["difficulty"],
            "expected_complexity": q.get("expected_complexity", ""),
            "order_sensitive": q.get("order_sensitive", False),
            "status": status,
            "generated_sql": generated_sql,
            "gold_sql": q["gold_sql"],
            "match": match,
            "complexity": complexity,
            "generated_rows": rows,
            "gold_rows": gold_rows,
            "rows_count": len(rows) if rows else 0,
            "gold_rows_count": len(gold_rows) if gold_rows else 0,
            "elapsed": round(elapsed, 2),
            "debug_trace": final.get("debug_trace", []),
        })
        print("PASS" if match else "FAIL", flush=True)

    accuracy = passed / len(questions) * 100 if questions else 0
    avg_time = total_time / len(questions) if questions else 0

    from app.services.llm_service import LLMService
    token_stats = LLMService.get_stats()

    return {
        "total": len(questions),
        "passed": passed,
        "failed": len(questions) - passed,
        "accuracy": round(accuracy, 1),
        "avg_time_sec": round(avg_time, 1),
        "tokens": token_stats,
        "results": results,
    }


def execute_gold_sql(sql: str) -> list[dict]:
    """执行标准 SQL，返回结果集"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(sql)
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


def compare_results(generated_rows: list[dict], gold_rows: list[dict], order_sensitive: bool = False) -> bool:
    """比较两个结果集是否等价。"""
    if len(generated_rows) != len(gold_rows):
        return False
    if not generated_rows and not gold_rows:
        return True

    def row_to_values(row: dict, keys: list[str] | None = None) -> tuple:
        if keys is None:
            keys = sorted(row.keys())
        return tuple(str(row[k]) for k in keys if k in row)

    gen_keys = list(generated_rows[0].keys())
    gold_keys = list(gold_rows[0].keys())
    common = [k for k in gen_keys if k in gold_keys]

    def row_to_values_by_position(row: dict) -> tuple:
        return tuple(str(v) for v in row.values())

    if common:
        key_fn = lambda r: row_to_values(r, common)
    else:
        key_fn = row_to_values_by_position

    if order_sensitive:
        return all(
            key_fn(gen) == key_fn(gold)
            for gen, gold in zip(generated_rows, gold_rows)
        )
    else:
        gen_sorted = sorted(key_fn(r) for r in generated_rows)
        gold_sorted = sorted(key_fn(r) for r in gold_rows)
        return gen_sorted == gold_sorted


def save_model_output(preset: str, summary: dict, tag: str = ""):
    """保存评测到 output/<preset>.json，tag 用于区分版本（如 v1/v2）"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 精简 results
    compact_results = []
    for r in summary["results"]:
        compact_results.append({
            "id": r["id"],
            "question": r["question"],
            "difficulty": r.get("difficulty", "?"),
            "status": r.get("status", "?"),
            "match": r.get("match", False),
            "generated_sql": r.get("generated_sql", ""),
            "gold_sql": r.get("gold_sql", ""),
            "generated_rows": r.get("generated_rows", []),
            "gold_rows": r.get("gold_rows", []),
            "rows_count": r.get("rows_count", 0),
            "gold_rows_count": r.get("gold_rows_count", 0),
            "elapsed": r.get("elapsed", 0),
            "complexity": r.get("complexity", "?"),
            "error": r.get("error", ""),
        })

    output = {
        "model": preset,
        "tag": tag,
        "evaluated_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S CST"),
        "summary": {
            "total": summary["total"],
            "passed": summary["passed"],
            "failed": summary["failed"],
            "accuracy": summary["accuracy"],
            "avg_time_sec": summary["avg_time_sec"],
            "tokens": summary["tokens"],
        },
        "results": compact_results,
    }

    out_path = OUTPUT_DIR / f"{preset}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"  输出已保存: {out_path}")


def refresh_comparison():
    """扫描 output/*.json，生成 output/comparison.json（二维对比：模型间 + 版本间）"""
    models = []
    for f in sorted(OUTPUT_DIR.glob("*.json")):
        if f.name == "comparison.json":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            sm = data.get("summary", {})
            if not sm:
                continue
            by_diff = {}
            for r in data.get("results", []):
                diff = r.get("difficulty", "?")
                if diff not in by_diff:
                    by_diff[diff] = {"total": 0, "passed": 0}
                by_diff[diff]["total"] += 1
                if r.get("match"):
                    by_diff[diff]["passed"] += 1

            models.append({
                "model": data["model"],
                "tag": data.get("tag", ""),
                "evaluated_at": data.get("evaluated_at", ""),
                "accuracy": sm.get("accuracy", 0),
                "passed": sm.get("passed", 0),
                "total": sm.get("total", 0),
                "avg_time_sec": sm.get("avg_time_sec", 0),
                "tokens": sm.get("tokens", {}),
                "by_difficulty": {
                    diff: {
                        "accuracy": round(v["passed"] / v["total"] * 100, 1) if v["total"] else 0,
                        "passed": v["passed"],
                        "total": v["total"],
                    }
                    for diff, v in by_diff.items()
                },
            })
        except Exception:
            continue

    if not models:
        return []

    # 按 model 分组，每个 model 内按 accuracy 排序
    by_model: dict[str, list] = {}
    for m in models:
        by_model.setdefault(m["model"], []).append(m)
    for v in by_model.values():
        v.sort(key=lambda x: x["accuracy"], reverse=True)

    output = {
        "generated_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S CST"),
        "cross_model": sorted(models, key=lambda m: m["accuracy"], reverse=True),
        "by_model_versions": {k: [
            {"tag": m["tag"], "accuracy": m["accuracy"],
             "simple_pct": m["by_difficulty"].get("simple",{}).get("accuracy",0),
             "medium_pct": m["by_difficulty"].get("medium",{}).get("accuracy",0),
             "tokens": m["tokens"].get("total_tokens",0),
             "avg_time": m["avg_time_sec"]}
            for m in v
        ] for k, v in by_model.items()},
    }

    comp_path = OUTPUT_DIR / "comparison.json"
    with open(comp_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    return models


def print_report(summary, label=""):
    """打印评测报告（复杂题用子问题成功率）"""
    total = summary["total"]
    results = summary["results"]

    simple = [r for r in results if r.get("difficulty") == "simple"]
    medium = [r for r in results if r.get("difficulty") == "medium"]
    complex_qs = [r for r in results if r.get("difficulty") == "complex"]
    non_complex = simple + medium

    all_ok = sum(1 for r in results if r.get("match"))
    simple_ok = sum(1 for r in simple if r.get("match"))
    medium_ok = sum(1 for r in medium if r.get("match"))
    complex_ok = sum(1 for r in complex_qs if r.get("match"))

    print(f"\n{'='*60}")
    print(f"  正确率 — {label}")
    print(f"{'='*60}")
    print(f"  总: {all_ok}/{total} = {all_ok/total*100:.1f}%")
    print(f"  (简单/中等: SQL执行结果对比 | 复杂: 子问题执行成功率)")
    print(f"  {'─'*50}")
    tokens = summary.get("tokens", {})
    if tokens:
        avg_tok = tokens.get("total_tokens", 0) // total if total else 0
        print(f"  Token: {tokens.get('total_tokens',0):,}  |  {avg_tok:,}/题  |  {summary['avg_time_sec']:.1f}s/题")
    print(f"  {'─'*50}")
    print(f"  {'simple':6s}: {simple_ok}/{len(simple)} ({simple_ok/len(simple)*100:.0f}%)" if simple else "")
    print(f"  {'medium':6s}: {medium_ok}/{len(medium)} ({medium_ok/len(medium)*100:.0f}%)" if medium else "")
    print(f"  {'complex':6s}: {complex_ok}/{len(complex_qs)} ({complex_ok/len(complex_qs)*100:.0f}%) [子问题成功率]" if complex_qs else "")
    print(f"  {'─'*50}")

    failures = [r for r in results if not r.get("match")]
    if failures:
        print(f"  失败 {len(failures)} 题:")
        for f in failures:
            detail = f.get('status','?')
            if f['difficulty'] == 'complex':
                detail = f"子问题: {detail}"
            sql_snippet = (f.get('generated_sql') or 'NONE')[:70]
            print(f"    [{f['id']}] {f['question'][:45]} | {detail} | {sql_snippet}")
            print(f"    [{f['id']}] {f['question'][:50]}")
            print(f"      {f['status']:12s} | rows={f.get('rows_count','?')}/{f.get('gold_rows_count','?')} | {sql_snippet}")
    print(f"{'='*60}")


def print_comparison(models):
    """打印多模型对比 + 版本内对比"""
    if not models:
        return
    print(f"\n{'='*80}")
    print(f"  评测对比 (output/comparison.json)")
    print(f"{'='*80}")
    print(f"  {'Model':<24s} {'Tag':<6s} {'Acc':>6s} {'Simple':>8s} {'Medium':>8s} {'Tokens':>10s} {'Time/q':>7s}")
    print(f"  {'─'*72}")
    for m in sorted(models, key=lambda x: x["accuracy"], reverse=True):
        bd = m.get("by_difficulty", {})
        s_acc = f"{bd.get('simple',{}).get('accuracy',0):.0f}%" if 'simple' in bd else '-'
        m_acc = f"{bd.get('medium',{}).get('accuracy',0):.0f}%" if 'medium' in bd else '-'
        tok = m.get("tokens", {}).get("total_tokens", 0)
        print(f"  {m['model']:<24s} {m.get('tag',''):<6s} {m['accuracy']:>5.1f}%  {s_acc:>8s} {m_acc:>8s} {tok:>10,} {m['avg_time_sec']:>6.1f}s")
    print(f"{'='*80}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Enterprise Text2SQL 评测框架")
    parser.add_argument("--preset", type=str, default=None,
                        help=f"指定模型预设运行（默认用 .env 里的 LLM_PRESET）。可用: {', '.join(ALL_PRESETS)}")
    parser.add_argument("--all", action="store_true",
                        help="对所有预设逐个运行评测")
    parser.add_argument("--compare", action="store_true",
                        help="仅根据已有结果重新生成 comparison.json（不跑评测）")
    parser.add_argument("--tag", type=str, default="",
                        help="版本标记（如 v2），用于区分改动前后的评测")
    parser.add_argument("--difficulty", type=str, default=None,
                        help="只跑指定难度：simple / medium / complex")
    args = parser.parse_args()

    if args.compare:
        models = refresh_comparison()
        print_comparison(models)
        print(f"\ncomparison.json 已更新 ({len(models)} 个模型)")
        return

    with open(EVAL_PATH, encoding="utf-8") as f:
        data = json.load(f)
    questions = data["questions"]
    if args.difficulty:
        questions = [q for q in questions if q.get("difficulty") == args.difficulty]
        if not questions:
            print(f"没有 {args.difficulty} 难度的题目")
            return

    tag = args.tag or datetime.now(CST).strftime("%m%d-%H%M")

    print(f"评测集: {len(questions)} 题")
    print(f"数据库: {DB_PATH}")
    if args.tag:
        print(f"版本标记: {args.tag}")

    presets_to_run = []
    if args.all:
        presets_to_run = ALL_PRESETS
    elif args.preset:
        presets_to_run = [args.preset]
    else:
        presets_to_run = [get_current_preset()]

    print(f"模型: {', '.join(presets_to_run)}")

    for preset in presets_to_run:
        print(f"\n{'='*60}")
        print(f"  [RUN] {preset}")
        print(f"{'='*60}")

        # 切换 .env 中的 LLM_PRESET + 重置 token 统计
        from app.services.llm_service import LLMService
        LLMService.reset_stats()
        old_preset = os.environ.get("LLM_PRESET")
        os.environ["LLM_PRESET"] = preset

        # 重新编译 graph（LLMService 读取 LLM_PRESET 环境变量）
        graph = compile_graph()
        summary = run_eval_set(questions, graph)
        print_report(summary, preset)

        save_model_output(preset, summary, tag=tag)

        # 恢复
        if old_preset:
            os.environ["LLM_PRESET"] = old_preset

    # 多模型对比
    models = refresh_comparison()
    if len(models) >= 2:
        print_comparison(models)


if __name__ == "__main__":
    main()
