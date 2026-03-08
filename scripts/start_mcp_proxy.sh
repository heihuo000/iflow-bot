#!/bin/bash
# 启动 MCP 代理服务器

# 配置文件路径 - 支持多位置查找
# 优先级：1. 运行时目录 (~/.iflow-bot/config/)  2. 项目目录  3. 用户指定

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# 默认端口，可通过环境变量覆盖
PORT=${MCP_PROXY_PORT:-8888}

# 支持通过环境变量指定配置文件
if [ -n "$MCP_PROXY_CONFIG" ]; then
    CONFIG_FILE="$MCP_PROXY_CONFIG"
else
    # 多路径查找配置文件
    RUNTIME_CONFIG="$HOME/.iflow-bot/config/.mcp_proxy_config.json"
    PROJECT_CONFIG="$PROJECT_ROOT/config/.mcp_proxy_config.json"

    if [ -f "$RUNTIME_CONFIG" ]; then
        CONFIG_FILE="$RUNTIME_CONFIG"
        echo "Using runtime config: $CONFIG_FILE"
    elif [ -f "$PROJECT_CONFIG" ]; then
        CONFIG_FILE="$PROJECT_CONFIG"
        echo "Using project config: $CONFIG_FILE"
    else
        echo "Error: MCP proxy config file not found!"
        echo "Searched:"
        echo "  - $RUNTIME_CONFIG"
        echo "  - $PROJECT_CONFIG"
        exit 1
    fi
fi

LOG_FILE="${MCP_PROXY_LOG:-$PROJECT_ROOT/mcp_proxy.log}"
PID_FILE="${MCP_PROXY_PID:-$PROJECT_ROOT/mcp_proxy.pid}"

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
echo "Starting MCP Proxy on port $PORT..."
python3 "$SCRIPT_DIR/mcp_proxy.py" \
    --config "$CONFIG_FILE" \
    --port "$PORT" &

PID=$!
echo $PID > "$PID_FILE"

echo "MCP Proxy started (PID: $PID)"
echo "HTTP: http://localhost:$PORT"
echo ""
echo "Available MCP servers will be shown at:"
echo "  - http://localhost:$PORT/health"
