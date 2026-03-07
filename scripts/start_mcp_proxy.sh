#!/bin/bash
# 启动 MCP 代理服务器

# 配置文件路径
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
CONFIG_FILE="$PROJECT_ROOT/config/.mcp_proxy_config.json"
LOG_FILE="$PROJECT_ROOT/mcp_proxy.log"
PID_FILE="$PROJECT_ROOT/mcp_proxy.pid"

# 默认端口，可通过环境变量覆盖
PORT=${MCP_PROXY_PORT:-8888}

# 检查是否已经在运行
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "MCP Proxy is already running (PID: $PID)"
        exit 1
    else
        rm -f "$PID_FILE"
    fi
fi

# 启动代理
echo "Starting MCP Proxy..."
python3 "$HOME/iflow-bot-src/scripts/mcp_proxy.py" \
    --config "$CONFIG_FILE" \
    --port 8888 &

PID=$!
echo $PID > "$PID_FILE"

echo "MCP Proxy started (PID: $PID)"
echo "HTTP: http://localhost:8888"
echo ""
echo "Available endpoints:"
echo "  - http://localhost:8888/github"
echo "  - http://localhost:8888/dnf-rag"
echo "  - http://localhost:8888/message-board"
