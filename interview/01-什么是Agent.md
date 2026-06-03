# 01 — 什么是 Agent

## 一句话

**Agent = LLM + 工具 + 循环决策**

不是"调一次 LLM 拿结果"，而是"LLM 在循环里，每一步自己决定干什么"。

---

## 对比：Node vs Agent

### Node（你项目里大部分节点）

```
输入 → 调一次 LLM → 输出 JSON → 代码往下走
```

比如你的 `intent_node`：

```python
def intent_node(state):
    result = llm.generate_json("用户的问题是数据查询吗？", question)
    state["is_data_question"] = result["is_data_question"]  # 写回 state
    return state  # 结束，不循环
```

**LLM 只说了一句话，代码就继续了。LLM 没有选择权。**

### Agent（你项目里的 ReAct Repair）

```python
while 还没修好:
    decision = llm.generate_with_tools("下一步做什么？观察、思考、选择工具", tools=[...])
    # LLM 可能选: schema_lookup / rewrite_sql / execute_sql / give_up
    执行选中的工具
    if 执行成功:
        return 结果
    # 否则继续循环
```

**LLM 在循环里，每轮都自己做决定。LLM 有选择权。**

---

## Agent 的四个必要条件

| 条件 | 含义 | 你的 ReAct Repair 有吗 |
|------|------|----------------------|
| 感知 | 能观察执行结果 | ✓ 每次执行后结果追加到 observations |
| 决策 | 在循环中自主选择下一步 | ✓ LLM 选择 schema_lookup / rewrite_sql / execute_sql / give_up |
| 执行 | 能调用工具 | ✓ 四个 Function Calling 工具 |
| 目标 | 有明确的终止条件 | ✓ execute_sql 成功或 give_up 或 3 次失败 |

---

## 你的系统里有哪些 Agent

| 组件 | 是 Agent 吗 | 原因 |
|------|-----------|------|
| intent_node | ✗ | 调一次 LLM，不循环 |
| classify_node | ✗ | 调一次 LLM，不循环 |
| sql_generation_node | ✗ | 调一次 LLM，不循环 |
| decompose_node | ✗ | 调一次 LLM，不循环 |
| orchestrator | ✗ | for 循环是代码写的，LLM 不在循环里做决策 |
| **ReAct Repair** | **✓** | LLM 在 while 循环里自己选工具 |
| answer_node | ✗ | 调一次 LLM，不循环 |

**13 个节点/组件，只有 1 个是真的 Agent。**

---

## 面试怎么说

❌ "我的系统用了 Agent 架构"（假，只有一个是 Agent）

✓ "我的系统有 8 个 LLM 节点和一个 ReAct Repair Agent。
   ReAct Repair 使用 OpenAI Function Calling 在循环中自主选择工具修复 SQL。
   上层编排（decompose + orchestrator）是 LLM 辅助规划，不是 Agent。"

**诚实比吹牛分高。**