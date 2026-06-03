# LangGraph 全节点流程图前端展示

**日期:** 2026-06-02
**状态:** 设计完成，待审查

---

## 1. 目标

将 LangGraph 完整工作流图（16 个节点 + 条件分支 + 循环回边）以卡片式 SVG 流程图的形式展示在前端。执行过程中节点逐一点亮，执行完毕后过渡切换为查询结果。

---

## 2. 现状

### 2.1 后端（已就绪，不改）

- `graph.py` 定义了完整的 16 节点 StateGraph
- `/text2sql/stream` SSE 端点每完成一个节点推送 `{"type":"node","node":"<name>","label":"<中文标签>"}`
- 开始推送 `{"type":"start"}`，完成推送 `{"type":"done"}`
- `NODE_LABELS` 已定义所有节点的中文 + emoji 标签

### 2.2 前端（需要改）

- `app.js` 硬编码了 8 个 SVG 节点，其中 4 个节点（validate, execute, sql_repair, answer）被合并映射到同一个 `review` 视觉节点
- 缺失 3 个终止节点（answer_non_data, answer_validation_failed, answer_exec_failed）
- 节点样式简陋：光秃秃的英文名 + 单色矩形框
- `lightNode()` 使用硬编码的线性序列 `['intent','classify','semantic','schema','sql_gen','review']`，无法处理分支
- 没有"完成→结果"的过渡动画

---

## 3. 设计

### 3.1 图配置（app.js）

用 JS 对象描述完整图结构：

```js
const GRAPH = {
  nodes: [
    { id: 'detect_intent',   label: '🔍 意图识别',     step: 1,  color: 'blue' },
    { id: 'classify',         label: '🏷️ 复杂度分类',   step: 2,  color: 'blue' },
    { id: 'decompose',        label: '🧩 拆解问题',     step: 3,  color: 'amber' },
    { id: 'orchestrator',     label: '🎯 编排执行',     step: 4,  color: 'amber' },
    { id: 'semantic',         label: '📝 语义解析',     step: 3,  color: 'blue' },
    { id: 'schema',           label: '🗄️ Schema 检索',  step: 4,  color: 'blue' },
    { id: 'sql_gen',          label: '⚡ 生成 SQL',     step: 5,  color: 'blue' },
    { id: 'sql_review',       label: '🔍 SQL 审查',     step: 6,  color: 'blue' },
    { id: 'validate',         label: '🛡️ SQL 校验',     step: 7,  color: 'blue' },
    { id: 'execute',          label: '▶️ 执行查询',     step: 8,  color: 'blue' },
    { id: 'sql_repair',       label: '🔧 ReAct 修复',   step: 9,  color: 'amber' },
    { id: 'answer',           label: '💬 汇总回答',     step: 10, color: 'green' },
    { id: 'answer_non_data',  label: '💬 非数据回答',   step: -1, color: 'red', terminal: true },
    { id: 'answer_valid_fail',label: '❌ 校验失败',     step: -1, color: 'red', terminal: true },
    { id: 'answer_exec_fail', label: '❌ 执行失败',     step: -1, color: 'red', terminal: true },
    { id: 'START',            label: 'START',           step: 0,  color: 'gray', isStart: true },
    { id: 'END',              label: 'END',             step: 99, color: 'gray', isEnd: true },
  ],
  edges: [
    { from: 'START', to: 'detect_intent' },
    { from: 'detect_intent', to: 'classify',         cond: '是数据问题' },
    { from: 'detect_intent', to: 'answer_non_data',  cond: '非数据问题' },
    { from: 'classify',      to: 'semantic',         cond: '简单' },
    { from: 'classify',      to: 'decompose',        cond: '复杂' },
    { from: 'decompose',     to: 'orchestrator' },
    { from: 'orchestrator',  to: 'END' },
    { from: 'semantic',      to: 'schema' },
    { from: 'schema',        to: 'sql_gen' },
    { from: 'sql_gen',       to: 'sql_review' },
    { from: 'sql_review',    to: 'validate' },
    { from: 'validate',      to: 'execute',              cond: '通过' },
    { from: 'validate',      to: 'answer_valid_fail',    cond: '失败' },
    { from: 'execute',       to: 'answer',               cond: '成功' },
    { from: 'execute',       to: 'sql_repair',           cond: '失败 <3次' },
    { from: 'execute',       to: 'answer_exec_fail',     cond: '失败 ≥3次' },
    { from: 'sql_repair',    to: 'execute',              cond: '重试' },
    { from: 'sql_repair',    to: 'answer_exec_fail',     cond: '放弃' },
    { from: 'answer',        to: 'END' },
    { from: 'answer_non_data', to: 'END' },
    { from: 'answer_valid_fail', to: 'END' },
    { from: 'answer_exec_fail', to: 'END' },
  ],
  positions: {
    // 手动布局，基于从上到下、分支左右分叉的原则
  }
}
```

### 3.2 节点卡片样式（style.css）

每个 SVG 节点渲染为卡片：

```
┌─────────────────┐
│      🔍         │  ← emoji 图标
│   意图识别       │  ← 中文名称（粗体）
│ detect_intent   │  ← 英文名（小字）
│ ████████░░░░░░  │  ← 进度条（仅执行中时显示）
└─────────────────┘
```

**四种状态：**

| 状态 | 背景 | 边框 | emoji | 文字色 |
|------|------|------|-------|--------|
| 等待 | `#121826` 暗灰 | `#1e293b` | 灰度 | `#475569` |
| 执行中 | `#1e3a5f → #0d1f3a` 深蓝渐变 | `2px #3b82f6` + 发光 | 彩色 | `#f3f4f6` |
| 已完成 | `#14532d → #0a1a0a` 深绿渐变 | `1.5px #22c55e` | ✅ | `#4ade80` |
| 分支未走 | 同等待 + 10% 透明度 | 同等待 | 灰度 | 同等待 |

### 3.3 点亮逻辑（app.js）

```
收到 SSE event { type: "node", node: "semantic" }
  ↓
setNodeState("semantic", "done")       ← 前一个节点变完成
setNodeState("semantic", "active")      ← 当前节点变执行中
highlightEdge(takenPath)                ← 走过的边高亮
dimUntakenBranches(unreachableNodes)    ← 不会走的分支变暗
  ↓
收到 SSE event { type: "done" }
  ↓
allNodesToState("done")                 ← 所有节点变完成
wait(500ms)
collapseGraphCard()                     ← 图卡片收拢
expandResultCards()                     ← 展开 SQL/数据/图表
```

### 3.4 过渡动画

1. SSE `done` 事件触发
2. 所有未完成节点快速变绿（0.3s）
3. 全部完成态保持 0.5s
4. 图卡片 `max-height` 从展开值过渡到 0（0.4s ease）
5. 结果卡片（SQL、数据表、图表）从隐藏过渡到展开

### 3.5 布局策略

从上到下主流程，分支左右分叉：

```
              START
                │
         🔍 意图识别
                │
         ┌──────┴──────┐
    💬 非数据回答    🏷️ 复杂度分类
                │
         ┌──────┴──────┐
    🧩 拆解问题      📝 语义解析
         │                │
    🎯 编排执行      🗄️ Schema检索
                        │
                   ⚡ 生成 SQL
                        │
                   🔍 SQL 审查
                        │
                   🛡️ SQL 校验
                        │
                 ┌──────┴──────┐
            ❌ 校验失败     ▶️ 执行查询
                        │
              ┌─────────┼─────────┐
         💬 汇总回答  🔧 ReAct修复  ❌ 执行失败
                        │
                    (回到执行)
```

---

## 4. 不变的部分

- 后端 `graph.py` — 不改
- 后端 `text2sql.py` SSE 端点 — 不改
- 数据库 Schema 浏览器 — 不改
- 对话区 — 不改
- ECharts 图表逻辑 — 不改
- SQL 高亮 — 不改

---

## 5. 不做的事

- 不引入第三方图可视化库（React Flow, D3.js 等）
- 不支持缩放/拖拽（当前版本）
- 不支持历史回放
- 不自动滚动到当前节点（后续迭代）

---

## 6. 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `frontend/app.js` | 重写图相关部分 | GRAPH 配置 + buildSvg + lightNode + 状态管理 + 过渡动画 |
| `frontend/style.css` | 新增样式 | 卡片节点 .gn-card, 4 种状态类, 过渡动画, 分支标签样式 |
| `frontend/index.html` | 可能微调 | 图 SVG viewBox 尺寸调整（如果 16 节点需要更大空间） |
