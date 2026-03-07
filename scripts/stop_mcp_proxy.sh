#!/bin/bash
# 停止 MCP 代理服务器

PID_FILE="$HOME/iflow-bot-src/mcp_proxy.pid"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    echo "Stopping MCP Proxy (PID: $PID)..."
    kill $PID 2>/dev/null
    
    # 等待进程结束
    for i in {1..10}; do
        if ! ps -p "$PID" > /dev/null 2>&1; then
            echo "MCP Proxy stopped"
            rm -f "$PID_FILE"
            exit 0
        fi
        sleep 1
    done
    
    # 强制杀死
    kill -9 $PID 2>/dev/null
    rm -f "$PID_FILE"
    echo "MCP Proxy stopped (forced)"
else
    echo "MCP Proxy is not running"
fi
