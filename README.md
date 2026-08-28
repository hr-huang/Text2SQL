# Enterprise Text2SQL Agent

> **用自然语言问数据库，AI 自动写 SQL、查库、汇总回答。**
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

需要一个 LLM API key（[DeepSeek](https://platform.deepseek.com) 或 [硅基流动](https://siliconflow.cn)，免费注册即用）。

```bash
git clone https://github.com/hr-huang/text2sql.git
cd text2sql

cp .env.example .env
# 编辑 .env 填入 DEEPSEEK_V4_FLASH_KEY 和 SILICONFLOW_API_KEY

docker compose up
```

打开 **http://localhost:8000/demo**

或者一行从 Docker Hub 拉（本地需要有 `.env`）：

```bash
docker run -p 8000:8000 --env-file .env huanghairui/enterprise-text2sql:v1.0.1
```

---

## 🗣️ 试试这些问题

内置了一个 27 张表的电商 demo 数据库，进聊天界面直接问：

```
•  上个月销售额超过 5000 元的商品有哪些？
•  各物流公司的签收率是多少？
•  评分最高的 10 个商品是哪些？
•  每个供应商供应了多少种商品和多少类品类？
```

AI 会自动：听懂问题 → 找相关表 → 生成 SQL → 跑数据库 → 用人话回答，同时右侧流程图实时展示每一步在做什么。

---

## 🔌 接入你自己的数据库

项目默认带一个电商 SQLite demo。要换成你自己的数据，**3 步**：

### 第 1 步：把数据库文件放进去

```bash
cp /path/to/your.db data/mydb.db
```

### 第 2 步：生成 Schema 索引

Schema 索引告诉 AI「有哪些表、每个字段是什么、表之间怎么关联」。跑一次：

```bash
python scripts/build_schema_catalog.py data/mydb.db mydb
```

会生成 `data/schema_catalog.json`，内容大致是：

```json
{
  "datasource_id": "mydb",
  "tables": [
    {
      "table_name": "users",
      "primary_key": "id",
      "columns": [
        {"column_name": "id", "type": "INTEGER", "is_primary_key": true},
        {"column_name": "city", "type": "TEXT", "sample_values": ["北京", "上海"]}
      ]
    }
  ],
  "relationships": [...]
}
```

> **字段语义很重要**：脚本会自动采样每个字段的值（见 `sample_values`），这些样本会喂给 LLM 帮它判断字段含义。如果你的字段是英文缩写（如 `amt`），建议手动在 `schema_catalog.json` 里补 `business_name` 和 `description`，准确率会明显提升。

### 第 3 步：注册数据源

编辑 `app/services/db_service.py`，在 `datasource_map` 加一行：

```python
self.datasource_map = {
    "ecommerce_db": project_root / "data" / "ecommerce.db",
    "mydb": project_root / "data" / "mydb.db",   # ← 加这行
}
```

重启服务，前端数据源下拉里就能选 `mydb` 了。

### 可选：清空旧的向量索引

换库后旧的向量索引就失效了，建议清掉让它重建：

```bash
rm -rf chroma_data/*
```

下次启动会自动用新 Schema 重建索引（首次会慢一点，因为要 embedding 所有表和字段）。

---

## ⚙️ 配置

所有配置都在 `.env`，改完重启生效。

### 换 LLM

项目用 OpenAI 兼容协议，**不绑死任何厂商**。改 `.env` 里的 `LLM_PRESET` 即可切换：

```bash
LLM_PRESET=deepseek_v4_flash    # 默认，便宜快
# LLM_PRESET=ali_qwen_plus     # 阿里通义
# LLM_PRESET=gemini_flash      # Google Gemini
# LLM_PRESET=kimi_8k           # 月之暗面 Kimi
# LLM_PRESET=mimo_flash        # 小米 MiMo
```

每个 preset 配三行（以 DeepSeek 为例）：

```bash
DEEPSEEK_V4_FLASH_KEY=sk-xxx
DEEPSEEK_V4_FLASH_URL=https://api.deepseek.com/v1
DEEPSEEK_V4_FLASH_MODEL=deepseek-chat
```

### RAG 检索

```bash
SILICONFLOW_API_KEY=sk-xxx      # embedding + rerank 服务
RAG_THRESHOLD=15                # 表数 ≤ 此值则全量返回 schema（小库没必要走检索）
RAG_HYBRID_ENABLED=1            # 向量 + BM25 混合检索
RAG_RERANK_ENABLED=1            # bge-reranker 精排
```

> 如果你的库只有十几张表，可以设 `RAG_THRESHOLD=50` 关掉检索（全量 schema 塞进 prompt 也够用，还省一次 embedding 调用）。

---

## 🏗️ 架构

![Architecture diagram](docs/architecture.svg)

基于 LangGraph StateGraph 构建多节点 Agent 状态机，用 Conditional Edge 实现意图路由、复杂度分流、执行失败恢复。

| 阶段 | 节点 | 作用 |
|---|---|---|
| 理解 | `detect_intent` → `classify` | 判断是不是数据问题、简单还是复杂 |
| 检索 | `semantic` → `schema` | 抽指标维度 → **4 阶段 RAG** 找相关表字段 |
| 生成 | `sql_gen` → `sql_review` → `self_reflection` | 生成 SQL → Function Calling 审查 → LLM 自评风险 |
| 执行 | `validate` → `execute` | 语法/安全校验 → 跑数据库 |
| 修复 | `sql_repair`（按需） | 失败时进入 ReAct 循环，调工具自诊，最多 3 次 |
| 回答 | `answer` | 汇总成自然语言 |

复杂问题会走 `decompose` → `orchestrator`：先拆成子问题，拓扑排序后串行执行，上下文传递给下一步。

---

## 🔍 多阶段 RAG 怎么工作

```
用户问题
   │
   ├─→ ① 向量召回   bge-m3 → ChromaDB      （语义相似）
   ├─→ ② 关键词召回 BM25 + jieba 分词      （精确命中）
   │
   ▼
③ RRF 融合（Reciprocal Rank Fusion）
   │
   ▼
④ bge-reranker-v2-m3 精排
   │
   ▼
Top-K 表 + Top-N 字段 → 喂给 SQL 生成
```

**为什么需要两路召回**：向量对 `vip_level` 这类专有名词召回差；BM25 对"上个月销量最好"这类口语化问法召回差。两者互补。

**实测**：在 27 张表的 demo 库上，检索命中 12 张相关表，prompt 比全量 schema 小 23%。

---

## 🧪 跑评测

内置 60 道分层评测题（simple 29 / medium 27 / complex 4）：

```bash
# 跑全部
python scripts/run_evaluation.py --tag my_exp

# 只跑中等难度
python scripts/run_evaluation.py --difficulty medium

# 看失败归因
python scripts/analyze_bad_cases.py deepseek_v4_flash

# 多模型横向对比
python scripts/run_evaluation.py --all
```

结果输出到 `output/<preset>/`，含 `summary.json` 和 `bad_cases.md`。

**当前成绩**（DeepSeek-V4-Flash，60 题黄金评测集）：

![Evaluation results](docs/eval_results.svg)

上图是三轮优化的演进：v1 纯向量 RAG → v2 加混合检索 + Self-Reflection → v3 加针对性 few-shot。最新一轮的精确数字：

| 难度 | 结果 |
|---|---|
| Simple | 100% (29/29) |
| Medium | 96.3% (26/27) |
| Complex | 75% (3/4) |

> simple / medium 用执行结果等价校验；complex 记录子任务执行状态（子问题答案可能不唯一）。

---

## 🛠️ 技术栈

| 层 | 技术 |
|---|---|
| Agent 编排 | LangGraph 1.0+ |
| LLM | DeepSeek / Qwen / Gemini / Kimi / MiMo（OpenAI 兼容，12 预设） |
| Embedding + Rerank | 硅基流动 `BAAI/bge-m3` + `BAAI/bge-reranker-v2-m3` |
| 关键词检索 | rank_bm25 + jieba |
| 融合算法 | RRF（Reciprocal Rank Fusion） |
| 向量库 | ChromaDB（持久化 + schema hash 缓存） |
| 后端 | FastAPI + SSE 流式 |
| 前端 | 原生 HTML/CSS/JS + ECharts + SVG |
| 数据库 | SQLite（只读接入） |
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
├── build_schema_catalog.py   # 从你的数据库生成 Schema 索引
├── init_ecommerce_db.py      # 初始化 demo 电商库
├── run_evaluation.py         # 评测主入口
├── analyze_bad_cases.py      # Bad Case 自动归因
├── deploy_docker.sh          # 一键推 Docker Hub
└── pull_and_run.sh           # 一键拉取并启动

data/               # 评测集 + Schema + SQLite
docs/               # 架构图、评测图、详细讲解
output/             # 评测输出（gitignore）
```

---

## ❓ 常见问题

**Q：支持 MySQL / PostgreSQL 吗？**

目前只实现 SQLite adapter。要接其他库，改 `app/services/db_service.py`（执行层）和 `scripts/build_schema_catalog.py`（Schema 提取层）两个文件即可，其他代码不用动。

**Q：会不会改到我的数据？**

不会。所有 SQL 都强制走只读：
- sqlglot 解析 AST，拒绝任何 `INSERT` / `UPDATE` / `DELETE` / `DROP` 等非 SELECT 语句
- 自动注入 `LIMIT 500`，防止一次返回过多行

**Q：检索不到我想要的字段怎么办？**

先检查 `data/schema_catalog.json` 里该字段的 `sample_values` 是否有值——样本值是 LLM 判断字段语义的关键依据。如果字段是缩写，手动补 `business_name` 和 `description`。

**Q：为什么我的库没走 RAG 检索？**

表数 ≤ `RAG_THRESHOLD`（默认 15）时会全量返回 schema，这是刻意设计——小库全量塞进 prompt 既准又省事。想强制走检索就调小这个值。

**Q：启动后向量索引重建很慢？**

首次启动要给所有表和字段做 embedding，表多时会慢。之后有 schema hash 缓存，Schema 不变就跳过重建。

---

## 🤝 Contributing

见 [CONTRIBUTING.md](CONTRIBUTING.md)。核心约定：改 prompt 前先跑 `analyze_bad_cases.py` 看当前错题，改完跑评测对比 before/after。

更详细的设计讲解见 [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md)。

---

## 📄 License

MIT — 详见 [LICENSE](LICENSE)。
