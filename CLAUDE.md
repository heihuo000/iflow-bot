# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 快速命令

```bash
# 安装依赖
uv sync

# 运行测试
uv run pytest
uv run pytest -v tests/test_qq_split.py  # 运行单个测试文件

# 本地调试运行
uv run iflow-bot gateway run

# 后台运行
uv run iflow-bot gateway start
uv run iflow-bot status
uv run iflow-bot gateway stop

# 查看帮助
uv run iflow-bot --help
```

## 项目架构

### 核心结构

iflow-bot 是一个多平台消息机器人，基于 iflow CLI 构建，将 AI 能力扩展到多个通信平台。

```
iflow_bot/
├── __main__.py              # CLI 入口点
├── bus/                     # 消息总线
│   ├── events.py            # InboundMessage/OutboundMessage 事件定义
│   └── queue.py             # 消息队列实现
├── channels/                # 各平台渠道实现
│   ├── base.py              # BaseChannel 抽象基类 (start/stop/send)
│   ├── manager.py           # Channel 管理器，统一注册/启动/管理
│   ├── telegram.py
│   ├── discord.py
│   ├── slack.py
│   ├── feishu.py
│   ├── dingtalk.py
│   ├── qq.py                # QQ 频道实现
│   ├── whatsapp.py
│   ├── email.py
│   └── mochat.py
├── cli/
│   └── commands.py          # Typer CLI 命令定义
├── config/
│   ├── schema.py            # Pydantic 配置模型
│   └── loader.py            # 配置加载 (~/.iflow-bot/config.json)
├── cron/                    # 定时任务服务
├── engine/                  # 核心引擎
│   ├── adapter.py           # iflow 适配器
│   ├── stdio_acp.py         # Stdio 通信模式 (推荐)
│   ├── acp.py               # ACP WebSocket 模式
│   └── loop.py              # 消息循环处理
├── session/
│   └── manager.py           # 多用户会话管理
├── web/                     # Web 控制台
└── utils/
    └── helpers.py           # 工具函数
```

### 消息处理流程

1. **入站**: 各 Channel 接收外部消息 → 权限检查 → 发布到 `MessageBus.inbound_queue`
2. **处理**: `EngineLoop` 从队列取消息 → iflow 适配器调用 iflow CLI → 获取 AI 响应
3. **出站**: 响应发布到 `MessageBus.outbound_queue` → 对应 Channel 的 `send()` 方法发送

### Channel 架构

所有渠道继承自 `BaseChannel`，实现三个抽象方法：
- `start()`: 启动并监听消息
- `stop()`: 停止并清理资源
- `send(OutboundMessage)`: 发送消息到平台

通用功能由基类提供：
- `is_allowed()`: 白名单权限检查
- `_handle_message()`: 消息处理并发布到总线

### 配置管理

配置文件位于 `~/.iflow-bot/config.json`，配置模型定义在 `config/schema.py`：

- **driver**: iflow 通信模式配置（stdio/acp/cli）、模型、超时等
- **channels**: 各渠道开关和凭据配置
- **log_level/log_file**: 日志配置

### MCP 代理配置

MCP 代理采用共享模式，多个 iflow 实例共用一个 MCP 代理服务器（端口 8888），避免资源浪费。

**配置项**（`driver` 下）：

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `mcp_proxy_enabled` | bool | `true` | 是否启用 MCP 代理 |
| `mcp_proxy_port` | int | `8888` | MCP 代理服务器端口 |
| `mcp_proxy_auto_start` | bool | `true` | 网关启动时自动启动 MCP 代理 |
| `mcp_servers_auto_discover` | bool | `true` | 自动从 MCP 代理发现启用的服务器 |
| `mcp_servers_max` | int | `10` | 单个 iflow 实例最多连接的 MCP 服务器数量 |
| `mcp_servers_allowlist` | list | `[]` | 允许使用的 MCP 服务器名称列表（空表示全部） |
| `mcp_servers_blocklist` | list | `[]` | 禁用的 MCP 服务器名称列表 |

**配置文件位置**（按优先级）：
1. `~/.iflow-bot/config/.mcp_proxy_config.json` - 运行时配置（推荐）
2. `项目目录/config/.mcp_proxy_config.json` - 项目配置

**同步 iflow CLI 配置**：
```bash
# 从 iflow 的 settings.json 同步 MCP 配置
iflow-bot mcp-sync

# 覆盖现有配置
iflow-bot mcp-sync --overwrite
```

**MCP 服务器配置格式**：
```json
{
  "mcpServers": {
    "github": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "disabled": false
    },
    "dnf-rag": {
      "type": "stdio",
      "command": "python3",
      "args": ["/path/to/rag_server.py"],
      "disabled": false
    }
  }
}
```

**工作流程**：
1. MCP Proxy 启动时加载配置文件中的 MCP 服务器
2. iflow 实例通过 `discover_mcp_servers()` 从代理动态获取服务器列表
3. 支持白名单/黑名单过滤和数量限制，防止资源耗尽

**多平台支持**：
- Linux/Android (Termux): `~/.iflow/`
- macOS: `~/Library/Application Support/iflow/`
- Windows: `%APPDATA%/iflow/`

### Web 控制台

启动：`iflow-bot console --host 127.0.0.1 --port 8787`

**功能页面**：
- **仪表盘** (`/`) - Gateway 状态、会话统计
- **Web 对话** (`/chat`) - 网页与 AI 对话
- **全渠道对话** (`/conversations`) - 查看各渠道聊天记录
- **配置中心** (`/config`) - 编辑配置文件
- **MCP 代理** (`/mcp`) - 查看 MCP 服务器状态、配置、健康检查
- **实时日志** (`/logs`) - 查看网关日志

**MCP 代理页面功能**：
- 查看运行状态和 PID
- 查看配置的 MCP 服务器列表
- 健康检查（显示发现的服务）
- 重启 MCP 代理
- 从 iflow CLI 同步配置

## 开发注意事项

### 添加新 Channel

1. 在 `channels/` 目录创建新文件，继承 `BaseChannel`
2. 实现 `start()`、`stop()`、`send()` 三个抽象方法
3. 在 `channels/manager.py` 中注册新 Channel

### 消息事件

- `InboundMessage`: channel, sender_id, chat_id, content, media, metadata
- `OutboundMessage`: channel, chat_id, content, media, metadata, reply_to_message_id

### 会话管理

会话映射存储在 `~/.iflow-bot/session_mappings.json`，格式：`{channel}:{chat_id} -> {sessionId}`

### 调试

- 日志文件：`~/.iflow-bot/gateway.log`
- 使用 `uv run iflow-bot gateway run` 在前台运行查看详细日志
- QQ 频道额外日志：`botpy.log`
