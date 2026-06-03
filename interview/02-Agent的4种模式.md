# 02 — Agent 的 4 种模式

## 模式 1：ReAct（Reasoning + Acting）

**一句话**：走一步看一步。每步都思考→行动→观察。

```
你的 ReAct Repair Agent:

  观察: SQL 报错 "no such column: customer_name"
    ↓
  思考: 字段名可能写错了，先看看表结构
    ↓
  行动: 调用 schema_lookup("customers")
    ↓
  观察: 字段列表里有 "name"，没有 "customer_name"
    ↓
  思考: 把 customer_name 改成 name
    ↓
  行动: 调用 rewrite_sql("SELECT name FROM ...")
    ↓
  观察: SQL 已改写
    ↓
  思考: 执行试试
    ↓
  行动: 调用 execute_sql()
    ↓
  观察: 返回 500 行，成功 → 结束
```

**关键**：思考和行动是交错的，不是提前计划好的。

---

## 模式 2：Plan-and-Execute

**一句话**：先一口气想清楚怎么做，再逐步执行。

```
你的 decompose + orchestrator:

  规划(LLM一次调用):
    "这个问题需要两步：
     步骤1: 查消费最高10个客户
     步骤2: 用步骤1的名单查他们的品类"

  执行(代码for循环):
    步骤1 → sql_gen → validate → execute → 拿到10个人
    步骤2 → sql_gen(注入步骤1的名单) → validate → execute → 拿到品类

  汇总: LLM 把所有结果拼成最终回答
```

**关键**：规划在前面，执行在后面，执行过程中 LLM 不参与决策。

---

## 模式 3：Reflection

**一句话**：执行完后回头检查自己的答案，发现问题就改。

```
你的 orchestrator 里的 Reflection 步骤:

  所有子问题执行完:
    检查: 步骤1失败了吗？
      → 是 → 步骤2依赖步骤1 → 标记"跳过(前置失败)"
    检查: 步骤2失败了吗？
      → 是 → 步骤2无后置依赖 → 在回答中如实说明

  汇总时 LLM 看到完整状态 → 给出诚实的回答
```

**关键**：不是在执行过程中改，是在执行完后检查。

---

## 模式 4：Function Calling / Tool Use

**一句话**：LLM 自己决定调哪个工具、传什么参数。

```
你的 ReAct Repair 用 Function Calling:

  LLM 输出不是一个字符串，而是一个 tool_call:
    {
      "name": "schema_lookup",
      "arguments": {"table_name": "customers"}
    }

  代码执行这个工具，把结果返回给 LLM，LLM 再决定下一步。
```

**关键**：工具名和参数 schema 由 API 层校验，LLM 不会拼错工具名。

---

## 你的项目里：三种模式组合

```
Plan-and-Execute (decompose + orchestrator)
    │
    ├── 规划: LLM 一次性拆解复杂问题
    │
    ├── 执行: 逐个运行子问题
    │
    ├── Reflection: 检查执行结果，标记依赖断裂
    │
    └── 失败时 → ReAct Repair Agent 接管
            │
            ├── Function Calling 选工具
            ├── Think → Act → Observe 循环修复
            └── 修复成功 → 继续 / 放弃 → 标记失败
```

**面试时说**：

> "复杂问题用 Plan-and-Execute：LLM 先规划，系统按序执行，Reflection 检查结果。
> 子问题 SQL 失败时 ReAct Agent 接管，用 Function Calling 自主选择工具修复。
> 三种 Agent 范式组合解决 text2sql 场景下规划-执行-修复的完整闭环。"