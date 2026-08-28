# Contributing to Enterprise Text2SQL

欢迎贡献！无论是修复 bug、增加功能、改进文档还是提 issue，都非常感谢。

## 开发环境

```bash
# 1. 克隆 + 装依赖
git clone <repo>
cd enterprise_text2sql
pip install -r requirements.txt

# 2. 配置 .env
cp .env.example .env
# 编辑 .env 填入 API key

# 3. 启动
python -m app.main
# 访问 http://localhost:8000/demo
```

## 提交流程

1. **Fork** → 创建 feature 分支：`git checkout -b feat/xxx`
2. **开发** → 写代码 + 测试
3. **跑评测** → `python scripts/run_evaluation.py --tag your_change`（确认不破坏现有指标）
4. **提 PR** → 描述改了什么、为什么

## 改 Prompt 时

- 改之前先跑一次 `analyze_bad_cases.py` 看当前错题分布
- 改之后跑评测 + 分类，对比改进
- 在 PR 描述里附上 before/after 数据

## 加新 Node 时

- 在 `app/nodes/` 加节点函数
- 在 `app/prompts/` 加对应 prompt（如有）
- 在 `app/workflow/graph.py` 注册节点 + 加边
- 在 `app/schemas/state.py` 加 state 字段
- 在 `frontend/app.js` 的 NODES 数组加可视化

## 提交信息规范

```
feat: 加新功能
fix: 修 bug
docs: 改文档
refactor: 重构（无功能变化）
perf: 性能优化
test: 加测试
```

## 行为准则

请保持友善和专业。专注在技术问题本身。

## 联系

Issue Tracker → 提 Issue。