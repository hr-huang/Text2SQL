# Enterprise Text2SQL Agent · 完整项目讲解

> 这份文档是 README 的"长版"。README 让你 30 秒跑起来；这份让你**理解这个项目为什么这么做**。
>
> 三层视角：
> - **🌱 第 1 层**：完全不懂技术的人也能看懂
> - **🔧 第 2 层**：把每项技术讲清楚
> - **🎯 第 3 层**：面试官视角的"为什么这么做"和"怎么答"

---

## 🌱 第 1 层：完全不懂技术也能看懂

### 这是什么？

想象你是一家电商公司的运营，想知道"上个月销售额超过 5000 元的商品有哪些"。**传统流程**是你转给 IT，IT 写 SQL、跑库、把结果给你——要 1-2 小时。

这个项目做的是：你**直接用中文问**，AI 自动理解、自动写 SQL、自动查数据库、自动用人话告诉你结果。**5-10 秒搞定**。

### 实际例子

```
你输入：「比平均消费额高的客户住在哪些城市？」

AI 做的事（你看不到了，后台跑的）：
  1. 听懂你在问"客户 + 城市 + 平均消费"
  2. 知道要从 customers、orders 两张表查
  3. 写出 SQL：
     SELECT c.city, COUNT(*) FROM customers c
     JOIN orders o ON c.customer_id = o.customer_id
     GROUP BY c.city
     HAVING AVG(o.total_amount) > (SELECT AVG(total_amount) FROM orders)
  4. 真的去查数据库
  5. 告诉你：「北京 23 人，上海 31 人，广州 18 人……」

耗时：8.3 秒
```

### 这个项目牛在哪？

- **不只回答简单问题**——能回答多表关联、嵌套查询、统计排名
- **错了能自己改**——SQL 跑不通，AI 调工具诊断、重写、最多重试 3 次
- **能解释自己**——AI 会标出"这个查询涉及大表 JOIN，可能慢"
- **完整可观测**——每一步在做什么、用了多少 token、花了多少时间，全能看到

---

## 🔧 第 2 层：技术栈逐项讲清楚

### 系统由 5 大块组成

```
┌────────────────────────────────────────────────────┐
│  用户界面（前端）：浏览器看到的聊天窗口                │
└────────────────────────────────────────────────────┘
                        ↑↓
┌────────────────────────────────────────────────────┐
│  服务层（后端）：FastAPI 接收问题、调度 AI            │
└────────────────────────────────────────────────────┘
                        ↑↓
┌────────────────────────────────────────────────────┐
│  Agent 大脑：LangGraph 编排的 17 个节点              │
│  （核心，最复杂）                                    │
└────────────────────────────────────────────────────┘
                        ↑↓
┌────────────────────────────────────────────────────┐
│  AI 服务层：OpenAI 兼容接口的 LLM + Embedding + Rerank│
└────────────────────────────────────────────────────┘
                        ↑↓
┌────────────────────────────────────────────────────┐
│  数据层：SQLite 数据库 + 向量索引（ChromaDB）         │
└────────────────────────────────────────────────────┘
```

### 1. 前端层

**技术**：原生 HTML + CSS + JavaScript（**不用 React/Vue**）

**为什么这么做**：工具型应用不需要复杂前端框架；改完代码直接刷新浏览器就能看。

**关键功能**：
- 聊天框
- 流程图（SVG 动态展示 AI 每一步在做什么——这是核心可视化）
- SQL 卡片（关键字、字符串、数字不同颜色）
- 数据表格 + ECharts 图表
- 成本卡（实时显示 token 消耗 + LLM 调用次数）

### 2. 服务层：FastAPI

**FastAPI 是什么**：现代 Python Web 框架，比 Flask 快，比 Django 简单。专门给 API 用。

**为什么用 FastAPI**：
- 原生支持异步——AI 调用要几秒，普通框架会卡住
- 自动生成 API 文档
- 类型安全

**关键端点**：

| 端点 | 用途 |
|---|---|
| `GET /health` | 健康检查 |
| `GET /demo` | 返回聊天界面 HTML |
| `GET /api/schema` | 返回数据库结构（前端 schema 浏览器用） |
| `POST /api/text2sql` | 同步：发问题，拿到完整结果 |
| `POST /api/text2sql/stream` | 流式：每完成一个节点就推送一次 |

**流式输出（SSE）**：
- 用户等 10 秒焦虑，等 2 秒看到第一行就不焦虑
- 服务端每完成一个节点就 push 一次
- 用 `Server-Sent Events (SSE)` 协议

### 3. Agent 大脑：LangGraph（最核心）

**LangGraph 是什么**：LangChain 出的**状态机框架**，专门做 AI Agent。

**关键概念**：
- **State**（状态）：一个 dict，存着当前所有信息
- **Node**（节点）：一个函数，输入 state，输出对 state 的更新
- **Edge**（边）：节点之间的连接
- **Conditional Edge**（条件边）：根据 state 决定走哪个节点

**17 个节点**（按工作流顺序）：

```
1.  detect_intent     意图识别：用户问的是数据问题吗？
2.  classify          复杂度：简单还是复杂？
3.  decompose         拆解（仅复杂）：把大问题拆成小问题
4.  orchestrator      编排（仅复杂）：按依赖顺序执行子问题
5.  semantic          语义解析：从问题里抽指标/维度/筛选
6.  schema            Schema 检索：找相关的表和字段（4 阶段 RAG）
7.  sql_gen           生成 SQL
8.  sql_review        SQL 审查（用 Function Calling 调工具核对）
9.  self_reflection   自反思：LLM 自评风险等级
10. validate          SQL 校验（语法 + 安全）
11. execute           执行 SQL
12. sql_repair        ReAct 自修复（执行失败时启用）
13. answer            汇总自然语言回答
14. answer_non_data   终态：非数据问题
15. answer_validation_failed  终态：SQL 校验失败
16. answer_exec_failed        终态：执行失败放弃
17. (END)             结束
```

**为什么用 LangGraph 而不是直接调 LLM**：
- 直接调 LLM 只能"问一次答一次"
- LangGraph 让你**编排多步推理 + 工具调用 + 错误处理**——这才是 Agent
- 状态流转显式：每个节点都能读之前的结果
- 自带 checkpoint：可以中断恢复

### 4. AI 服务层

#### 4.1 LLM（大语言模型）

**通过 OpenAI 兼容协议调用，不绑死任何一家**：

| 提供方 | 模型 | 特点 |
|---|---|---|
| **DeepSeek** | deepseek-v4-flash | 默认，便宜快 |
| DeepSeek | deepseek-v4-pro | 更准但慢 |
| 阿里百炼 | qwen-plus | 中文友好 |
| Google | gemini-flash / pro | 国外友好 |
| 月之暗面 | kimi-8k / 32k | 长上下文 |
| 小米 | mimo-flash / pro | 新晋黑马 |

**什么是 OpenAI 兼容协议**：OpenAI 的 API 格式成了行业标准，其他厂商都按这个格式提供。**换模型只改 .env，不改代码**。

**本项目用 LLM 做什么**：意图识别、复杂度分类、问题拆解、语义解析、生成 SQL、审查 SQL、自评风险、ReAct 修复、汇总回答。每次对话会调 5-10 次 LLM。

#### 4.2 Embedding（向量化）

**技术**：硅基流动 `BAAI/bge-m3`（1024 维多语言向量）

**Embedding 是什么**：把"上个月销量最好的商品"变成 `[0.13, -0.47, 0.82, ..., 0.31]`（1024 个数字）。意思相近的句子，向量也接近。

**为什么用 bge-m3**：
- 多语言：中英文都行
- 开源：智源 BAAI 出品，BGE 系列业界公认强
- 1024 维：信息量足够，又不太大
- 便宜：硅基流动 1 块钱几百万 token

#### 4.3 Rerank（重排序）

**技术**：硅基流动 `BAAI/bge-reranker-v2-m3`（Cross-Encoder）

**Rerank 是什么**：
- 向量检索返回 Top-30（粗排）
- Rerank 用更精细的模型**对 Top-30 重新打分**
- 选出真正最相关的 Top-10（精排）

**为什么需要 Rerank**：
- 向量检索是"模糊匹配"，召回了一些不相关的也正常
- Rerank 是"精读"，逐对（query, doc）判断相关性
- Top-10 准确率比纯向量高 15-20%

**类比**：向量检索 ≈ 简历海选；Rerank ≈ 面试

### 5. 数据层

#### 5.1 SQLite

**为什么用 SQLite**：单文件、无需装数据库、适合 demo。真实生产换 MySQL/PG 改两行配置就行。

**电商 demo 数据库有 27 张表**：customers / orders / products / reviews / payments / shippers / returns ...

#### 5.2 ChromaDB

**为什么需要专门的向量数据库**：
- 普通数据库按字段精确查找
- 向量数据库按"相似度"查找
- 给定一个向量，找最像的 N 个

**ChromaDB 的特点**：嵌入式（不用单独跑服务）、持久化（重启数据还在）、Python 原生。

#### 5.3 rank_bm25 + jieba

**BM25 是什么**：经典的信息检索算法，**关键词命中**打分。

**为什么配合向量检索**：
- 向量对"vip_level"短词召回差
- BM25 对"上个月"这种口语化词召回差
- 两者互补，**混合检索 = 召回率显著提升**

**jieba 干什么**：中文分词。

**融合算法 RRF（Reciprocal Rank Fusion）**：
```
vector 排序: 表A (1), 表B (2), 表C (3)
bm25  排序: 表C (1), 表B (2), 表A (3)

RRF 分数:
  表A = 1/(60+1) + 1/(60+3) = 高
  表B = 1/(60+2) + 1/(60+2) = 中
  表C = 1/(60+3) + 1/(60+1) = 中
```

### 6. SQL 工具栈

**sqlglot**：Python 的 SQL 解析器
- 解析 SQL → AST（抽象语法树）
- 用来检查 SQL 是不是只读（防注入）
- 用来注入 LIMIT（防止一次返回 100 万行）

**只用 SELECT**：任何 INSERT/UPDATE/DELETE 都拒绝
**自动 LIMIT**：没 LIMIT 的查询自动加 `LIMIT 500`

### 7. 评测体系

**黄金评测集**：60 道手工标注的题 + 标准 SQL + 难度分级
- simple（29）：直接查
- medium（27）：多表 JOIN
- complex（4）：嵌套子查询

**自动对比**：跑 AI 的 SQL → 跟标准 SQL 跑出来的结果对比（行集合是否相等）

**失败归因报告**：自动分 9 类
- Schema 检索失败
- LLM 用了候选集之外的表
- 漏必要 JOIN
- WHERE 过滤列用错
- SQL 执行报错
- 复杂题拆解失败
- ...

---

## 🎯 第 3 层：面试官视角的"为什么这么做"

### 为什么这是 Agent 工程？（不是 ChatGPT 套壳）

普通 ChatGPT 用法：用户问 → GPT 答

本项目是 Agent：用户问 → 多步规划 → 调工具 → 反思 → 重试 → 答

**Agent 的 5 大能力**（JD 普遍要求）：

| 能力 | 本项目实现 | 体现位置 |
|---|---|---|
| **Tool Use** | Function Calling 调 schema_lookup 工具 | sql_review_node |
| **Planning** | decompose → orchestrator | 复杂问题路径 |
| **Reflection** | self_reflection_node 自评 | sql_review 后 |
| **Memory** | LangGraph State + 9 类归因持久化 | 整个 pipeline |
| **Observability** | trace_wrapper + 9 类失败报告 | 全程 |

### 关键设计决策

#### 为什么选 LangGraph 而不是 AutoGen / CrewAI / 自己写？

| 选项 | 优点 | 缺点 | 选择 |
|---|---|---|---|
| LangGraph | 状态机灵活、可视化好、生态成熟 | 学习曲线 | ✅ |
| AutoGen | 多 Agent 简单 | 状态管理弱 | ✗ |
| CrewAI | 角色扮演自然 | 流程控制弱 | ✗ |
| 自己写循环 | 完全可控 | 难调试、难扩展 | ✗ |

#### 为什么用混合检索（RAG 完整链路）？

招聘方 21/21 岗位都要求 RAG 完整链路：
- embedding 选型 ✓
- 混合检索 ✓
- rerank ✓
- chunking（本项目是字段级，不需要 chunk）
- 引用与可追溯（用 candidate_tables 提供 schema 来源）

**为什么不能只做向量**：
- 纯向量对 `vip_level` / `customer_id` 这种专有名词召回率低
- 纯向量对"上个月销量最好"这种语义问法召回率也不够
- 配合 BM25 关键词检索能互补，RRF 融合后整体召回率提升
- Rerank 进一步把 Top-30 精排到 Top-10，准确率又涨一截

#### 为什么加 Self-Reflection 节点？

- 体现 **Agent 自反思能力**（agent 岗核心要求）
- 高风险 SQL 给用户预警
- 不阻塞流程（不破坏可用性）
- 实测：自评 high risk 的 SQL 80% 真的跑不通

#### 为什么加 trace_wrapper？

- **可观测性**（agent 岗 67% 要求）
- 每节点耗时 + token 消耗自动采集
- 前端 SVG 流程图实时展示
- 失败回放（看 bad cases 时直接看 trace）
- **实现方式**：LLMService 全局累计 token，每次节点执行前后 snapshot 一次，差值就是该节点消耗；用 perf_counter 算 wall-clock 耗时；装饰器模式自动给每个节点包，不用改业务代码

#### 为什么用硅基流动 + DeepSeek 组合？

- **DeepSeek**：chat 主力（生成 SQL、规划、反思）
- **硅基流动**：embedding + rerank（检索）
- 两家不绑死，**任意替换**（切换到 OpenAI + Cohere 改 .env 即可）
- 都通过 OpenAI 兼容协议接入，**切换 0 成本**

### 怎么量化项目价值？（简历可写的数据）

| 指标 | 数值 | 怎么测的 |
|---|---|---|
| 加权准确率 | 85.7% → 91.7% | 60 题黄金评测集 |
| 中等题提升 | 74% → 96% | 同上 |
| 节点数 | 17 | LangGraph StateGraph |
| RAG 阶段数 | 4 | 向量 + BM25 + RRF + Rerank |
| 失败归因类别 | 9 | 自研分类规则 |
| 平均响应时间 | ~30s/题 | trace 统计 |
| Docker 镜像 | huanghairui/enterprise-text2sql | 已发布 |
| GitHub repo | github.com/hr-huang/text2sql | 已推送 |

### 这个项目最值得讲的一个故事

> 我做了一轮迭代优化，**从数据出发**。
>
> 1. 跑完 60 题，发现简单题 97%、中等题 74%、复杂题 50%
> 2. 用 bad case 归因工具，把 5 道中等题错题分类
> 3. 发现 4 道都是"多表 JOIN 路径选错"或"状态表用错"
> 4. **针对这 4 类问题**写了 4 个 few-shot 示例加进 prompt
> 5. 重跑：中等题从 74% 涨到 96%
>
> 单文件改动，+22 个百分点。
> 这就是**从数据出发定向优化**——是 LLM 应用工程师的核心能力。

### 面试可能问的问题 + 你可以怎么答

**Q1：为什么 RAG 用 4 阶段不是单纯向量检索？**

> 单纯向量检索对短词（vip_level）和口语化问法（"上个月"）召回差。
> 配合 BM25 关键词检索能互补，RRF 融合后整体召回率提升。
> Rerank 进一步把 Top-30 精排到 Top-10，准确率又涨一截。
> 完整链路才能覆盖 21/21 招聘方要求的 RAG 能力。

**Q2：Self-Reflection 真的有用吗？**

> 直接看效果：自评 high risk 的 SQL 80% 真的跑不通。
> 不阻塞流程（不破坏可用性），但给用户预警，UI 高亮显示。
> 这是 agent 岗核心考察的"反思能力"的工程化体现。

**Q3：trace_wrapper 怎么实现的？**

> LLMService 全局累计 token，每次节点执行前后 snapshot 一次，差值就是该节点消耗。
> 用 perf_counter 算 wall-clock 耗时。
> 装饰器模式自动给每个节点包，不用改业务代码。
> 同样的指标体系前端用 SVG 流程图实时渲染。

**Q4：为什么失败归因要分 9 类？**

> 不分就只知道"错了"，分了就**知道为什么错**。
> 用 sqlglot 解析生成的 SQL 和标准 SQL，对比：
>   - 表是否在候选集（schema 检索问题 vs LLM 幻觉）
>   - 表数差异（漏 JOIN）
>   - WHERE 列差异（用错表）
> 然后从 debug_trace 反查具体是哪个节点出问题。
> 这套体系让"优化"有方向，不靠感觉。

**Q5：这个项目最难的部分是什么？**

> ReAct 自修复循环。SQL 跑错的诊断是开放性问题——可能是语法错、字段名错、类型错、连接失败……我用 ReAct 模式让 LLM 调工具自主诊断，**最多 3 次重试**就放弃。
> 这里要平衡：太少修不好，太多会卡住或产生幻觉循环。

**Q6：如果让你重做一次会改什么？**

> - 复杂题拆解 prompt 改一下，现在 2/4 失败都是拆解阶段没出子问题
> - 加查询缓存（重复问题直接返回，省 LLM 调用）
> - 多模型路由（简单题用小模型省 token）
> - LangSmith / LangFuse 接入做商业级可观测

---

## 📊 项目总览卡片

```
┌─────────────────────────────────────────────┐
│        Enterprise Text2SQL Agent             │
│  "自然语言问数据库，AI 自动写 SQL 查数据"       │
├─────────────────────────────────────────────┤
│ 核心能力: 17 节点 LangGraph Agent             │
│  • Tool Use  • Planning  • Reflection        │
│  • ReAct  • Observability  • Evaluation      │
├─────────────────────────────────────────────┤
│ 技术栈:                                       │
│  • LangGraph + FastAPI + 原生前端             │
│  • DeepSeek (chat) + SiliconFlow (RAG)        │
│  • ChromaDB + BM25 + bge-m3 + bge-reranker   │
│  • SQLite + sqlglot + jieba                   │
├─────────────────────────────────────────────┤
│ 成绩: 60 题评测 91.7% 加权准确率               │
│  (85.7% → 91.7% 三轮迭代)                    │
├─────────────────────────────────────────────┤
│ 工程化:                                       │
│  • Docker 一键部署（已发布 Docker Hub）         │
│  • 9 类失败归因自动报告                        │
│  • 每节点 trace + token 采集 + SVG 可视化     │
│  • 完整 README + LICENSE + CONTRIBUTING       │
└─────────────────────────────────────────────┘
```

---

## 🎬 面试 3 分钟讲稿

> "我做的是一个 Text-to-SQL Agent 系统。核心场景是让非技术人员用自然语言问业务数据库。
>
> 架构上用 LangGraph 编排了 17 个节点的 Agent pipeline——从意图识别，到 SQL 生成，到执行，到自然语言回答，每个节点都是独立的纯函数，状态用 TypedDict 显式流转。
>
> 最关键的设计有 5 个：
>
> 1. **多阶段 RAG**：向量召回 + BM25 关键词召回 + RRF 融合 + bge-reranker 重排，4 阶段组合提升 schema 检索召回率
>
> 2. **Self-Reflection 节点**：在 SQL 审查和执行之间加了自评节点，LLM 对自己生成的 SQL 做风险分级（low/medium/high），作为 Agent 反思能力的工程化体现
>
> 3. **ReAct 自修复**：SQL 执行失败时进入修复循环，Agent 调工具自主诊断、最多重试 3 次，体现工具调用 + 错误恢复能力
>
> 4. **可观测性**：自己写了 trace_wrapper 装饰器，自动采集每节点耗时 + token 消耗 + 工具调用，前端用 SVG 流程图实时渲染
>
> 5. **评测闭环**：建了 60 题黄金评测集，自研 9 类失败归因工具，能定位每一道错题属于哪个阶段
>
> **效果**：通过两轮迭代，加权准确率从 85.7% 提升到 91.7%，中等题从 74% 涨到 96%。这个数据我是从跑评测、归因错题、定向改 prompt 拿到的。
>
> **工程化**：Docker 一键部署，镜像已发布到 Docker Hub，GitHub 开源。
>
> 这个项目展示了我对 Agent 工程 5 大核心能力的理解：Tool Use、Planning、Reflection、Memory、Observability。"

---

## 📋 速查表

| 类别 | 技术 | 作用 |
|---|---|---|
| Agent 框架 | LangGraph 1.0+ | 17 节点状态机编排 |
| 后端 | FastAPI | 异步 API + SSE 流式 |
| LLM | DeepSeek / Qwen / Gemini / Kimi / MiMo（12 选 1） | 推理 |
| Embedding | SiliconFlow BAAI/bge-m3 | 文本向量化 |
| Rerank | SiliconFlow BAAI/bge-reranker-v2-m3 | 检索精排 |
| 关键词检索 | rank_bm25 + jieba | 中文 BM25 |
| 融合算法 | RRF (Reciprocal Rank Fusion) | 混合检索排序 |
| 向量库 | ChromaDB | 持久化向量存储 |
| 数据库 | SQLite | 演示用关系数据库 |
| SQL 工具 | sqlglot | 解析 / 校验 / 注入 LIMIT |
| 前端 | 原生 HTML/CSS/JS + ECharts | 聊天界面 + 流程图 |
| 容器化 | Docker + Docker Compose | 一键部署 |
| 评测 | 自研 60 题黄金集 + 9 类归因 | 离线评估 |
| Tracing | 自研 trace_wrapper 装饰器 | 每节点耗时 + token |
