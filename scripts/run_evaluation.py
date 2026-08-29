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

# 允许从任意目录直接执行：python scripts/run_evaluation.py
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv()

from app.workflow.state_helpers import create_initial_state
from app.workflow.graph import compile_graph
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


def run_eval_set(questions, graph, force_decompose: bool = False):
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
            force_decompose=force_decompose,
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

        # ── 复杂题：路由验证 + 子任务执行 + 最终答案比对 ──
        routing_ok = None
        sub_ok = None
        answer_match = None
        gold_rows: list[dict] = []
        judge_equiv = None
        judge_reason = ""
        if is_complex:
            # ① 路由验证：必须真的走 decompose → orchestrator
            debug = final.get("debug_trace", []) or []
            visited = {e.get("node") for e in debug if isinstance(e, dict)}
            routing_ok = {"decompose", "orchestrator"} <= visited

            sub_results = final.get("sub_results", [])
            if not sub_results:
                # 没走编排（classify 判成简单题 / decompose 认为单条 SQL 可解）
                # → 回退到结果等价校验：单条 SQL 答对也算对
                gold_rows = execute_gold_sql(q["gold_sql"])
                answer_match = compare_results(
                    rows, gold_rows,
                    order_sensitive=q.get("order_sensitive", False),
                )
                if answer_match:
                    match, status = True, "pass"
                else:
                    # 规则层不过 → 交给 LLM 判语义等价（容忍格式/标识/粒度差异）
                    judge_equiv, judge_reason = llm_judge(q["question"], rows, gold_rows)
                    match = judge_equiv
                    status = "pass|judge" if judge_equiv else "no_decompose"
            else:
                # ② 子任务执行成功率
                ok = sum(1 for r in sub_results if not r.get("error") and len(r.get("rows", [])) > 0)
                fail = len(sub_results) - ok
                sub_ok = f"{ok}/{len(sub_results)}"

                # ③ 最终答案比对：最后一步的结果集 vs gold_sql 结果集
                gold_rows = execute_gold_sql(q["gold_sql"])
                last_rows = sub_results[-1].get("rows", []) or []
                answer_match = compare_results(
                    last_rows, gold_rows,
                    order_sensitive=q.get("order_sensitive", False),
                )

                if fail:
                    match, status = False, f"sub_fail({sub_ok})"
                elif answer_match:
                    match, status = True, "pass"
                else:
                    # 规则层不过 → 交给 LLM 判语义等价
                    judge_equiv, judge_reason = llm_judge(q["question"], last_rows, gold_rows)
                    match = judge_equiv
                    status = "pass|judge" if judge_equiv else "answer_mismatch"
            if not routing_ok:
                status = f"{status}|not_routed"
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
            "routing_ok": routing_ok,
            "sub_ok": sub_ok,
            "answer_match": answer_match,
            "judge_equiv": judge_equiv,
            "judge_reason": judge_reason,
            # complex 逐步明细：人工核验口径差异 vs 真错 时必须能回溯
            "sub_results": final.get("sub_results", []) if is_complex else None,
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


def _normalize_value(v) -> str:
    """归一化单元格值用于比较。

    浮点数必须做容差：LLM 返回 14.125 而 gold 写 ROUND(...,2) 得 14.13，
    语义相同但字符串不等。统一按 2 位小数比较，避免精度差异造成误判。
    """
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, (int, float)):
        return f"{round(float(v), 2):.2f}"
    return str(v)


def compare_results(generated_rows: list[dict], gold_rows: list[dict], order_sensitive: bool = False) -> bool:
    """比较两个结果集是否等价。"""
    if len(generated_rows) != len(gold_rows):
        return False
    if not generated_rows and not gold_rows:
        return True

    def row_to_values(row: dict, keys: list[str] | None = None) -> tuple:
        if keys is None:
            keys = sorted(row.keys())
        return tuple(_normalize_value(row[k]) for k in keys if k in row)

    gen_keys = list(generated_rows[0].keys())
    gold_keys = list(gold_rows[0].keys())
    common = [k for k in gen_keys if k in gold_keys]

    def row_to_values_by_position(row: dict) -> tuple:
        return tuple(_normalize_value(v) for v in row.values())

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


JUDGE_SYSTEM_PROMPT = """你是严谨的 SQL 查询判分员。你只判断两个结果集是否「语义等价」，不做其他分析。

判断标准：
- 两个结果集必须是在回答同一个问题
- 「语义等价」指包含相同的信息：同一批实体 + 同一批数值/结论

以下差异一律【不算】错误，不要因为它们判 false：
1. 列名不同（如 customer_id vs customer）
2. 行/列顺序不同
3. 标识符表示不同（用 ID 还是用名称，只要指向同一实体）
4. 数值精度不同（14.125 vs 14.13）
5. 聚合粒度不同（每个实体的明细行，vs 每实体一行、其他信息用逗号拼接——只要实体集合和值相同）
6. 多返回或漏返回了非核心列（如多返回了筛选条件用的数值）

只有在【实体集合不同】或【核心数值不同】时才判 false。

输出 JSON：{"equivalent": true/false, "reason": "一句话说明"}"""


def _trim_rows(rows: list[dict], limit: int = 60) -> str:
    """结果集转文本，超长截断并注明总数，避免 LLM judge 输入过长。"""
    if not rows:
        return "（空）"
    text = json.dumps(rows[:limit], ensure_ascii=False)
    if len(rows) > limit:
        text += f"\n…（共 {len(rows)} 行，仅显示前 {limit} 行）"
    return text


def llm_judge(question: str, gen_rows: list[dict], gold_rows: list[dict]) -> tuple[bool, str]:
    """第 2 层判分：规则匹配不过时，让 LLM 判断语义等价。

    Returns (equivalent, reason)。judge 本身异常时保守返回 (False, 异常信息)。
    """
    from app.services.llm_service import LLMService

    user_prompt = (
        f"问题：{question}\n\n"
        f"系统生成的答案（{len(gen_rows)} 行）：\n{_trim_rows(gen_rows)}\n\n"
        f"标准答案（{len(gold_rows)} 行）：\n{_trim_rows(gold_rows)}\n\n"
        "这两个答案语义等价吗？"
    )
    try:
        result = LLMService().generate_json(
            system_prompt=JUDGE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
        return bool(result.get("equivalent")), str(result.get("reason", ""))
    except Exception as exc:
        return False, f"LLM judge 异常: {type(exc).__name__}: {exc}"


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
            # complex 专用：路由是否走到 orchestrator / 子任务成功率 / 答案是否比对通过
            "routing_ok": r.get("routing_ok"),
            "sub_ok": r.get("sub_ok"),
            "answer_match": r.get("answer_match"),
            "judge_equiv": r.get("judge_equiv"),
            "judge_reason": r.get("judge_reason"),
            "sub_results": r.get("sub_results"),
            # 保留 trace（含每节点耗时/token + schema 节点返回的候选表），
            # analyze_bad_cases.py 依赖它做 table_out_of_scope / missing_join 判定。
            "debug_trace": r.get("debug_trace", []),
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

    # tag 进文件名：同一 preset 多次跑不再互相覆盖（否则 A/B 对比数据会自毁）
    suffix = f"_{tag}" if tag else ""
    out_path = OUTPUT_DIR / f"{preset}{suffix}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # 同时写一份固定名 latest，保证 analyze_bad_cases.py 等依赖它的脚本仍可用
    latest_path = OUTPUT_DIR / f"{preset}.json"
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"  输出已保存: {out_path}")
    print(f"  latest 副本: {latest_path}")


def refresh_comparison():
    """扫描 output/*.json，生成 output/comparison.json（二维对比：模型间 + 版本间）"""
    models = []
    seen: set[tuple] = set()
    for f in sorted(OUTPUT_DIR.glob("*.json")):
        if f.name == "comparison.json":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            sm = data.get("summary", {})
            if not sm:
                continue
            # 去重：latest 副本（{preset}.json）与 {preset}_{tag}.json 内容相同，
            # 按 (model, tag, evaluated_at) 去重，避免 comparison 里出现重复行
            dedup_key = (data["model"], data.get("tag", ""), data.get("evaluated_at", ""))
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
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
    print(f"  (简单/中等: SQL执行结果对比 | 复杂: 路由 + 子任务 + 答案三重校验)")
    print(f"  {'─'*50}")
    tokens = summary.get("tokens", {})
    if tokens:
        avg_tok = tokens.get("total_tokens", 0) // total if total else 0
        print(f"  Token: {tokens.get('total_tokens',0):,}  |  {avg_tok:,}/题  |  {summary['avg_time_sec']:.1f}s/题")
    print(f"  {'─'*50}")
    print(f"  {'simple':6s}: {simple_ok}/{len(simple)} ({simple_ok/len(simple)*100:.0f}%)" if simple else "")
    print(f"  {'medium':6s}: {medium_ok}/{len(medium)} ({medium_ok/len(medium)*100:.0f}%)" if medium else "")
    if complex_qs:
        print(f"  {'complex':6s}: {complex_ok}/{len(complex_qs)} ({complex_ok/len(complex_qs)*100:.0f}%)")
        routed = sum(1 for r in complex_qs if r.get("routing_ok"))
        subok = sum(1 for r in complex_qs
                    if r.get("sub_ok") and r["sub_ok"].split("/")[0] == r["sub_ok"].split("/")[1])
        ansm = sum(1 for r in complex_qs if r.get("answer_match"))
        judged = sum(1 for r in complex_qs if r.get("judge_equiv"))
        n = len(complex_qs)
        print(f"            ├ 走 decompose→orchestrator : {routed}/{n} ({routed/n*100:.0f}%)")
        print(f"            ├ 子任务全部执行成功       : {subok}/{n} ({subok/n*100:.0f}%)")
        print(f"            ├ 规则层匹配 gold_sql       : {ansm}/{n} ({ansm/n*100:.0f}%)")
        print(f"            └ LLM judge 补判通过        : {judged}/{n}")
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
    parser.add_argument("--force-decompose", action="store_true",
                        help="强制走 decompose→orchestrator 编排路径（评测用）。"
                             "默认不强制，保留 LLM 的智能判断——很多多跳题单条 SQL 也能解。")
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
        summary = run_eval_set(questions, graph, force_decompose=args.force_decompose)
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
