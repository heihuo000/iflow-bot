# iflow-bot v0.3.4 发布说明

## 发布信息

- **版本**: 0.3.4
- **发布日期**: 2026-03-08
- **发布包**: iflow-bot-v0.3.4-release.tar.gz
- **文件大小**: 8.6 MB
- **SHA256**: c012ab1075dc6ba9f1641b0723f9b8aed698c5785d14667a50ed07da217d16b8

## 包含文件

```
iflow-bot-v0.3.4-release.tar.gz
├── iflow_bot-0.3.4-py3-none-any.whl  (198 KB) - Wheel 包（推荐）
├── iflow_bot-0.3.4.tar.gz             (8.4 MB)  - 源码包
├── INSTALL.md                          (2.2 KB)  - 安装指南
├── SHA256SUMS                          (188 B)   - 校验和文件
├── README.md                           (项目说明)
└── LICENSE                             (MIT 许可证)
```

## 快速开始

### 1. 解压发布包

```bash
tar -xzf iflow-bot-v0.3.4-release.tar.gz
cd iflow-bot-src
```

### 2. 安装 iflow-bot

```bash
# 推荐使用 wheel 包（更快）
pip install dist/iflow_bot-0.3.4-py3-none-any.whl

# 或使用源码包
pip install dist/iflow_bot-0.3.4.tar.gz
```

### 3. 安装 iflow CLI

```bash
# Linux/macOS
curl -fsSL https://gitee.com/iflow-ai/iflow-cli/raw/main/install.sh | bash

# 或使用 npm
npm install -g @iflow-ai/iflow-cli@latest
```

### 4. 登录并配置

```bash
# 登录 iflow
iflow login

# 配置 iflow-bot
cp config.example.json ~/.iflow-bot/config.json
nano ~/.iflow-bot/config.json
```

### 5. 启动服务

```bash
# 后台启动（自动启动 MCP 代理）
iflow-bot gateway start

# 查看状态
iflow-bot status

# 停止服务
iflow-bot gateway stop
```

## 新功能

### v0.3.4 新增功能

1. **MCP 共享代理**
   - 自动管理共享 MCP 服务器
   - 减少资源消耗（进程数从 15 降至 3）
   - 支持动态配置端口

2. **配置文件增强**
   - 在 `~/.iflow-bot/config.json` 中配置 MCP 代理
   - 支持 `mcp_proxy_enabled`, `mcp_proxy_port`, `mcp_proxy_auto_start`

3. **自动启动 MCP 代理**
   - 启动网关时自动检查并启动 MCP 代理
   - 支持通过命令行参数 `--without-mcp` 禁用

4. **QQ Markdown 修复**
   - 修复 QQ 群消息 Markdown 格式显示问题
   - 支持流式 Markdown 输出

## 系统要求

- Python 3.10 或更高版本
- iflow CLI（需要单独安装）
- Linux, macOS, 或 Windows
- 网络连接（用于访问 iflow API）

## 依赖项

主要依赖包括：
- typer, rich - CLI 界面
- fastapi, uvicorn - Web 服务
- python-telegram-bot - Telegram 支持
- discord.py - Discord 支持
- slack-sdk - Slack 支持
- qq-botpy - QQ 支持
- 以及其他依赖...

完整依赖列表见 `pyproject.toml`

## MCP 代理配置

### 配置文件

编辑 `~/.iflow-bot/config.json`:

```json
{
  "driver": {
    "mcp_proxy_enabled": true,
    "mcp_proxy_port": 8888,
    "mcp_proxy_auto_start": true
  }
}
```

### 手动管理

```bash
# 启动 MCP 代理
bash ~/iflow-bot-src/scripts/start_mcp_proxy.sh

# 停止 MCP 代理
bash ~/iflow-bot-src/scripts/stop_mcp_proxy.sh

# 测试 MCP 代理
bash ~/iflow-bot-src/scripts/test_mcp_proxy.sh
```

## 支持的渠道

- ✅ Telegram
- ✅ Discord
- ✅ Slack
- ✅ QQ
- ✅ 飞书
- ✅ 钉钉
- ✅ WhatsApp
- ✅ Email
- ✅ MoChat

## 升级说明

从 v0.3.3 升级到 v0.3.4：

```bash
# 卸载旧版本
pip uninstall iflow-bot

# 安装新版本
pip install dist/iflow_bot-0.3.4-py3-none-any.whl

# 更新配置文件（可选，新增 MCP 代理配置）
nano ~/.iflow-bot/config.json
```

## 问题反馈

- GitHub Issues: https://github.com/heihuo000/qwen-code/issues
- 文档: https://github.com/heihuo000/qwen-code/blob/main/iflow-bot-src/README.md

## 许可证

MIT License - 详见 LICENSE 文件

## 致谢

感谢所有贡献者的支持！

---

**下载链接**: https://github.com/heihuo000/qwen-code/releases/tag/v0.3.4

**校验和**: `sha256sum iflow-bot-v0.3.4-release.tar.gz`

**预期输出**: `c012ab1075dc6ba9f1641b0723f9b8aed698c5785d14667a50ed07da217d16b8  iflow-bot-v0.3.4-release.tar.gz`
