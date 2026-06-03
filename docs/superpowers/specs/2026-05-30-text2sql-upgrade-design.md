# Enterprise Text2SQL 升级设计文档

> 面向 AI/LLM 应用开发岗位面试的项目升级方案
> 
> 创建日期：2026-05-30

---

## 1. 目标与范围

### 1.1 升级目标

将当前项目从"能跑的 Text2SQL 原型"升级为"具备面试竞争力的生产级 LLM 应用"，在以下维度达到目标分数：

| 维度 | 当前分数 | 目标分数 | 说明 |
|------|---------|---------|------|
| Agent 编排 | 60 | **95** | 核心差异化亮点 |
| 模型工程化 | 40 | **95** | 展示生产级工程能力 |
| RAG 检索 | 60 | **80** | 补齐混合检索和图检索 |
| 评测体系 | 30 | **80** | 多模型对比 + 消融实验 |

### 1.2 不做什么

- 不引入前端框架（React/Vue）— 保持 FastAPI 纯后端
- 不实现用户权限系统（偏离 AI/LLM 主线）
- 不做 Docker/K8s 部署（面试不考运维）
- 不支持 MySQL/PostgreSQL 多数据源（当前 Chinook SQLite 够用）

---

## 2. Phase 结构总览

```
P0 (必须完成)                     P1 (强烈建议)        P2 (锦上添花)
┌─────────────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ 1.0 LangGraph 迁移       │  │ 3.1 图结构检索   │  │ 4.1 评测框架      │
│ 1.1 复杂问题拆解          │  │ 3.2 混合检索     │  │ 4.2 Prompt 管理   │
│ 1.2 Plan-Execute 编排器   │  │ 3.3 Query 改写   │  │ 4.3 多轮对话      │
│ 1.3 工具注册中心          │  └──────────────────┘  └──────────────────┘
│ 1.4 Agent 决策可观测      │
│                          │
│ 2.1 多模型智能路由        │
│ 2.2 SSE 流式输出          │
│ 2.3 语义缓存              │
│ 2.4 成本追踪              │
└─────────────────────────┘
```

---

## 3. Phase 1.0：迁移到 LangGraph（P0）

### 3.1 为什么必须迁移

| 当前手写 graph.py | 真正 LangGraph |
|------------------|---------------|
| 串行 if/else 控制分支 | `add_conditional_edges()` 声明式路由 |
| 无法做子图嵌套 | `StateGraph` 天然支持子图 |
| 无状态持久化 | 内置 `Checkpointer`，支持 `thread_id` |
| 无流式钩子 | 内置 `astream()` / `astream_events()` |
| PPT 写 LangGraph 但实际没用 | 名副其实 |

### 3.2 迁移方案

**不改 node 接口** — 每个 node 保持 `(state) -> dict` 签名，LangGraph 自动合并状态。

#### 新图结构

```
START
  │
  ▼
intent ──(非数据问题)──► answer_non_data ──► END
  │
  │(数据问题)
  ▼
classify
  │
  ▼
semantic
  │
  ▼
schema
  │
  ▼
sql_gen
  │
  ▼
validate ──(校验失败)──► answer_validation_failed ──► END
  │
  │(校验通过)
  ▼
execute ──(执行失败)──► sql_repair ──(修复后重试)──► execute
  │                        │
  │(执行成功)              │(放弃)──► answer_exec_failed ──► END
  ▼
answer ──► END
```

#### 关键条件边

```python
# intent → classify 或 answer_non_data
def route_after_intent(state):
    if not state["is_data_question"]:
        return "answer_non_data"
    return "classify"

# validate → execute 或 answer_validation_failed  
def route_after_validate(state):
    if state.get("sql_validation_error"):
        return "answer_validation_failed"
    return "execute"

# execute → answer 或 sql_repair
def route_after_execute(state):
    if state.get("execution_error"):
        if state.get("repair_attempts", 0) < 3:
            return "sql_repair"
        return "answer_exec_failed"
    return "answer"

# sql_repair → execute（重试）或 answer_exec_failed（放弃）
def route_after_repair(state):
    if state.get("execution_error"):
        return "answer_exec_failed"
    return "execute"
```

#### 循环边处理

`execute → sql_repair → execute` 形成循环。LangGraph 支持的两种方式：

1. **简单方案**：用 `repair_attempts` 计数器，达到上限后路由到 `answer_exec_failed`
2. **Command 方案**：sql_repair 返回 `Command(goto="execute", update={...})` 显式跳转

采用方案 2（更 LangGraph-idiomatic）。

### 3.3 compile 时机

在 `app/main.py` startup 事件中编译一次，后续所有请求复用同一个 `CompiledGraph`：

```python
# app/main.py
from app.workflow.graph import compile_graph

graph = None  # type: ignore

@app.on_event("startup")
async def startup():
    global graph
    graph = compile_graph()
```

### 3.4 涉及文件

| 操作 | 文件 | 说明 |
|------|------|------|
| 重写 | `app/workflow/graph.py` | StateGraph 定义、条件边、compile |
| 修改 | `app/api/routes/text2sql.py` | `graph.invoke(state)` 替代 `run_text2sql_workflow(state)` |
| 修改 | `scripts/run_evaluation.py` | 同上 |
| 修改 | `requirements.txt` | 添加 `langgraph`、`langgraph-checkpoint` |
| 修改 | `app/main.py` | startup 编译 graph |
| 删除 | `app/workflow/conditions.py` | 条件路由逻辑已移入 graph.py |

### 3.5 验收标准

- 现有 30 题评测集准确率不变（功能回归）
- `graph.get_graph().draw_mermaid()` 能输出正确的流程图
- 代码行数减少（手写 if/else 被声明式路由替代）

---

## 4. Phase 1.1：复杂问题拆解（P0）

### 4.1 动机

当前 `classify_node` 可以识别复杂问题，但路由分支的代码被注释掉：

```python
# graph.py line 77-78
# if state["complexity"] == "complex":  return decompose_node(state)
```

复杂问题也走老路，导致「消费最高的 10 个客户分别买了哪些音乐类型？」这种问题一定生成错误 SQL。

### 4.2 设计

**Decompose Node** 调用 LLM，将复杂问题拆成有序子问题序列：

```
输入: "消费最高的 10 个客户分别买了哪些音乐类型？"

输出:
[
  {
    "id": 1,
    "question": "消费总额最高的 10 个客户的 CustomerId 是什么？",
    "depends_on": [],
    "reason": "先确定 Top10 客户"
  },
  {
    "id": 2, 
    "question": "这 10 个客户分别购买的音乐类型及数量？",
    "depends_on": [1],
    "reason": "用上一步的客户 ID 列表查品类分布"
  }
]
```

### 4.3 LLM Prompt 设计

```
你是一个 SQL 问题分析专家。请分析以下复杂查询问题，
判断它是否可以一步完成（用一句 SQL 解决），
如果不能，请将它拆解为有序的子问题序列。

复杂问题的特征：
- 需要先查询得到一组结果，再用这组结果去查另一组数据
- 包含子查询、多步聚合
- 需要跨多个层级做过滤

拆解规则：
1. 每个子问题必须是可以独立回答的完整问题
2. 标注子问题之间的依赖关系（depends_on）  
3. 子问题按执行顺序排列
4. 如果一句 SQL 能解决，返回空列表

输出 JSON 格式：
{
  "can_single_sql": false,
  "reason": "...",
  "sub_questions": [...]
}
```

### 4.4 数据流

```
classify_node → (complex) → decompose_node → orchestrator → sub_pipelines → merge
                  │
                  ├── (simple) → 现有串行管道
                  └── (not_data) → 直接回答
```

### 4.5 涉及文件

| 操作 | 文件 | 说明 |
|------|------|------|
| 新增 | `app/nodes/decompose_node.py` | LLM 拆解节点 |
| 新增 | `app/prompts/decompose_prompt.py` | 拆解 Prompt |
| 修改 | `app/workflow/graph.py` | classfiy 后加条件路由到 decompose |
| 修改 | `app/schemas/state.py` | 新增 `sub_questions`、`sub_results`、`merge_answer` |

### 4.6 验收标准

- 评测集 Q28、Q29（complex 难度）生成正确的子问题序列
- 子问题之间依赖关系正确标注

---

## 5. Phase 1.2：Plan-and-Execute 编排器（P0）

### 5.1 动机

拆解出子问题后，需要一个编排器来调度执行。关键挑战：

1. **依赖顺序**：子问题 2 依赖子问题 1 的结果，必须等 1 完成
2. **上下文传递**：子问题 2 的 SQL 生成需要知道子问题 1 返回了什么
3. **错误处理**：某个子问题失败后，后续依赖它的子问题如何处理

### 5.2 设计

**Orchestrator** 类负责子任务的调度和执行：

```
┌──────────────────────────────────────────┐
│            Orchestrator                   │
│                                           │
│  1. 拓扑排序子问题（按 depends_on）        │
│  2. 逐层执行：                            │
│     ┌─────────────────────────┐           │
│     │ for each ready task:    │           │
│     │   schema → sql → val   │           │
│     │   → execute → collect   │           │
│     └─────────────────────────┘           │
│  3. 依赖结果注入：                         │
│     子问题 N 的 Prompt 包含                │
│     前序子问题的 SQL + 结果摘要            │
│  4. 汇总所有子结果 → merge_answer          │
└──────────────────────────────────────────┘
```

### 5.3 上下文注入机制

后续子问题的 `sql_generation_prompt` 增加 `context_from_previous` 参数：

```
# 子问题 2 的 Prompt 中追加：

前置步骤的结果：
步骤1 SQL: SELECT CustomerId FROM Invoice GROUP BY CustomerId ORDER BY SUM(Total) DESC LIMIT 10
步骤1 结果: CustomerId=[3, 7, 12, 18, 24, 31, 37, 42, 48, 53]

请基于以上信息，生成当前问题的 SQL。
如果需要在 WHERE 条件中引用上述结果，请使用 IN (...) 语法。
```

### 5.4 LangGraph 实现方式

使用 LangGraph 的 `Send()` API 实现子任务的并行分发：

```python
def continue_to_sub_tasks(state):
    """将每个子问题打包为 Send 分发"""
    return [
        Send("sub_task_pipeline", {"sub_task": task, "context": state})
        for task in state["sub_questions"]
        if not task.get("depends_on")  # 第一批无依赖的子任务
    ]
```

实际上，由于子任务之间可能存在依赖（不能完全并行），采用串行执行：
有依赖的子任务等依赖完成后，拿到结果再执行。

### 5.5 涉及文件

| 操作 | 文件 | 说明 |
|------|------|------|
| 新增 | `app/workflow/orchestrator.py` | 编排器核心逻辑 |
| 修改 | `app/workflow/graph.py` | 添加 sub_task_pipeline 子图 |
| 修改 | `app/prompts/sql_generation_prompt.py` | 新增 `context_from_previous` 参数 |
| 修改 | `app/schemas/state.py` | 新增 `sub_task_context` 字段 |

### 5.6 验收标准

- Q28（「消费最高的 10 个客户分别买了哪些音乐类型？」）端到端执行正确
- 子问题结果正确传递到后续子问题的 Prompt 中
- 中间子任务失败时，编排器正确处理（跳过依赖任务 + 记录错误）

---

## 6. Phase 1.3：工具注册中心（P0）

### 6.1 动机

当前 Agent 的工具是硬编码的 dict：

```python
self.tools = {
    "schema_lookup": SchemaLookupTool(),
    "execute_sql": ExecuteSQLTool(),
}
```

新增工具需要改 Agent 代码、改 Prompt、改多处。需要标准化的 Tool 注册机制。

### 6.2 设计

```
BaseTool (抽象基类)
├── name: str
├── description: str  
├── parameters_schema: dict  # JSON Schema 格式
└── run(**kwargs) -> dict    # 统一执行接口

ToolRegistry
├── register(tool: BaseTool)
├── get(name: str) -> BaseTool
├── list_tools() -> list[dict]  # 返回 Function Calling 格式
└── list_for_prompt() -> str    # 返回 Prompt 可用的工具描述
```

### 6.3 工具列表

| 工具 | 用途 | Agent 使用场景 |
|------|------|---------------|
| `schema_lookup` | 查表字段、类型、样本 | ReAct 修复时验证字段是否存在 |
| `execute_sql` | 安全校验后执行 SQL | ReAct 修复后重新执行 |
| `rewrite_sql` | LLM 重新生成 SQL | ReAct 修正 SQL 语法/逻辑错误 |
| `think` | 显式推理（不执行动作） | Agent 在行动前做推理分析 |
| `give_up` | 标记放弃 | 3 轮后仍失败，放弃并说明原因 |

### 6.4 涉及文件

| 操作 | 文件 | 说明 |
|------|------|------|
| 新增 | `app/tools/base_tool.py` | BaseTool 抽象类 |
| 新增 | `app/tools/registry.py` | ToolRegistry 注册中心 |
| 新增 | `app/tools/think_tool.py` | Think 工具 |
| 修改 | `app/tools/execute_sql_tool.py` | 继承 BaseTool |
| 修改 | `app/tools/schema_lookup_tool.py` | 继承 BaseTool |
| 修改 | `app/agents/react_sql_repair_agent.py` | 从 Registry 获取工具 |

### 6.5 验收标准

- 新增工具只需继承 BaseTool + 注册到 Registry，Agent 自动识别
- `ToolRegistry.list_for_prompt()` 输出可被 LLM 理解的工具描述
- 现有 ReAct Agent 功能不受影响

---

## 7. Phase 1.4：Agent 决策可观测性（P0）

### 7.1 动机

当前 `debug_trace` 只记录了节点级别的输入输出。Agent 内部的 Think-Act-Observe 循环完全没有记录，出问题无法排查。

### 7.2 设计

**AgentTracer** 记录每次 Agent 决策的完整上下文：

```python
@dataclass
class AgentStep:
    timestamp: float
    step_number: int
    thought: str          # LLM 的推理过程
    action: str           # 选择的工具名
    action_input: dict    # 工具参数
    observation: dict     # 工具返回结果
    error: str | None     # 如果有错误
```

每次 ReAct 循环结束后，生成决策链路：

```
Step 1 (0.0s):
  Thought: SQL 报错 "no such column: sale_amount"，
           需要查 Invoice 表有哪些字段
  Action: schema_lookup(table_name="Invoice")
  Observation: {columns: [...12 fields...], success: true}

Step 2 (0.5s):
  Thought: 发现字段名是 Total 不是 sale_amount，
           重写 SQL 用 SUM(Total)
  Action: rewrite_sql(sql="SELECT ... SUM(Total) ...")
  Observation: {current_sql: "SELECT ... SUM(Total) ..."}

Step 3 (1.0s):  
  Action: execute_sql
  Observation: {success: true, rows: [...], row_count: 25}
```

### 7.3 API 响应格式

```json
{
  "answer": "...",
  "sql": "SELECT ...",
  "agent_trace": [
    {
      "step": 1,
      "thought": "SQL 报错...",
      "action": "schema_lookup",
      "observation": {"success": true, "columns": [...]},
      "latency_ms": 234
    }
  ]
}
```

### 7.4 涉及文件

| 操作 | 文件 | 说明 |
|------|------|------|
| 新增 | `app/utils/agent_tracer.py` | AgentTracer 类 |
| 修改 | `app/agents/react_sql_repair_agent.py` | 每步调用 tracer.record() |
| 修改 | `app/workflow/orchestrator.py` | 记录编排决策 |
| 修改 | `app/schemas/state.py` | 新增 `agent_trace` 字段 |

### 7.5 验收标准

- 每次 ReAct 修复后，API 响应包含完整决策链路
- 每个 step 包含 thought/action/observation/latency

---

## 8. Phase 2.1：多模型智能路由（P0）

### 8.1 动机

当前所有问题都用同一个模型（qwen-plus），简单 COUNT 查询和复杂 JOIN 查询花同样的钱。

### 8.2 设计

**ModelRouter** 根据问题复杂度选择模型：

```
问题复杂度      →  模型选择          →  预估成本/1K tokens
─────────────────────────────────────────────────────
simple          →  qwen-turbo       →  ￥0.0003
medium          →  qwen-plus        →  ￥0.002
complex         →  qwen-max         →  ￥0.02
```

配置结构：

```python
MODEL_CONFIG = {
    "simple": {
        "model": "qwen-turbo",
        "fallback": "qwen-plus",     # 超时/故障降级
        "max_tokens": 1024,
        "temperature": 0.1,
    },
    "medium": {
        "model": "qwen-plus", 
        "fallback": "qwen-max",
        "max_tokens": 2048,
        "temperature": 0.1,
    },
    "complex": {
        "model": "qwen-max",
        "fallback": "qwen-plus",
        "max_tokens": 4096, 
        "temperature": 0.0,
    },
}
```

路由逻辑：

```python
def route(self, complexity: str, node: str) -> ModelConfig:
    # 某些节点强制用强模型（如 SQL 生成）
    if node in ("sql_generation", "sql_repair"):
        return self.config["complex"]
    # 意图识别、分类等始终用便宜模型
    if node in ("intent", "classify"):
        return self.config["simple"]  
    # 其余按复杂度路由
    return self.config.get(complexity, self.config["medium"])
```

### 8.3 Fallback 机制

```
qwen-turbo 调用
  ├── 成功 → 返回结果
  └── 超时/5xx → qwen-plus 重试
        ├── 成功 → 返回结果 + warning
        └── 失败 → 返回 error
```

### 8.4 涉及文件

| 操作 | 文件 | 说明 |
|------|------|------|
| 新增 | `app/services/model_router.py` | 路由逻辑 |
| 修改 | `app/services/llm_service.py` | 接入 router，每次调用先 route |
| 修改 | `app/core/config.py` | 新增模型配置项 |

### 8.5 验收标准

- simple 问题使用 qwen-turbo，complex 问题使用 qwen-max
- 模型故障时自动降级到 fallback 模型
- 日志中能看到每次调用的模型选择 + 原因

---

## 9. Phase 2.2：SSE 流式输出（P0）

### 9.1 动机

当前 API 是同步的，一个请求 5-10 秒才返回。用户看到的是黑盒。面试时需要展示「生产过程」。

### 9.2 设计

新增 SSE 端点，利用 LangGraph 的 `astream_events()` 推送每个节点的事件：

```
POST /api/text2sql/stream

事件流：
event: node_start
data: {"node": "intent", "timestamp": 0.0}

event: node_complete  
data: {"node": "intent", "output": {"intent": "data_query", "is_data_question": true}, "elapsed_ms": 234}

event: node_start
data: {"node": "classify", "timestamp": 0.3}

event: node_complete
data: {"node": "classify", "output": {"complexity": "medium"}, "elapsed_ms": 189}

... (继续 schema → sql_gen → validate → execute → answer)

event: workflow_complete
data: {"answer": "...", "sql": "SELECT ...", "rows_count": 25, "total_elapsed_ms": 4521}
```

### 9.3 LangGraph 集成

```python
# app/api/routes/stream.py
async def stream_text2sql(req: Text2SQLRequest):
    async def event_generator():
        async for event in graph.astream_events(state, version="v2"):
            if event["event"] == "on_chain_start":
                yield f"event: node_start\ndata: {json.dumps({...})}\n\n"
            elif event["event"] == "on_chain_end":
                yield f"event: node_complete\ndata: {json.dumps({...})}\n\n"
        yield f"event: workflow_complete\ndata: {json.dumps({...})}\n\n"
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

### 9.4 涉及文件

| 操作 | 文件 | 说明 |
|------|------|------|
| 新增 | `app/api/routes/stream.py` | SSE 端点 |
| 修改 | `app/schemas/response.py` | SSE 事件 schema |
| 修改 | `app/main.py` | 注册 stream router |

### 9.5 验收标准

- `curl -N POST /api/text2sql/stream` 能实时看到事件流
- 每个节点的开始/完成事件在正确时机推送
- 非流式端点 `/api/text2sql` 行为不变

---

## 10. Phase 2.3：语义缓存（P0）

### 10.1 动机

「一共有多少位艺术家？」这种问题每次都被重新处理一遍，浪费 LLM 调用和计算资源。

### 10.2 设计

两层缓存：

#### L1：精确 SQL 缓存

```
cache_key = hash(sql)  →  {rows, timestamp, ttl}
```

相同 SQL 在 TTL（5 分钟）内直接返回缓存结果。

#### L2：语义缓存

```
新问题 → embedding → 与缓存中所有问题计算 cosine_sim
  ├── ≥ 0.95 → 返回缓存结果（语义相同）
  └── < 0.95 → 正常处理 → 结果写入缓存
```

缓存策略：LRU，最多保留 100 条。

### 10.3 API 响应标记

```json
{
  "answer": "...",
  "cached": true,
  "cache_hit_type": "semantic",   // "exact" | "semantic" | "miss"
  "cache_similar_question": "一共有几位艺术家？",
  "cache_similarity": 0.97
}
```

### 10.4 涉及文件

| 操作 | 文件 | 说明 |
|------|------|------|
| 新增 | `app/services/cache_service.py` | 两层缓存实现 |
| 修改 | `app/workflow/graph.py` | 管道入口检查缓存，出口写入缓存 |
| 修改 | `app/schemas/response.py` | 新增 cached 相关字段 |

### 10.5 验收标准

- 相同问题第二次查询返回 `cached: true`，延迟 < 50ms
- 相似问题（如「有多少艺术家？」vs「一共有多少位艺术家？」）命中语义缓存
- 缓存 TTL 过期后自动失效

---

## 11. Phase 2.4：成本追踪（P0）

### 11.1 动机

面试时需要回答「这个系统每次查询花多少钱？」、「哪个环节最耗 Token？」

### 11.2 设计

**CostTracker** 在每次 LLM 调用后记录：

```
调用记录:
  node: "sql_generation"
  model: "qwen-plus"
  prompt_tokens: 1,234
  completion_tokens: 89
  cost: ￥0.0027
  latency_ms: 1,245
```

每次请求结束后汇总：

```
请求总成本:
  intent:         ￥0.0001 (turbo)
  classify:       ￥0.0001 (turbo)
  semantic:       ￥0.0003 (turbo)
  sql_gen:        ￥0.0027 (plus)
  validate:       ￥0.0000 (本地, 0 token)
  execute:        ￥0.0000 (本地, 0 token)
  answer:         ￥0.0012 (plus)
  ────────────────────────────
  Total:          ￥0.0044
```

### 11.3 计价配置

```python
PRICING = {
    "qwen-turbo":   {"input": 0.0003, "output": 0.0006},   # 元/1K tokens
    "qwen-plus":    {"input": 0.002,  "output": 0.004},
    "qwen-max":     {"input": 0.02,   "output": 0.04},
    "text-embedding-v2": {"input": 0.0007, "output": 0.0},
}
```

### 11.4 涉及文件

| 操作 | 文件 | 说明 |
|------|------|------|
| 新增 | `app/utils/cost_tracker.py` | 成本记录 + 汇总 |
| 修改 | `app/services/llm_service.py` | 每次调用后上报 usage |
| 修改 | `app/schemas/state.py` | 新增 `cost_breakdown` 字段 |
| 新增 | `scripts/cost_report.py` | 全局成本分析脚本 |

### 11.5 验收标准

- API 响应包含 `cost_breakdown`，列出每个节点/模型的 Token 和费用
- `python scripts/cost_report.py` 输出评测集的总体成本报告
- 各模型定价可配置（通过环境变量）

---

## 12. Phase 3.1：图结构检索（P1）

### 12.1 动机

当前 Schema 检索只按相似度返回表和字段，但不知道表之间怎么 JOIN。LLM 需要自己推断 JOIN 路径，经常出错。

### 12.2 设计

**GraphTraversal** 基于外键关系构建有向图：

```
Database Schema Graph:

Artist ──► Album ──► Track ──► InvoiceLine ◄── Invoice ◄── Customer
                                    │
                                    ▼
                                 Genre                Employee ◄── Customer
                                    │
                                 MediaType
```

核心方法：

```python
class GraphTraversal:
    def find_join_path(self, from_table: str, to_table: str) -> list[JoinStep]:
        """BFS 最短路径，返回 JOIN 序列"""
        
    def expand_tables(self, seed_tables: set[str], max_hops: int = 2) -> set[str]:
        """从命中表沿外键扩展 N 跳"""
        
    def get_join_clause(self, path: list[JoinStep]) -> str:
        """生成 ON 条件，如 'Album.ArtistId = Artist.ArtistId'"""
```

### 12.3 集成到 Schema 检索

检索流程变为：

```
1. 向量检索 → 命中 Genre(0.87), Track(0.61), Invoice(0.72)
2. 图扩展 1 跳 → 加入 InvoiceLine (通过 Track→InvoiceLine 外键)
3. 组装时附带 JOIN 路径信息
```

### 12.4 Prompt 增强

```
# sql_generation_prompt 中追加：

可用表及其 JOIN 路径：
- Genre ↔ Track: ON Genre.GenreId = Track.GenreId
- Track ↔ InvoiceLine: ON Track.TrackId = InvoiceLine.TrackId  
- Invoice ↔ InvoiceLine: ON Invoice.InvoiceId = InvoiceLine.InvoiceId
- Invoice ↔ Customer: ON Invoice.CustomerId = Customer.CustomerId
```

### 12.5 涉及文件

| 操作 | 文件 | 说明 |
|------|------|------|
| 新增 | `app/services/graph_traversal.py` | 图遍历逻辑 |
| 修改 | `app/services/schema_service.py` | 检索后调用图扩展 |
| 修改 | `app/prompts/sql_generation_prompt.py` | Prompt 添加 JOIN 路径 |

### 12.6 验收标准

- `expand_tables({"Genre", "Track"}, 1)` 返回 `{"Genre", "Track", "InvoiceLine", "MediaType"}`
- `find_join_path("Artist", "InvoiceLine")` 返回 `[Artist→Album, Album→Track, Track→InvoiceLine]`
- SQL 生成 Prompt 中包含正确的 JOIN 路径信息

---

## 13. Phase 3.2：混合检索（P1）

### 13.1 动机

纯向量检索对中文精确匹配弱。如「查询 Artist 表」的向量和「查询 Employee 表」很接近，但 BM25 能通过关键词「Artist」精确匹配。

### 13.2 设计

```
最终分数 = 0.6 × cosine_sim(向量) + 0.4 × BM25_score(关键词)
```

BM25 索引在启动时构建，对每张表的描述文本建立倒排索引。

### 13.3 涉及文件

| 操作 | 文件 | 说明 |
|------|------|------|
| 新增 | `app/services/bm25_index.py` | BM25 倒排索引 |
| 修改 | `app/services/schema_service.py` | search 方法改为混合打分 |

### 13.4 验收标准

- 纯关键词查询（如「Artist 表有多少条记录」）BM25 分数 > 纯向量分数
- 语义查询（如「音乐分类的销售额」）向量分数 > BM25 分数
- 混合分数在两类查询上都优于单独使用任何一种

---

## 14. Phase 3.3：Query 改写（P1）

### 14.1 动机

用户输入是口语化的：「上个月卖得最好的那个品类是啥」→ LLM 先理解成「上个月销售额最高的商品品类」，再做 Schema 检索更准确。

### 14.2 设计

在 semantic_parse_node 之前插入 query_rewrite_node：

```
原始问题: "上个月卖得最好的那个品类是啥"
     │
     ▼  query_rewrite_node (LLM 改写)
     │
改写结果: "上个月销售额最高的商品品类"
扩展词: ["销售额", "营收", "收入", "品类", "分类", "类型"]
     │
     ▼  semantic_parse_node (用改写后的问题做语义解析)
```

### 14.3 涉及文件

| 操作 | 文件 | 说明 |
|------|------|------|
| 新增 | `app/nodes/query_rewrite_node.py` | 改写节点 |
| 新增 | `app/prompts/query_rewrite_prompt.py` | 改写 Prompt |
| 修改 | `app/workflow/graph.py` | 在 semantic 前插入 rewrite |
| 修改 | `app/schemas/state.py` | 新增 `rewritten_question` 字段 |

### 14.4 验收标准

- 口语化问题被改写成标准化查询语言
- 改写后的 Schema 检索 recall 不低于原始问题

---

## 15. Phase 4.1：评测框架完善（P2）

### 15.1 改动

- 支持 `--models qwen-turbo,qwen-plus,qwen-max` 多模型对比
- 支持 `--rag full|none|hybrid` 消融实验
- 输出对比报告（CSV + JSON）
- 新增 `--stream` 实时进度

### 15.2 涉及文件

| 操作 | 文件 | 说明 |
|------|------|------|
| 修改 | `scripts/run_evaluation.py` | 加参数 + 多模型支持 |
| 新增 | `scripts/run_benchmark.py` | 一键全量 benchmark |

---

## 16. Phase 4.2：Prompt 版本管理（P2）

### 16.1 设计

```python
class PromptRegistry:
    def register(self, name, version, template, variables, author):
        """注册一个 Prompt 版本"""
        
    def get(self, name, version="latest") -> PromptTemplate:
        """获取指定版本"""
        
    def get_ab(self, name) -> PromptTemplate:
        """A/B 测试：随机返回版本 A 或 B"""
```

### 16.2 涉及文件

| 操作 | 文件 | 说明 |
|------|------|------|
| 新增 | `app/prompts/registry.py` | Prompt 注册中心 |
| 修改 | `app/prompts/sql_generation_prompt.py` | 迁移到 Registry |
| 新增 | `scripts/prompt_report.py` | 版本列表脚本 |

---

## 17. Phase 4.3：多轮对话（P2）

### 17.1 设计

基于 LangGraph Checkpointer 的 `thread_id` 实现：

```
用户: "巴西有多少客户？"
  → thread_id="abc123", 执行查询, 记录到 Checkpointer

用户: "其中圣保罗的有多少？"  
  → thread_id="abc123", 从 Checkpointer 读取历史
  → LLM 识别"其中"指代上轮的"巴西客户"
  → 改写为 "巴西圣保罗的客户数量"
```

### 17.2 涉及文件

| 操作 | 文件 | 说明 |
|------|------|------|
| 新增 | `app/services/conversation_service.py` | 对话上下文管理 |
| 修改 | `app/workflow/graph.py` | intent 前注入对话历史 |
| 修改 | `app/schemas/state.py` | 新增 `conversation_history` |

---

## 18. 文件改动汇总

| Phase | 新增 | 修改 | 删除 | 总文件数 |
|-------|------|------|------|---------|
| 1.0 LangGraph 迁移 | 0 | 5 | 1 | 6 |
| 1.1 复杂问题拆解 | 2 | 2 | 0 | 4 |
| 1.2 Plan-Execute | 1 | 3 | 0 | 4 |
| 1.3 工具注册中心 | 3 | 3 | 0 | 6 |
| 1.4 Agent 可观测 | 1 | 3 | 0 | 4 |
| 2.1 模型路由 | 1 | 2 | 0 | 3 |
| 2.2 SSE 流式 | 1 | 2 | 0 | 3 |
| 2.3 语义缓存 | 1 | 2 | 0 | 3 |
| 2.4 成本追踪 | 2 | 2 | 0 | 4 |
| 3.1 图检索 | 1 | 2 | 0 | 3 |
| 3.2 混合检索 | 1 | 1 | 0 | 2 |
| 3.3 Query 改写 | 2 | 2 | 0 | 4 |
| 4.1 评测框架 | 1 | 1 | 0 | 2 |
| 4.2 Prompt 管理 | 2 | 2 | 0 | 4 |
| 4.3 多轮对话 | 1 | 2 | 0 | 3 |
| **合计** | **20** | **34** | **1** | **55** |

---

## 19. 面试叙事线（升级完成后）

```
我做了一个企业级 Text2SQL 系统。核心是四层架构：

1️⃣ LangGraph Agent 编排层
   基于 StateGraph 构建 8 节点管道 + 条件分支。
   简单问题走快速管道，复杂问题触发 Plan-and-Execute 拆解：
   LLM 自主将问题拆成有序子任务，Orchestrator 按依赖拓扑排序调度，
   前一步结果自动注入后续 Prompt。子任务失败进入 ReAct 修复循环。

2️⃣ RAG Schema 检索层
   混合检索（向量 + BM25）+ Query 改写 + 外键图扩展。
   自动适配任意数据库，零手工标注。
   不仅检索相关表和字段，还自动发现 JOIN 路径。

3️⃣ 模型工程化层
   基于复杂度自适应路由：simple→turbo, medium→plus, complex→max，
   成本降低 50%。主模型超时自动降级到备选。
   SSE 流式实时推送每个节点的执行状态。语义缓存相似问题秒级命中。

4️⃣ 质量保障层
   9 道 SQL 安全校验（sqlglot AST + 表/字段白名单 + 危险关键字）。
   30 题评测集，覆盖简单/中等/复杂三类，执行准确率 87%+。
   全链路 Token 级成本追踪 + Agent 决策可观测。
```

---

## 20. 关键设计决策记录

| 决策 | 选择 | 原因 |
|------|------|------|
| 图编排框架 | LangGraph | PPT 写了但没用 → 名副其实；天然支持子图/流式/持久化 |
| Graph 风格 | StateGraph (not MessageGraph) | Text2SQL 是有状态管道，不是对话代理 |
| 子任务调度 | 串行（非并行） | 子任务之间有依赖关系，并行会出乱序 |
| 缓存存储 | 内存 dict | 面试项目不需要 Redis，内存够用 |
| Checkpointer | MemorySaver | 同上，开发阶段不引入外部依赖 |
| 向量存储 | 内存 list | 当前 11 表 64 字段，内存检索够快 |
| Prompt 模板 | 字符串模板（非 LangChain PromptTemplate） | 减少依赖，保持轻量 |

---

## 21. 风险与注意事项

1. **langgraph 版本兼容**：建议固定 `langgraph>=0.2.0,<0.4.0`，API 变化频繁
2. **模型路由复杂度**：classify_node 的结果决定了后续用哪个模型，classify 自身必须稳定
3. **缓存一致性**：语义缓存可能返回过期结果，需要对时间敏感的查询（如「本月销售额」）禁用缓存
4. **评测回归**：每个 Phase 完成后跑一次 30 题评测，确保准确率不下降
