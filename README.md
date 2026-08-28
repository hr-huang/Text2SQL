# Enterprise Text2SQL Agent

> **自然语言问数据库，AI 自动写 SQL、查库、汇总回答。**
>
> 基于 LangGraph 的多节点 Agent · 4 阶段 RAG · Self-Reflection · ReAct 自修复

<p>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/langgraph-1.0%2B-green.svg" alt="LangGraph">
  <a href="https://hub.docker.com/r/huanghairui/enterprise-text2sql"><img src="https://img.shields.io/docker/pulls/huanghairui/enterprise-text2sql?label=docker%20pulls" alt="Docker Pulls"></a>
</p>

---

## ⚡ 30 秒跑起来

需要一个 LLM API key（[DeepSeek](https://platform.deepseek.com) 或 [硅基流动](https://siliconflow.cn) 都行，免费注册即用）。

```bash
git clone https://github.com/hr-huang/text2sql.git
cd text2sql

cp .env.example .env
# 编辑 .env 填入 DEEPSEEK_V4_FLASH_KEY 和 SILICONFLOW_API_KEY

docker compose up
```

打开 http://localhost:8000/demo

或者一行命令从 Docker Hub 拉（需要你本地有 `.env`）：

```bash
docker run -p 8000:8000 --env-file .env huanghairui/enterprise-text2sql:v1.0.1
```

---

## 🗣️ 试试这些问题

进聊天界面后随便问：

```
•  上个月销售额超过 5000 元的商品有哪些？
•  各物流公司的签收率是多少？
•  客户里有多少是 VIP？
•  价格高于品类均价的商品有哪些？
```

AI 会自动：

1. 听懂你在问什么
2. 找相关数据库表
3. 生成 SQL
4. 跑数据库
5. 用人话回答 + 展示流程图

---

## 🏗️ 架构

![Architecture diagram](docs/architecture.svg)

基于 LangGraph StateGraph 构建多节点 Agent 状态机，使用 Conditional Edge 实现意图路由、复杂度分流、执行失败恢复等流程控制。

点 [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md) 看完整讲解（给非技术人也能看懂 + 给面试官讲技术取舍）。

---

## ✨ 关键能力

| | 能力 | 实现 |
|---|---|---|
| 🧠 | **Agent 状态机** | LangGraph StateGraph + Conditional Edge（意图路由、复杂度分流、执行恢复） |
| 🛠️ | **Tool Use Agent** | SQL Review Agent 用 Function Calling 在 `check_schema` / `fix_sql` / `approve_sql` 间自主决策（已验证） |
| 🧩 | **多步规划** | 复杂问题自动拆解为子问题 + 拓扑排序执行（Orchestrator） |
| 🪞 | **自我反思** | Self-Reflection 节点让 LLM 自评 SQL 风险等级 |
| 🔁 | **ReAct 自修复** | 执行失败进入 ReAct 循环：`schema_lookup` / `rewrite_sql` / `execute_sql` / `give_up` 四工具自主诊断，Observation 回灌下轮（已验证） |
| 🔍 | **多阶段 RAG** | 向量 (bge-m3) + BM25 (rank_bm25) + RRF 融合 + Rerank (bge-reranker-v2-m3) |
| 📊 | **可观测性** | trace_wrapper 自动采集每节点耗时 + Token + Tool 调用 |
| 🧪 | **评测闭环** | 60 题分层评测集 + 自动 Bad Case 归因 |
| 🐳 | **一键部署** | Docker + Docker Compose，已发布至 [Docker Hub](https://hub.docker.com/r/huanghairui/enterprise-text2sql) |

> **架构定位**：这是一个 LangGraph 工作流 + 两个独立 Agent（SQL Review / ReAct Repair）+ 一个复杂任务编排器（Orchestrator），**不是"多 Agent 协作系统"**——后者通常意味着有 Supervisor、Agent 间消息协议、独立 state/message history，本项目没有这些。

---

## 📊 评测方法与结果

**评测集**：60 道题，按难度分层（simple 29 / medium 27 / complex 4）。

**评测方法**：

| 难度 | 判定方式 |
|---|---|
| **simple / medium** | 生成 SQL 跑数据库 → 与标准 SQL 的执行结果集做**等价比较**（无序、行集合相等） |
| **complex** | 记录**子任务执行状态与失败路径**（子问题答案可能不唯一，暂不做统一最终结果等价比较） |

**迭代轨迹**：

| 迭代 | Simple | Medium | 关键改动 |
|---|---|---|---|
| v1 | 97% | 74% | 纯向量 RAG 基线 |
| + RAG 增强 + 自反思 | 100% | 82% | BM25 + Rerank + RRF + Self-Reflection |
| + 定向 few-shot | 100% | **96%** | 基于 Bad Case 归因增加 4 道多 JOIN / 状态表示例 |

![Eval results](docs/eval_results.svg)

### 🔍 关于 RAG 效果：诚实数据

修掉一个静默 fallback bug 后重跑，**准确率持平，但 token 成本下降 23%**：

| 指标 | 修复前 | 修复后 | 说明 |
|---|---|---|---|
| Medium 准确率 | 96.3% | 96.3% | **持平** |
| Token 消耗 | 486,205 | 373,267 | **-23%** |

**诚实结论**：在当前 27 张表的规模下，RAG 的价值是**降低 prompt 成本**，而非提升准确率——因为全量 schema 也塞得进 prompt。RAG 的准确率优势要到 100+ 张表、prompt 塞不下时才会显现。

> 这也是个有价值的工程观察：**不要为了用 RAG 而用 RAG**，要先量清楚它在你的数据规模下到底带来什么。

### 🔍 关于 Tool Use：真实实现

两个 Agent 都用 Function Calling，不是"伪装的"：

| Agent | 工具 | 循环 |
|---|---|---|
| **SQL Review Agent** | `check_schema` / `fix_sql` / `approve_sql` | 单轮决策 |
| **ReAct Repair Agent** | `schema_lookup` / `rewrite_sql` / `execute_sql` / `give_up` | 多轮 Thought→Action→Observation 循环，最多 3 次执行尝试 |

每次工具调用结果会回灌进下一轮 prompt（`observations`），这是标准 ReAct 模式。

---

## 🛠️ 技术栈

| 层 | 技术 |
|---|---|
| Agent 编排 | LangGraph 1.0+ |
| LLM | DeepSeek / Qwen / Gemini / Kimi / MiMo（OpenAI 兼容，12 预设） |
| Embedding + Rerank | 硅基流动 `BAAI/bge-m3` + `BAAI/bge-reranker-v2-m3` |
| 关键词检索 | rank_bm25 + jieba |
| 融合算法 | RRF (Reciprocal Rank Fusion) |
| 向量库 | ChromaDB（持久化 + schema hash 缓存） |
| 后端 | FastAPI + SSE 流式 |
| 前端 | 原生 HTML/CSS/JS + ECharts + SVG |
| 数据库 | SQLite（只读） |
| SQL 工具 | sqlglot |
| 容器化 | Docker + Docker Compose |

---

## 📁 项目结构

```
app/
├── agents/         # SQL Review Agent（Function Calling）+ ReAct Repair Agent
├── api/routes/     # FastAPI 路由
├── nodes/          # LangGraph 节点函数（每个是 state → dict 的纯函数）
├── prompts/        # 集中管理所有 prompt
├── schemas/        # TypedDict state + Pydantic
├── services/       # db / llm / schema 三个核心服务
├── workflow/       # StateGraph 装配 + orchestrator + trace_wrapper
└── utils/

scripts/
├── run_evaluation.py        # 评测主入口
├── analyze_bad_cases.py     # 自动 Bad Case 归因（按 AST + 候选 schema + 执行结果）
├── deploy_docker.sh         # 一键推 Docker Hub
└── pull_and_run.sh          # 一键拉取并启动

frontend/           # 单页 SPA（无打包）
data/               # 评测集 + Schema + SQLite
docs/               # 架构图、评测图、详细讲解
output/             # 评测输出（gitignore）
```

---

## 🔬 跑评测

```bash
# 用 .env 里的 LLM_PRESET 跑
python scripts/run_evaluation.py --tag my_exp

# 指定难度
python scripts/run_evaluation.py --difficulty medium

# 失败归因
python scripts/analyze_bad_cases.py deepseek_v4_flash

# 多模型对比
python scripts/run_evaluation.py --all
```

输出在 `output/<preset>/`，含 `summary.json` 和 `bad_cases.md`。

---

## 📚 进阶阅读

- **[docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md)** — 完整项目讲解（分 3 层：非技术人、技术人、面试官视角）
- **[docs/architecture.svg](docs/architecture.svg)** — 架构图源文件
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — 如何贡献

---

## 🗺️ Roadmap

- [ ] 多模型路由（简单题用小模型省 token）
- [ ] 查询缓存（重复问题直接返回）
- [ ] Query Rewrite（用户口语 → 标准查询）
- [ ] MCP Server 化
- [ ] 多数据库接入（MySQL / PG）
- [ ] LangSmith / LangFuse 集成
- [ ] Complex 题统一结果等价评测（取代子任务状态判断）

---

## 📄 License

MIT — 详见 [LICENSE](LICENSE)。

---

> 求职项目 · 目标岗位：AI Agent 工程师 · 重点展示：Tool Use / Planning / Reflection / ReAct / Observability / Evaluation
