# Enterprise Text2SQL 面试讲解稿

## 30 秒介绍

这是一个企业级 Text2SQL Agent 系统。用户用自然语言提问后，系统不会直接让大模型生成 SQL，而是通过 LangGraph 拆成多个可观测节点：意图识别、复杂度分类、Schema RAG、SQL 生成、Review Agent 审查、AST 安全校验、只读执行、Repair Agent 修复和最终回答。

我重点解决的是三个问题：

1. 大模型不知道企业数据库的真实 schema。
2. 生成 SQL 可能语义不对或执行失败。
3. Text2SQL 需要可观测、可评测、可迭代，而不是一次性 prompt demo。

## 为什么不是直接 Prompt

直接 prompt 的问题：

- 全量 schema 太大，token 成本高，模型注意力分散。
- 模型容易用错列名、状态字段、JOIN 路径和日期函数。
- 生成 SQL 之后缺少执行前审查和执行后修复。
- 错了以后不知道错在哪里，不能系统性迭代。

本项目的解法：

- 用 Schema RAG 缩小上下文。
- 用 Review Agent 在执行前做语义审查。
- 用 sqlglot AST 做确定性安全校验。
- 用 Repair Agent 根据真实执行错误修复。
- 用评测集记录 bad case，推动下一轮优化。

## 一次请求链路

1. `detect_intent`
   判断是不是数据问题。非数据问题直接走 `answer_non_data`。

2. `classify`
   判断问题复杂度。简单/中等问题走主链路；复杂问题先拆子问题。

3. `semantic_parse`
   抽取指标、维度、过滤条件、时间范围、排序和 limit。

4. `schema_retrieval`
   根据语义结果和原问题召回候选表、候选字段和表关系。

5. `sql_generation`
   把问题、语义结构、候选 schema、few-shot 示例拼成 prompt 生成 SQL。

6. `sql_review`
   Review Agent 用 Function Calling 审查 SQL。必要时查完整表结构并修正 SQL。

7. `sql_validation`
   使用 `sqlglot` AST 做只读校验、多语句校验、危险操作拦截和候选表校验。

8. `sql_execution`
   只读执行 SQL，执行层自动补 LIMIT。

9. `sql_repair`
   执行失败时进入 Repair Agent，最多重试 3 次。

10. `answer`
   根据 SQL、执行结果和用户问题生成自然语言回答。

## 复杂问题怎么处理

复杂问题不是直接生成一条 SQL。系统会先调用 `decompose`，得到多个子问题和依赖关系，然后进入 `orchestrator`。

`orchestrator` 会：

- 对每个子问题单独做 schema retrieval。
- 单独做 semantic parse、SQL generation、review、validation、execution。
- 如果某一步失败，记录失败原因。
- 把前序成功结果作为后续子问题上下文。
- 最后用 merge prompt 汇总所有子结果。

这个设计适合“先找 top 商品，再分析这些商品的用户分布”这类依赖型问题。

## Review Agent 和 Repair Agent 的区别

Review Agent 是执行前主动防错：

- 关注 SQL 是否真正回答用户问题。
- 检查列名语义、JOIN 路径、时间函数、聚合粒度。
- 使用工具：`check_schema`、`fix_sql`、`approve_sql`。

Repair Agent 是执行后被动兜底：

- 关注真实数据库报错。
- 根据错误信息查询 schema、重写 SQL、试执行。
- 达到重试上限后放弃并返回原因。

边界清楚后，排查问题会更容易：Review 没拦住是语义审查不足，Repair 修不好是执行错误处理不足。

## 为什么 SQL 校验用 AST

正则或关键字包含判断有两个问题：

- 容易误杀，例如字段名 `delete_count`。
- 容易漏掉复杂嵌套或变体 SQL。

所以项目用 `sqlglot` 解析 AST：

- 多语句会被拦截。
- 非 `SELECT` 根节点会被拦截。
- `Insert`、`Update`、`Delete`、`Drop`、`Create`、`Alter` 等节点会被拦截。
- CTE 和只读子查询可以通过。

面试追问时可以强调：LLM 输出不可信，必须经过确定性校验。

## Schema RAG 为什么分两级

全量 schema 有两个问题：

- 表多字段多时 token 成本高。
- 模型容易在大量无关字段里选错。

两级召回：

1. 表级召回找候选表。
2. 字段级召回找候选字段。

同时保留降级策略：

- 小库直接全量返回，优先保证召回。
- Chroma 或 embedding 不可用时也全量返回，保证系统可运行。

## 评测怎么讲

不要只说“能跑”。要说“怎么证明变好了”。

当前评测集：

- 60 道题。
- 简单题、中等题、复杂题分层。
- 指标是 Execution Accuracy：执行结果和 gold SQL 结果是否一致。

迭代例子：

- v1 准确率 80.0%。
- bad case 归因到 4 类：列名语义错误、状态字段误用、JOIN 链路缺失、日期函数参数缺失。
- 加入 Review Agent 候选 schema 逐列核对后，中等题从 74% 到 78%。

## 最可能被追问的问题

### 1. 为什么不用全量 schema？

小库可以全量，大库不行。全量 schema 会增加 token、降低注意力，还会让模型更容易混淆字段。RAG 的目标不是炫技，而是控制上下文规模和候选范围。

### 2. Review Agent 是否一定比普通 prompt 好？

不一定。它的价值在于把审查动作工具化、可追踪、可迭代。普通 prompt 错了只能改提示词；Review Agent 可以明确看到是否查了 schema、是否 fix_sql、修正理由是什么。

### 3. 怎么保证 SQL 安全？

三层：

- LLM prompt 层要求只读。
- `sqlglot` AST 层强制只允许 SELECT 并拦截危险节点。
- DB 执行层只配置只读权限，并自动追加 LIMIT。

生产环境必须依赖后两层，不能相信 prompt。

### 4. 复杂问题为什么不直接让模型生成？

复杂问题通常有依赖关系和多个中间结果。拆成子问题后，每一步都能执行、验证、失败定位，也能把前序结果作为后续上下文。

### 5. 这个项目还能怎么优化？

优先级：

1. 复杂问题的子步骤 SSE 可视化。
2. 更多核心链路集成测试。
3. 更完整的 datasource 接入抽象。
4. 基于历史 query 的 few-shot 自动检索。
5. 执行计划 explain 和成本估计。

## 面试收尾

可以这样总结：

> 这个项目的重点是把 Text2SQL 从 prompt demo 变成工程系统。RAG 解决 schema 上下文，Review/Repair 解决 LLM 不可靠，AST 校验解决安全边界，SSE 和评测集解决可观测和可迭代。
