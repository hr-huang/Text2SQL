# 07 — MCP 真实应用场景和代码

## 场景：Claude Desktop 读你电脑上的文件夹

---

## 完整三步骤

### 第 1 步：安装官方文件系统 MCP Server

```bash
# 什么都不用写，Anthropic 官方已经写好了
npx -y @modelcontextprotocol/server-filesystem C:\Users\黄海睿\Documents
```

这个命令启动了一个 MCP Server，里面有两个工具：
- `list_files(path)` — 列出文件夹内容
- `read_file(path)` — 读取文件内容

---

### 第 2 步：编辑 Claude Desktop 配置文件

文件位置：`%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:\\Users\\黄海睿\\Documents"]
    }
  }
}
```

---

### 第 3 步：重启 Claude Desktop，然后问它

```
你：帮我看看 Documents 文件夹里有哪些 PDF 文件

Claude：（内部自动调用 list_files → read_file → 回复）
"你的 Documents 里有 3 个 PDF：简历.pdf、需求文档.pdf、论文参考文献.pdf"
```

---

## 如果你要写一个 MCP Server（Python 版）

下面是一个**完整可运行的 MCP Server 代码**，功能是管理 SQLite 数据库：

```python
# sqlite_mcp_server.py —— 完整代码，80 行

import sqlite3
import asyncio
import json
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# ① 创建 Server
server = Server("sqlite-manager")

# ② 定义工具列表
@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="list_tables",
            description="列出数据库中的所有表",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="describe_table",
            description="查看某张表的字段结构",
            inputSchema={
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "表名"
                    }
                },
                "required": ["table_name"],
            },
        ),
        Tool(
            name="run_query",
            description="执行 SELECT 查询（只读）",
            inputSchema={
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "SELECT 查询语句"
                    }
                },
                "required": ["sql"],
            },
        ),
    ]

# ③ 工具执行逻辑
@server.call_tool()
async def call_tool(name: str, arguments: dict):
    conn = sqlite3.connect("chinook.db")
    conn.row_factory = sqlite3.Row

    if name == "list_tables":
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        result = "数据库中的表：\n" + "\n".join(f"  - {r['name']}" for r in rows)
        return [TextContent(type="text", text=result)]

    if name == "describe_table":
        table = arguments["table_name"]
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        result = f"表 {table} 的字段：\n"
        for r in rows:
            result += f"  {r['name']} ({r['type']})"
            if r['pk']:
                result += " [主键]"
            result += "\n"
        return [TextContent(type="text", text=result)]

    if name == "run_query":
        sql = arguments["sql"].upper()
        if not sql.strip().startswith("SELECT"):
            return [TextContent(type="text", text="错误：只允许 SELECT 查询")]
        try:
            rows = conn.execute(sql).fetchall()
            result = json.dumps([dict(r) for r in rows[:50]], ensure_ascii=False, indent=2)
            return [TextContent(type="text", text=result)]
        except Exception as e:
            return [TextContent(type="text", text=f"查询失败：{e}")]

    conn.close()

# ④ 启动
async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

asyncio.run(main())
```

---

## 这个 Server 和 Claude Desktop 的对话过程

```
┌─────────────────────────────────────────────────────────────┐
│                    Claude Desktop 启动                        │
│                                                               │
│  1. 读 claude_desktop_config.json                             │
│  2. 发现 "sqlite-manager"                                     │
│  3. 执行: python sqlite_mcp_server.py                        │
│  4. Server 启动，等待消息                                     │
└──────────────────────┬──────────────────────────────────────┘
                       │
        ┌──────────────┴──────────────┐
        │    JSON-RPC (通过 stdio)     │
        │    Standard Input/Output     │
        └──────────────┬──────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                sqlite_mcp_server.py                           │
│                                                               │
│  收到消息 → 执行工具 → 返回结果                                │
│  能做的事：list_tables / describe_table / run_query            │
└─────────────────────────────────────────────────────────────┘
```

**具体对话**：

```
Claude: → {"method":"tools/list", "params":{}}

Server: ← {"tools":[
  {"name":"list_tables","description":"列出数据库中的所有表"},
  {"name":"describe_table","description":"查看某张表的字段结构",...},
  {"name":"run_query","description":"执行 SELECT 查询",...}
]}

Claude: → {"method":"tools/call", "params":{
  "name":"list_tables",
  "arguments":{}
}}

Server: ← {"content":[{"type":"text",
  "text":"数据库中的表：\n  - Album\n  - Artist\n  - Customer\n  ..."
}]}

Claude: → {"method":"tools/call", "params":{
  "name":"describe_table",
  "arguments":{"table_name":"Customer"}
}}

Server: ← {"content":[{"type":"text",
  "text":"表 Customer 的字段：\n  CustomerId (INTEGER) [主键]\n  FirstName (NVARCHAR)\n  ..."
}]}
```

---

## 和 Function Calling 的区别（在同一张图上）

```
Function Calling (你的ReAct Repair):
┌──────────────┐
│  LLMService  │
│              │
│ ① tools=[]   │──── 工具定义作为API参数传进去
│ ② LLM返回    │
│    tool_call  │
│ ③ 你的代码   │──── 执行工具
│    在同一进程  │
└──────────────┘

MCP:
┌──────────────┐          ┌──────────────────┐
│  Claude      │  JSON-   │  sqlite_mcp_     │
│  Desktop     │──RPC────→│  server.py        │
│              │          │                   │
│ ① 自动发现   │←────────│ ② 返回工具列表    │
│ ③ 调用工具   │────────→│ ④ 执行并返回结果   │
│              │          │                   │
│ 独立的AI应用  │   stdio   │  独立的工具进程    │
└──────────────┘          └──────────────────┘
```

**一句话**：Function Calling 是进程内的，MCP 是进程间的。你的 ReAct Repair 适合 Function Calling，跨 AI 客户端共享工具才需要 MCP。

---

## MCP 在企业中的真实使用场景

### 场景 1：公司内部"工具市场"

字节有 100+ 个内部系统（用户系统、订单系统、物流系统...）。每个系统封装成一个 MCP Server。任何 AI 应用要调某个系统，直接在 MCP 配置里加上就行。

```
AI应用A ──→ 用户MCP Server ──→ 用户系统
AI应用B ──→ 用户MCP Server ──→ 用户系统
          ──→ 订单MCP Server ──→ 订单系统
          ──→ 物流MCP Server ──→ 物流系统
```

### 场景 2：Cursor + MCP 代码分析

Cursor 内置 MCP 客户端。你接一个代码库分析 MCP Server，Cursor 就能：
- 查某个函数的定义和调用链
- 跑单元测试
- 查 git blame

所有这些能力都通过 MCP Server 暴露，Cursor 不用适配每个工具。

### 场景 3：跨公司生态

Anthropic 官方的 filesystem MCP Server、GitHub MCP Server、Slack MCP Server——都是开源的。你装了就接，不用写任何代码。**这就是 MCP 的核心价值：一次开发，任何 AI 都能用。**

---

## 什么时候用 MCP vs Function Calling

| 场景 | 用什么 |
|------|--------|
| 我自己的 Agent 用自己的工具 | **Function Calling** |
| 我做了个工具，想让别人的 AI 也能用 | **MCP** |
| 公司有 10 个内部系统，每个系统一个工具 | **MCP**（一个系统一个 Server） |
| 我的 Agent 需要调用外部服务（天气API、数据库） | **Function Calling**（API调一次就行） |