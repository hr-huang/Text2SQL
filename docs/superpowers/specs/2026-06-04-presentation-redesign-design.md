# Enterprise Text2SQL 期末汇报演示文稿重设计

## 背景

现有 `presentation.html`（9页滚动网页幻灯片）和 `output/enterprise_text2sql_python_final.pptx`（python-pptx 生成）存在以下问题：

- **无流程图**：LangGraph 架构仅用文字块罗列，没有可视化
- **无架构图**：系统全貌无法一目了然
- **排版单调**：每页都是"标题 + 文字卡片"的重复节奏
- **数据展示弱**：评测结果只是数字，缺乏视觉对比
- **重点不突出**：所有信息同等权重，没有视觉层级

## 目标

重新制作一个高质量演示文稿，用于 5 分钟期末汇报。听众：老师 + 全体同学。考核重点：技术实现深度、项目完整度。

## 约束

- 5 分钟讲解时长
- 输出为单文件 HTML 网页幻灯片（浏览器打开即用）
- 展示真实的 LangGraph 流程图、架构图、评测数据
- 深色主题技术叙事风

## 幻灯片结构（7 页）

### Slide 1 · 封面（30s）

**标题**：Enterprise Text2SQL
**副标题**：从中文问题到可验证 SQL 的 Agent 系统
**视觉元素**：右下角系统 UI 界面预览小图（模拟浏览器窗口，展示 schema 面板 + SQL 面板）
**色彩**：深色背景 + cyan 强调色

### Slide 2 · 痛点与方案（45s）⭐ 重点页

**布局**：左右 50:50 分栏

**左栏 — 两重困境（红色调）**：
- 困境一：手写 SQL
  - 企业几十上百张表，记住所有表名和字段不现实
  - JOIN 路径复杂，跨 5 张表才能回答一个品类分析
  - 字段业务含义需翻文档（total_amount 含税吗？order_date 是什么时间？）
  - 复杂问题需要子查询/窗口函数，嵌套易错
  - > 结论：运营想查"上月各品类销售额排名"，得找数据分析师写半小时 SQL
- 困境二：丢给 ChatGPT
  - 模型不知道你的数据库有哪些表、字段
  - 字段名是英文缩写（cust_id / ord_amt），模型猜不透业务含义
  - SQL 语法对但语义错——JOIN 错表、漏 WHERE 条件
  - 更危险：可能生成 DELETE/DROP，直接跑就是事故
  - > 结论：AI 写的 SQL，你敢直接跑在生产库上吗？

**右栏 — 四个方案卡片（青色调）**：
1. Schema 感知 — RAG 检索相关表和字段，模型不再瞎猜
2. 结构化生成 — 语义解析→Schema检索→SQL生成→Review→校验，每步可追踪
3. 安全执行 — AST 级校验，只允许 SELECT，拒绝一切写操作
4. 复杂问题拆解 — 自动识别分解子问题，按依赖顺序执行，结果汇总

**视觉对比**：左红右青，色彩叙事——红色=痛苦 → 青色=解药

### Slide 3 · 核心架构：LangGraph 流程图（60s）🔥 最重要

**整页展示完整的 LangGraph StateGraph 流程图**，包含：

- 所有节点：intent → classify → [分支] → semantic → schema → sql_gen → sql_review → validate → execute → answer
- 复杂路径分支：classify → decompose → orchestrator → END
- 修复回路：execute(失败) → sql_repair → execute（最多3次）
- 三种终端出口：answer_non_data / answer_validation_failed / answer_exec_failed

**颜色编码**：
- 蓝色节点 = 简单 SQL 路径
- Amber 节点 = 复杂问题路径（decompose + orchestrator）  
- 绿色节点 = 安全/修复回路
- 灰色 = 终端出口

**排版**：流程图占页面主体（~80%面积），左下角放一句总结文字。

### Slide 4 · 复杂问题：分类→拆解→编排（50s）

**上半部分**：具体示例展开
- 原始问题："消费最高的10个客户分别买了哪些品类？"
- 拆成两个子问题：
  1. "消费总额最高的10个客户的 CustomerId？"（无依赖）
  2. "这10个客户分别购买的音乐类型及数量？"（依赖步骤1）
- 展示 orchestrator 如何拓扑排序 + 按依赖顺序执行

**下半部分**：编排器内部流程小图
- 每个子问题 → 完整重放 SQL 管道（schema→semantic→sql_gen→review→validate→execute→repair）
- 前置结果通过 context_from_previous 注入后续子问题
- 失败传播：前置子问题失败 → 依赖它的自动跳过

### Slide 5 · 安全边界（40s）

**四层防线图示**（同心圆或护盾布局）：
1. 外层 — sqlglot AST 解析，识别 SQL 结构
2. 中层 — 只允许 exp.Select 根节点，拒绝 Insert/Update/Delete/Drop/Create/Alter
3. 内层 — 候选表白名单，提取 SQL 使用表名做白名单校验
4. 核心 — Repair Agent，执行失败自动重写 SQL，最多 3 次

**设计理念大字**："LLM 负责生成，系统负责边界"

### Slide 6 · 评测结果（45s）🔥

**四个大数字**（stat cards）：
- 91.7%（DeepSeek V4 Flash v8 总正确率）
- 55/60（通过题数）
- 29/29（简单题，100%）
- 3/4（复杂题，较 v1 的 0/4 大幅提升）

**下方模型对比表**：
| 模型 | 版本 | 正确率 | 中等题 | 复杂题 |
|------|------|--------|--------|--------|
| DeepSeek V4 Flash | v8 | 91.7% | 23/27 | 3/4 |
| DeepSeek V4 Flash | v1 | 80.0% | 20/27 | 0/4 |
| MiMo 2.5 Flash | v2 | 80.0% | 20/27 | 0/4 |

**关键叙事**：v8 通过 decompose 把复杂题从 0/4 提升到 3/4——证明复杂问题拆解机制有效。

### Slide 7 · 总结（30s）

- 三个关键词大字报：**可运行 · 可观察 · 可评测**
- 下方一行启动命令：`pip install ... && uvicorn app.main:app`
- 右下角 "Thank You"
- 可选：GitHub 链接或二维码

## 技术方案

### 输出格式

单文件 self-contained HTML，所有 CSS/JS 内联。无外部依赖（Google Fonts 用系统字体 fallback）。

### 实现方式

- 使用 `html-ppt` 或 `frontend-slides` skill 生成
- 流程图用内联 SVG 手绘（或 Mermaid 编译为 SVG）
- 需要适配键盘翻页（↑↓←→ / 滚动）

### 不做的

- 不生成 PPTX（HTML 优先，只在必要时手动导出关键页为图片放 PPTX 备份）
- 不前端的 SSE 流式连接真实系统（静态演示即可）
- 不加音频/视频
