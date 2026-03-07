#!/bin/bash
# 测试 MCP 代理功能

set -e

echo "=== MCP 代理功能测试 ==="
echo ""

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 测试函数
test_endpoint() {
    local name=$1
    local endpoint=$2
    echo -n "测试 $name ... "
    
    response=$(curl -s -X POST "http://localhost:8888$endpoint" \
        -H "Content-Type: application/json" \
        -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"1","clientCapabilities":{},"capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}')
    
    if echo "$response" | grep -q '"result"'; then
        echo -e "${GREEN}✓ 通过${NC}"
        echo "  响应: $(echo $response | jq -r '.result.serverInfo.name // .result')"
    else
        echo -e "${RED}✗ 失败${NC}"
        echo "  响应: $response"
        return 1
    fi
}

# 1. 检查 MCP 代理是否运行
echo "1. 检查 MCP 代理状态"
if curl -s http://localhost:8888/health > /dev/null 2>&1; then
    echo -e "${GREEN}✓ MCP 代理正在运行${NC}"
    health=$(curl -s http://localhost:8888/health)
    echo "  可用服务器: $(echo $health | jq -r '.servers' 2>/dev/null || echo $health)"
else
    echo -e "${RED}✗ MCP 代理未运行${NC}"
    echo "请先运行: bash ~/iflow-bot-src/scripts/start_mcp_proxy.sh"
    exit 1
fi
echo ""

# 2. 测试各个 MCP 端点
echo "2. 测试 MCP 端点"
test_endpoint "GitHub MCP" "/github"
test_endpoint "DNF RAG MCP" "/dnf-rag"
test_endpoint "Message Board MCP" "/message-board"
echo ""

# 3. 检查进程数
echo "3. 检查 MCP 进程数"
mcp_count=$(ps aux | grep -E "simple_server|mcp-server-github|message-board.*mcp_server_simple" | grep -v grep | grep -v "mcp_proxy" | wc -l)
echo "  当前 MCP 进程数: $mcp_count"
if [ "$mcp_count" -eq 3 ]; then
    echo -e "${GREEN}✓ 进程数正常（3 个）${NC}"
else
    echo -e "${YELLOW}⚠ 进程数异常（期望 3 个，实际 $mcp_count 个）${NC}"
fi
echo ""

# 4. 检查内存使用
echo "4. 检查内存使用"
if command -v free &> /dev/null; then
    mem_info=$(free -h | grep Mem)
    echo "  $mem_info"
fi
echo ""

# 5. 检查 iflow-bot 状态
echo "5. 检查 iflow-bot 状态"
if pgrep -f "iflow_bot.*_run_gateway" > /dev/null; then
    echo -e "${GREEN}✓ iflow-bot 正在运行${NC}"
    iflow_bot_pid=$(pgrep -f "iflow_bot.*_run_gateway")
    echo "  PID: $iflow_bot_pid"
else
    echo -e "${YELLOW}⚠ iflow-bot 未运行${NC}"
fi
echo ""

echo "=== 测试完成 ==="