"""多模型评测对比 — 逐个跑、逐个保存、最后对比"""

import json
import os
import time
from pathlib import Path

from app.workflow.graph import compile_graph
from scripts.run_evaluation import run_eval_set, print_report

EVAL_PATH = Path(__file__).resolve().parent.parent / "data" / "eval_questions.json"
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "evals"

# 要评测的模型列表
MODELS = [
    ("deepseek_v4_flash", "DeepSeek V4 Flash"),
    ("deepseek_v4_pro", "DeepSeek V4 Pro"),
    ("ali_qwen_plus", "阿里 qwen-plus-latest"),
    ("mimo_flash", "小米 MiMo v2-flash"),
    ("mimo_pro", "小米 MiMo v2-pro"),
    ("kimi_8k", "Kimi moonshot-v1-8k"),
]


def main():
    with open(EVAL_PATH, encoding="utf-8") as f:
        questions = json.load(f)["questions"]

    graph = compile_graph()
    OUT_DIR.mkdir(exist_ok=True)

    all_reports = []

    for preset, name in MODELS:
        os.environ["LLM_PRESET"] = preset
        print(f"\n{'='*60}")
        print(f"  {name} ({preset})")
        print(f"{'='*60}")

        t0 = time.time()
        try:
            summary = run_eval_set(questions, graph)
        except Exception as e:
            print(f"  ❌ 失败: {e}")
            continue

        dt = time.time() - t0
        print_report(summary)
        print(f"  耗时: {dt:.0f}s ({dt/60:.1f}min)")

        # 保存单模型结果
        out_path = OUT_DIR / f"{preset}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        # 汇总到对比表
        gen_ok = sum(1 for r in summary["results"] if r.get("generated_sql"))
        all_reports.append({
            "model": name,
            "preset": preset,
            "total": summary["total"],
            "gen_ok": gen_ok,
            "gen_rate": round(gen_ok / summary["total"] * 100, 1),
            "exec_pass": summary["passed"],
            "exec_rate": summary["accuracy"],
            "avg_time": summary["avg_time_sec"],
        })

    # 保存对比表
    cmp_path = OUT_DIR / "comparison.json"
    with open(cmp_path, "w", encoding="utf-8") as f:
        json.dump(all_reports, f, ensure_ascii=False, indent=2)

    # 打印对比表
    print(f"\n{'='*80}")
    print(f"  模型对比总表")
    print(f"{'='*80}")
    print(f"  {'模型':<25s} {'SQL生成成功率':>12s} {'SQL执行成功率':>12s} {'平均耗时':>10s}")
    print(f"  {'─'*25} {'─'*12} {'─'*12} {'─'*10}")
    for r in all_reports:
        print(f"  {r['model']:<25s} {r['gen_rate']:>11.1f}% {r['exec_rate']:>11.1f}% {r['avg_time']:>9.1f}s")
    print(f"{'='*80}")
    print(f"  对比结果: {cmp_path}")


if __name__ == "__main__":
    main()
