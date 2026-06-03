# 05 — 企业中 Agent 怎么用的

基于 2026 年字节/阿里/腾讯等大厂真实 JD 和面经整理。

---

## 三大场景

### 1. 代码助手 Agent（Copilot 类）

**代表**：GitHub Copilot、Cursor、通义灵码

**Agent 做什么**：
- 读代码库 → 理解上下文 → 生成代码
- 读 PR → Review → 给建议
- 读报错 → 修改代码 → 测试 → 提交

**用到什么**：ReAct + Function Calling（读文件、写文件、跑命令）

---

### 2. 业务运营 Agent（Tool 类）

**代表**：电商客服、金融风控、数据查询

**Agent 做什么**：
- 用户问"这个订单为什么延迟"→ 查订单系统 → 查物流系统 → 汇总回答
- 用户说"帮我做周报"→ 查销售数据 → 生成图表 → 写报告 → 发邮件

**用到什么**：Plan-and-Execute（先规划查哪些系统，再逐步执行）+ MCP（每个系统一个 MCP Server）

---

### 3. 数据处理 Agent（你的方向）

**代表**：Text2SQL、自动 BI、数据治理

**Agent 做什么**：
- 自然语言 → SQL → 执行 → 数据 → 回答
- 自动发现数据质量问题
- 多表自动关联分析

**用到什么**：Plan-and-Execute + ReAct + Reflection（就是你的架构）

---

## 企业技术选型

| 公司 | Agent 框架 | Tool 方式 |
|------|-----------|----------|
| 字节 | 自研 + LangGraph | Function Calling |
| 阿里 | 百炼平台 + 自研 | 阿里云 MCP |
| 腾讯 | LangChain/LangGraph | MCP + Function Calling |
| 百度 | 文心 SDK + 自研 | 百度 Tool 规范 |

**趋势**：
- 2024 → 大家都在用 LangChain
- 2025 → 开始迁到 LangGraph（更好的状态管理）
- 2026 → MCP 成为工具共享标准，Function Calling 做内部工具

---

## 企业 Agent 和你的项目的对应关系

| 企业做法 | 你的项目 |
|---------|---------|
| LangGraph StateGraph | ✓ 9 节点状态图 |
| Plan-Execute 编排 | ✓ decompose + orchestrator |
| ReAct 修复 | ✓ Function Calling 4 工具 |
| Reflection 检查 | ✓ 依赖断裂检测 |
| 安全校验 | ✓ 9 道 SQL 防线 |
| 评测体系 | ✓ 30 题评测集 |

**你的架构和企业级的差距就只有规模**——企业是 100+ 数据源、1000+ 并发、7×24 运营，你是单机 demo。但架构思路完全一样。

---

## 面试怎么说

> "我的架构参考了企业 text2sql 系统的三层设计：规划层、执行层、修复层。
> 虽然 demo 规模小，但 LangGraph StateGraph + Function Calling + 
> Plan-Execute-Reflect + ReAct 的技术栈选择和企业标准一致。
> 如果接入生产环境，扩展点是数据源路由和并发执行，架构不需要重构。"