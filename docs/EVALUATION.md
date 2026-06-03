# Evaluation Report

This project uses execution accuracy as the main metric: a generated SQL query is counted as correct only when its execution result matches the `gold_sql` result in the evaluation set.

## Evaluation Set

| File | Purpose | Size |
| --- | --- | ---: |
| `data/eval_questions.json` | 60 evaluation questions with `gold_sql` labels. Difficulty split: 29 simple, 27 medium, 4 complex. | 20 KB |
| `data/schema_catalog.json` | Database schema catalog used by schema retrieval and prompt construction. | 77 KB |
| `output/comparison.json` | Compact cross-model and cross-version summary. Kept in Git as reproducible evidence. | 5 KB |

The large per-question model outputs are intentionally ignored because they are generated artifacts and can be recreated with `scripts/run_evaluation.py`.

## Output Naming Policy

The repository should keep one compact evidence file in Git:

```text
output/comparison.json
```

Full model outputs are useful locally, but they should not be committed because they are large and change often. Recommended local naming:

```text
output/runs/deepseek_v4_flash_v8.json
output/runs/mimo_2_5_flash_v2.json
output/runs/kimi_32k_v1.json
```

The current historical files such as `deepseek_v4_flash.json` and `deepseek_v4_flash_v1.json` came from earlier evaluation runs. For documentation and job review, cite the representative rows in `comparison.json` instead of listing every generated file in README.

## Latest Result

| Model | Version | Accuracy | Passed | Simple | Medium | Complex | Avg time | Tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| DeepSeek V4 Flash | v8 | **91.7%** | 55 / 60 | 29 / 29 | 23 / 27 | 3 / 4 | 44.9s | 705,132 |

Why this matters:

- Simple questions are solved on this run: 100.0%.
- Medium questions improved from 74.1% to 85.2%.
- Complex questions improved from 0% to 75% after adding decomposition and orchestrated sub-query execution.

## Version Comparison

| Output | Version | Accuracy | Simple | Medium | Complex | Avg time |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `deepseek_v4_flash.json` | v8 | **91.7%** | 100.0% | 85.2% | 75.0% | 44.9s |
| `deepseek_v4_flash_v1.json` | v1 | 80.0% | 96.6% | 74.1% | 0.0% | 29.3s |
| `mimo_2_5_flash.json` | v2 | 80.0% | 96.6% | 74.1% | 0.0% | 40.1s |
| `mimo_flash_v1.json` | v1 | 78.3% | 96.6% | 70.4% | 0.0% | 61.7s |
| `gemini_flash.json` | v2 | 1.7% | 3.4% | 0.0% | 0.0% | 0.5s |

## What Changed From v1 to v8

| Area | v1 behavior | v8 behavior | Effect |
| --- | --- | --- | --- |
| Complex questions | Classified but not solved end-to-end. | Decomposed into sub-questions, executed by `orchestrator`, then merged. | Complex accuracy moved from 0 / 4 to 3 / 4. |
| SQL review | Generated SQL moved too quickly to execution. | Review Agent checks schema, semantics, JOIN path, time functions, and aggregation grain. | Medium accuracy moved from 20 / 27 to 23 / 27. |
| Simple question reliability | One simple case still failed. | All simple questions passed in the v8 run. | Simple accuracy moved from 28 / 29 to 29 / 29. |
| Repair path | Execution errors had limited recovery. | Repair Agent can inspect schema, rewrite SQL, retry, or give up with a reason. | Better resilience on schema and execution failures. |
| Evaluation loop | Single model result. | Cross-model, cross-version comparison with compact summary. | Clear evidence of iteration rather than demo-only behavior. |

## Reproduce

```bash
python scripts/init_ecommerce_db.py
python scripts/build_schema_catalog.py
python -m scripts.run_evaluation --preset deepseek_v4_flash --tag v8
python -m scripts.run_evaluation --compare
```

The command regenerates `output/comparison.json`. Full per-question files remain local generated artifacts.
