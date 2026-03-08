"""MCP Proxy server for sharing stdio MCP servers over HTTP."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
from typing import Any, Optional

from aiohttp import web


class MCPServer:
    """Process wrapper for a single stdio MCP server."""

    def __init__(self, name: str, config: dict[str, Any]):
        self.name = name
        self.config = config
        self.process: Optional[asyncio.subprocess.Process] = None
        self.running = False

    async def start(self) -> None:
        if self.running:
            return

        cmd = self.config["command"]
        args = self.config.get("args", [])
        env = self.config.get("env", {})
        cwd = self.config.get("cwd", None)
        full_env = os.environ.copy()
        full_env.update(env)

        self.process = await asyncio.create_subprocess_exec(
            cmd,
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=full_env,
            cwd=cwd,
        )
        self.running = True
        print(f"[{self.name}] MCP server started (PID: {self.process.pid})")

    async def stop(self) -> None:
        if not self.running:
            return
        if self.process:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
            self.process = None
        self.running = False
        print(f"[{self.name}] MCP server stopped")

    async def send_request(self, request: dict[str, Any]) -> dict[str, Any]:
        if not self.process or not self.running:
            raise RuntimeError(f"MCP server {self.name} is not running")

        request_str = json.dumps(request) + "\n"
        assert self.process.stdin is not None
        self.process.stdin.write(request_str.encode())
        await self.process.stdin.drain()

        assert self.process.stdout is not None
        response_line = await self.process.stdout.readline()
        if not response_line:
            raise RuntimeError(f"No response from MCP server {self.name}")

        return json.loads(response_line.decode())


class MCPProxy:
    """HTTP proxy for multiple MCP servers."""

    def __init__(self, config_path: str):
        self.config = self._load_config(config_path)
        self.servers: dict[str, MCPServer] = {}
        self.app = web.Application()
        self.app.router.add_post("/{server_name}", self.handle_request)
        self.app.router.add_get("/health", self.handle_health)
        self.app.router.add_get("/tools", self.handle_tools)

    @staticmethod
    def _load_config(config_path: str) -> dict[str, Any]:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    async def start_servers(self) -> None:
        mcp_servers = self.config.get("mcpServers", {})
        for name, config in mcp_servers.items():
            if config.get("disabled", False):
                continue
            if config.get("type") != "stdio":
                continue
            server = MCPServer(name, config)
            await server.start()
            self.servers[name] = server

    async def stop_servers(self) -> None:
        for server in self.servers.values():
            await server.stop()
        self.servers.clear()

    async def handle_request(self, request: web.Request) -> web.Response:
        server_name = request.match_info["server_name"]
        if server_name not in self.servers:
            return web.json_response({"error": f"Unknown MCP server: {server_name}"}, status=404)
        try:
            body = await request.json()
            response = await self.servers[server_name].send_request(body)
            return web.json_response(response)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "healthy", "servers": list(self.servers.keys())})

    async def handle_tools(self, request: web.Request) -> web.Response:
        """返回所有 MCP 服务器的工具列表"""
        import asyncio
        tools_info = {}
        
        async def fetch_tools(name, server):
            try:
                # 调用 MCP 的 tools/list 方法，超时 3 秒
                response = await asyncio.wait_for(
                    server.send_request({"method": "tools/list", "params": {}}),
                    timeout=3.0
                )
                return name, response.get("result", {}).get("tools", [])
            except asyncio.TimeoutError:
                return name, {"error": "timeout"}
            except Exception as e:
                return name, {"error": str(e)}
        
        # 并行获取所有服务器的工具列表
        tasks = [fetch_tools(name, server) for name, server in self.servers.items()]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, Exception):
                tools_info[str(result)] = {"error": "failed"}
            else:
                name, tools = result
                tools_info[name] = tools
        
        return web.json_response({"servers": list(self.servers.keys()), "tools": tools_info})

    async def start_http_server(self, port: int) -> web.AppRunner:
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, "localhost", port)
        await site.start()
        print(f"MCP Proxy listening on HTTP port: http://localhost:{port}")
        print(f"Available MCP servers: {list(self.servers.keys())}")
        return runner


async def _shutdown(proxy: MCPProxy) -> None:
    await proxy.stop_servers()
    print("Shutdown complete")


async def main() -> None:
    parser = argparse.ArgumentParser(description="MCP Server Proxy")
    parser.add_argument("--config", required=True, help="Path to MCP config file")
    parser.add_argument("--port", default=8888, type=int, help="HTTP port (default: 8888)")
    args = parser.parse_args()

    proxy = MCPProxy(args.config)
    await proxy.start_servers()
    runner = await proxy.start_http_server(args.port)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _stop_signal() -> None:
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _stop_signal)
        except NotImplementedError:
            # Windows with Proactor event loop may not support signal handlers.
            pass

    try:
        await stop_event.wait()
    finally:
        await runner.cleanup()
        await _shutdown(proxy)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
