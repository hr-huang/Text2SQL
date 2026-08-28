# Enterprise Text2SQL Agent

> **A production-grade Text-to-SQL Agent with multi-stage RAG, self-reflection, and self-repair — built on LangGraph.**

<p>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/langgraph-1.0%2B-green.svg" alt="LangGraph">
  <img src="https://img.shields.io/badge/docker-supported-blue.svg" alt="Docker">
  <a href="https://hub.docker.com/r/huanghairui/enterprise-text2sql"><img src="https://img.shields.io/badge/docker%20hub-huanghairui%2Fenterprise--text2sql-blue.svg" alt="Docker Hub"></a>
  <img src="https://img.shields.io/badge/eval%20accuracy-91.7%25-brightgreen.svg" alt="Accuracy">
  <img src="https://img.shields.io/badge/agent%20nodes-17-purple.svg" alt="Nodes">
</p>

用自然语言问数据库，自动生成 SQL、执行查询、汇总回答 — 不需要懂 SQL。

```
你问：上个月销售额超过 5000 元的商品有哪些？
AI 想：意图 → 复杂度 → 检索相关表 → 生成 SQL → 自评风险 → 执行 → 修复（如失败）→ 汇总
AI 答：返回 Top 商品列表 + 自然语言解释
```

---

## ✨ 核心特性

| | 特性 |
|---|---|
| 🧠 | **17 节点 LangGraph Agent** — 意图识别 / 复杂度分类 / Schema 检索 / SQL 生成 / 审查 / **自反思** / 校验 / 执行 / **ReAct 自修复** |
| 🔍 | **4 阶段 RAG 链路** — 向量召回 (bge-m3) + BM25 关键词召回 + RRF 融合 + bge-reranker-v2-m3 精排 |
| 🪞 | **Self-Reflection 节点** — LLM 对自己生成的 SQL 做风险自评 (low/medium/high) |
| 🔁 | **ReAct 自修复** — SQL 失败时 Agent 调工具诊断，最多重试 3 次 |
| 📊 | **完整可观测性** — 每节点 wall-clock 耗时 + Token 消耗 + Tool 调用，前端 SVG 流程图实时渲染 |
| 📈 | **60 题黄金评测集** + **9 类失败归因报告**（自动分类：检索失败 / 漏 JOIN / WHERE 列用错 / 拆解失败 …） |
| 🐳 | **Docker 一键部署** — 含自动初始化数据库 + schema 索引 |

---

## 📊 评测结果

60 道黄金评测集（simple 29 / medium 27 / complex 4），DeepSeek-V4-Flash 模型。

![Accuracy chart](docs/eval_results.svg)

| 迭代 | Simple | Medium | Complex | 加权 | 关键改动 |
|---|---|---|---|---|---|
| v1（基线） | 97% | 74% | — | — | 纯向量 RAG |
| + RAG 增强 + 自反思 | 100% | 82% | 50% | 88.6% | + BM25 + Rerank + RRF + Self-Reflection 节点 |
| **+ 定向 few-shot** | **100%** | **96%** | **50%** | **91.7%** | + 4 道多 JOIN / 状态表 / 嵌套聚合示例 |

**核心 takeaway**：从错题出发定向设计 few-shot，单文件改动带来 **+14 pp on medium**。

---

## 🏗️ 架构

![Architecture diagram](docs/architecture.svg)

5 个泳道：BRANCH（分支） / MAIN PIPELINE（主流程） / REFLECT（自反思） / RUN & ANSWER（执行与回答） / REPAIR / FAILURE（修复与失败）。

| 关键节点 | 作用 |
|---|---|
| `detect_intent` | 识别是不是数据问题；非数据直接拒答 |
| `classify` | 判定 simple / complex，复杂问题走拆解 |
| `decompose` → `orchestrator` | 复杂问题拆子问题 + 按依赖编排执行 |
| `schema` | **4 阶段 RAG**：向量 + BM25 + RRF + Rerank |
| `sql_gen` | LLM 生成只读 SELECT SQL |
| `sql_review` | Function Calling 审查（调 schema_lookup 工具核对） |
| **`self_reflection`** | 🪞 LLM 自评 SQL 风险（high/medium/low） |
| `validate` → `execute` | SQLGlot 语法校验 + DB 执行 |
| `sql_repair` | 🔁 ReAct 自修复（最多 3 次） |

---

## 🚀 快速开始

### 方式〇：从 Docker Hub 一行拉取（最快）

```bash
docker run -p 8000:8000 --env-file .env huanghairui/enterprise-text2sql:v1.0.0
```

需要同目录有 `.env` 文件（含 `DEEPSEEK_V4_FLASH_KEY` 和 `SILICONFLOW_API_KEY`）。访问 http://localhost:8000/demo 即可。

镜像地址：https://hub.docker.com/r/huanghairui/enterprise-text2sql

### 方式一：本地构建 + docker compose

```bash
cp .env.example .env
# 编辑 .env 填入 DEEPSEEK_V4_FLASH_KEY 和 SILICONFLOW_API_KEY

docker compose up --build
```

启动后访问：

- **聊天界面** → http://localhost:8000/demo
- **健康检查** → http://localhost:8000/health
- **Schema 浏览器** → http://localhost:8000/api/schema

### 方式二：本地运行

```bash
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env 填入 API key

python -m app.main
```

### 推送镜像到 Docker Hub（可选）

```bash
export DOCKERHUB_USER=你的用户名
./scripts/deploy_docker.sh v1.0.0
```

别人拉取运行：

```bash
DOCKERHUB_USER=你的用户名 ./scripts/pull_and_run.sh v1.0.0
```

---

## 🧠 关键设计决策

### 1. 为什么需要混合检索？

- **纯向量**：对 `vip_level` / `customer_id` 这种专有名词召回率低
- **纯 BM25**：对"上个月销量最好"这种语义问法召回差
- **混合（向量 + BM25 + RRF）**：互补，整体召回率提升
- **Rerank**：Cross-encoder 重新打分，Top-10 精度大幅提升

### 2. 为什么需要 Self-Reflection？

LLM 生成的 SQL 经常有**微妙错误**（如选了 `orders.status` 但用户问的是 `shipping_tracking.status`）。Self-Reflection 节点在 validate 之前让 LLM 自评风险，作为**Agent 反思能力的工程化体现**。不阻塞流程（validate + execute + repair 兜底），但高风险时给用户清晰提示。

### 3. 为什么用 TypedDict State + LangGraph？

- 17 个节点的 state 流转可显式追踪
- 条件路由（conditional edges）实现"复杂/简单"分支
- 自修复循环（repair → execute）实现 ReAct
- 自动 checkpointing（如需）

### 4. 失败归因报告（9 类）

不是只统计 pass/fail，而是**自动分类失败原因**，定向优化：

| 类别 | 含义 |
|---|---|
| Schema 检索失败（未召回相关表） | RAG 没找到相关表 |
| LLM 用了候选集之外的表 | LLM 幻觉 / 候选表错误 |
| 漏必要 JOIN | LLM 简化了 JOIN 路径 |
| WHERE 过滤列用错 | 状态列取错表（如 orders.status 替代 shipping_tracking.status） |
| 复杂题拆解失败 | LLM 没把嵌套子查询式问题拆两步 |

跑 `python scripts/analyze_bad_cases.py <preset>` 生成 `output/<preset>/bad_cases.md`。

---

## 📁 项目结构

```
app/
├── agents/                       # 可独立运行的 Agent 单元
│   ├── sql_review_agent.py       #   Function-Calling SQL 审查
│   └── react_sql_repair_agent.py #   ReAct 模式自修复
├── api/routes/                   # FastAPI 路由（SSE 流式）
├── nodes/                        # LangGraph 节点（17 个）
│   ├── intent_node.py            #   🔍 意图识别
│   ├── classify_node.py          #   🏷️ 复杂度分类
│   ├── decompose_node.py         #   🧩 问题拆解
│   ├── semantic_parse_node.py    #   📝 语义解析
│   ├── schema_retrieval_node.py  #   🗄️ 4 阶段 RAG
│   ├── sql_generation_node.py    #   ⚡ 生成 SQL
│   ├── sql_review_node.py        #   🔍 SQL 审查
│   ├── self_reflection_node.py   #   🪞 自反思
│   ├── sql_validation_node.py    #   🛡️ SQL 校验
│   ├── sql_execution_node.py     #   ▶️ 执行查询
│   ├── sql_repair_node.py        #   🔧 ReAct 修复
│   ├── answer_node.py            #   💬 汇总回答
│   └── terminal_nodes.py         #   ❌ 终态节点
├── prompts/                      # 所有 prompt 集中管理
├── schemas/                      # TypedDict state + Pydantic
├── services/
│   ├── db_service.py             #   只读 SQL 执行
│   ├── llm_service.py            #   统一 LLM + token 统计
│   └── schema_service.py         #   多阶段 RAG 检索
├── workflow/
│   ├── graph.py                  #   LangGraph StateGraph 装配
│   ├── orchestrator.py           #   复杂问题编排
│   ├── trace_wrapper.py          #   自动 trace 包装器
│   └── state_helpers.py
└── utils/trace_utils.py

scripts/
├── run_evaluation.py             # 评测主入口
├── analyze_bad_cases.py          # 失败归因报告
├── build_schema_catalog.py       # 生成 schema 索引
├── init_ecommerce_db.py          # 初始化 demo 数据库
├── deploy_docker.sh              # 一键推送 Docker Hub
└── pull_and_run.sh               # 一键拉取并启动

frontend/             # 单页 SPA（无打包，纯 HTML/CSS/JS）
data/                 # 评测集 + Schema + SQLite
docs/                 # 架构图 / 评测结果图
output/               # 评测输出（gitignore）
```

---

## 🛠️ 技术栈

| 层 | 技术 |
|---|---|
| Agent 编排 | LangGraph 1.0+（StateGraph + 条件路由 + ReAct 循环） |
| LLM | OpenAI 兼容协议（DeepSeek / Qwen / Gemini / Kimi / MiMo 等 12 个预设） |
| Embedding + Rerank | 硅基流动 `BAAI/bge-m3` + `BAAI/bge-reranker-v2-m3` |
| 关键词检索 | rank_bm25 + jieba |
| 向量库 | ChromaDB（持久化 + schema-hash 缓存） |
| 后端 | FastAPI + SSE 流式 |
| 前端 | 原生 HTML/CSS/JS + ECharts + SVG 流程图 |
| 数据库 | SQLite（只读接入） |
| 容器化 | Docker + Docker Compose |

---

## 📈 跑评测

```bash
# 单模型（用 .env 里的 LLM_PRESET）
python scripts/run_evaluation.py --tag my_experiment

# 指定难度
python scripts/run_evaluation.py --difficulty medium --tag my_experiment

# 多模型对比
python scripts/run_evaluation.py --all

# 失败归因分析
python scripts/analyze_bad_cases.py deepseek_v4_flash
```

输出结构：

```
output/<preset>/
├── summary.json              # 汇总指标
├── bad_cases.md              # 失败归因报告
├── questions/
│   └── 001.json              # 每题详情
└── sql/
    └── 001.sql               # 每题生成的 SQL
```

---

## 🗺️ Roadmap

- [ ] **多模型路由** — 按问题复杂度自动选模型（简单用小模型省 token，复杂用大模型）
- [ ] **查询缓存** — 重复问题直接返回，省 LLM 调用
- [ ] **Query Rewrite** — 用户口语 → 标准查询改写
- [ ] **MCP Server 化** — 让外部 Agent 能调用本系统
- [ ] **多数据库接入** — MySQL / PostgreSQL / 跨库联邦
- [ ] **LangSmith / LangFuse 集成** — 商业级可观测性
- [ ] **多轮对话** — 实体级对话记忆
- [ ] **CI/CD** — GitHub Actions 自动跑评测

---

## 🤝 Contributing

详见 [CONTRIBUTING.md](CONTRIBUTING.md)。核心约定：

- 改 prompt 前先跑 `analyze_bad_cases.py` 看当前错题
- 改后跑评测对比 before/after
- PR 附数据证明

---

## 📄 License

MIT — 详见 [LICENSE](LICENSE)。

---

## 🙏 致谢

- [LangGraph](https://github.com/langchain-ai/langgraph) — Agent 编排框架
- [SiliconFlow](https://siliconflow.cn) — Embedding + Rerank 服务
- [DeepSeek](https://deepseek.com) — Chat LLM
- [ChromaDB](https://www.trychroma.com) — 向量数据库
- [BAAI](https://github.com/FlagOpen/FlagEmbedding) — bge-m3 / bge-reranker-v2-m3

---

> **求职用项目** · 目标岗位：AI Agent 工程师 · 重点展示：Tool Use / Planning / Reflection / ReAct / Observability / Evaluation
