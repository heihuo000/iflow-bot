"""QQ channel implementation using @sliverp/qqbot compatible API.

使用与 @sliverp/qqbot 相同的 QQ 官方 API 和 WebSocket 网关。
支持 C2C 私聊消息和群消息。

参考：https://github.com/sliverp/qqbot
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
import base64
import zlib
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional, Callable, Coroutine

import aiohttp
import websockets
from websockets.asyncio.client import connect as ws_connect

from iflow_bot.bus.events import OutboundMessage
from iflow_bot.bus.queue import MessageBus
from iflow_bot.channels.base import BaseChannel
from iflow_bot.channels.manager import register_channel
from iflow_bot.config.schema import QQConfig

logger = logging.getLogger(__name__)

# QQ Bot API 常量
API_BASE = "https://api.sgroup.qq.com"
TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
GATEWAY_URL = "wss://gateway.sgroup.qq.com/"

# Intent 配置
INTENTS = {
    "GUILDS": 1 << 0,
    "GUILD_MEMBERS": 1 << 1,
    "PUBLIC_GUILD_MESSAGES": 1 << 30,
    "DIRECT_MESSAGE": 1 << 12,
    "GROUP_AND_C2C": 1 << 25,
}

# 权限级别：从高到低依次尝试
INTENT_LEVELS = [
    {"name": "full", "intents": INTENTS["PUBLIC_GUILD_MESSAGES"] | INTENTS["DIRECT_MESSAGE"] | INTENTS["GROUP_AND_C2C"]},
    {"name": "group+channel", "intents": INTENTS["PUBLIC_GUILD_MESSAGES"] | INTENTS["GROUP_AND_C2C"]},
    {"name": "channel-only", "intents": INTENTS["PUBLIC_GUILD_MESSAGES"] | INTENTS["GUILD_MEMBERS"]},
]


@dataclass
class AccessToken:
    """访问令牌。"""
    token: str = ""
    expires_at: float = 0
    expires_in: int = 7200


@dataclass
class SessionState:
    """WebSocket 会话状态。"""
    session_id: str = ""
    last_seq: int = 0
    resume_url: str = ""


class QQBotAPI:
    """QQ Bot API 客户端。"""

    def __init__(self, app_id: str, client_secret: str):
        self.app_id = app_id
        self.client_secret = client_secret
        self._token: Optional[AccessToken] = None
        self._token_lock = asyncio.Lock()
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def get_access_token(self) -> str:
        """获取访问令牌（带缓存）。"""
        async with self._token_lock:
            if self._token and time.time() < self._token.expires_at - 300:
                return self._token.token

        session = await self._get_session()

        logger.info(f"[qqbot] Fetching access token for app_id={self.app_id}")

        try:
            async with session.post(
                TOKEN_URL,
                json={"appId": self.app_id, "clientSecret": self.client_secret},
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                data = await resp.json()

                if not data.get("access_token"):
                    raise Exception(f"Failed to get access_token: {data}")

                expires_in = int(data.get("expires_in", 7200))
                self._token = AccessToken(
                    token=data["access_token"],
                    expires_at=time.time() + expires_in * 0.9,  # 提前 10% 刷新
                    expires_in=expires_in,
                )

                logger.info(f"[qqbot] Token acquired, expires in {expires_in}s")
                return self._token.token

        except Exception as e:
            logger.error(f"[qqbot] Failed to get token: {e}")
            raise

    async def api_request(
        self,
        method: str,
        path: str,
        body: Optional[dict] = None,
        timeout: int = 30,
    ) -> dict:
        """发送 API 请求。"""
        token = await self.get_access_token()
        session = await self._get_session()

        url = f"{API_BASE}{path}"
        headers = {
            "Authorization": f"QQBot {token}",
            "Content-Type": "application/json",
        }

        try:
            async with session.request(
                method,
                url,
                json=body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status >= 400:
                    error_data = await resp.text()
                    logger.error(f"[qqbot] API error {resp.status}: {error_data}")
                    raise Exception(f"API error: {resp.status} - {error_data}")

                return await resp.json()

        except aiohttp.ClientError as e:
            logger.error(f"[qqbot] Network error: {e}")
            raise

    async def send_c2c_message(
        self,
        openid: str,
        content: str,
        msg_id: Optional[str] = None,
        msg_seq: int = 1,
    ) -> dict:
        """发送 C2C 消息。

        注意：如果有 msg_id（回复消息），使用被动回复模式（/messages 接口）
        如果没有 msg_id（主动消息），需要使用 /messages 接口但可能受限于每日配额
        """
        body: dict = {
            "content": content,
            "msg_type": 0,  # 文本
            "msg_seq": msg_seq,
        }

        if msg_id:
            body["msg_id"] = msg_id
            body["event_type"] = "C2C_MESSAGE_CREATE"

        # 使用 /v2/users/{openid}/messages 接口（@sliverp/qqbot 方式）
        return await self.api_request("POST", f"/v2/users/{openid}/messages", body, timeout=30)

    async def send_group_message(
        self,
        group_openid: str,
        content: str,
        msg_id: Optional[str] = None,
        msg_seq: int = 1,
    ) -> dict:
        """发送群消息。"""
        body: dict = {
            "content": content,
            "msg_type": 0,
            "msg_seq": msg_seq,
        }

        if msg_id:
            body["msg_id"] = msg_id
            body["event_type"] = "C2C_MESSAGE_CREATE"

        return await self.api_request("POST", f"/v2/groups/{group_openid}/messages", body, timeout=30)

    async def send_c2c_input_notify(
        self,
        openid: str,
        msg_id: str,
    ) -> None:
        """发送 C2C 输入状态通知。"""
        try:
            body = {
                "msg_id": msg_id,
                "action_type": 1,  # 正在输入
                "event_type": "C2C_INPUT_TYPING",
            }
            await self.api_request("POST", f"/v2/c2c/{openid}/typing", body, timeout=10)
        except Exception as e:
            logger.debug(f"[qqbot] Failed to send typing notify: {e}")

    async def get_gateway_url(self) -> str:
        """获取 WebSocket 网关 URL。"""
        result = await self.api_request("GET", "/gateway", timeout=30)
        return result.get("url", GATEWAY_URL)

    async def get_gateway_bot_url(self) -> str:
        """获取带分片信息的网关 URL。"""
        result = await self.api_request("GET", "/gateway/bot", timeout=30)
        return result.get("url", GATEWAY_URL), result.get("shards", 1), result.get("session_start_limit", {})


# 消息序号追踪器
_msg_seq_tracker: dict[str, int] = {}


def get_next_msg_seq(msg_id: str) -> int:
    """获取下一条消息的序号。"""
    current = _msg_seq_tracker.get(msg_id, 0)
    next_seq = current + 1
    _msg_seq_tracker[msg_id] = next_seq

    # 清理过期记录
    if len(_msg_seq_tracker) > 1000:
        keys = list(_msg_seq_tracker.keys())
        for i in range(500):
            _msg_seq_tracker.pop(keys[i], None)

    return next_seq


@register_channel("qq")
class QQChannel(BaseChannel):
    """QQ Channel - 使用 QQ 官方 API 和 WebSocket 网关。

    与 @sliverp/qqbot 使用相同的 API 实现。

    支持:
    - C2C 私聊消息
    - 群消息
    - 频道消息

    要求:
    - app_id: QQ 机器人 AppID
    - secret: QQ 机器人 Secret
    """

    name = "qq"

    def __init__(self, config: QQConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: QQConfig = config
        self._api: Optional[QQBotAPI] = None
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._processed_ids: deque = deque(maxlen=1000)
        self._session_state: Optional[SessionState] = None
        self._heartbeat_interval: float = 0
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._reconnect_attempts = 0
        self._intent_level_index = 0
        self._last_connect_time: float = 0
        self._msg_seq_map: dict[str, int] = {}

    async def start(self) -> None:
        """启动 QQ Bot 网关连接。"""
        if not self.config.app_id or not self.config.secret:
            logger.error(f"[{self.name}] app_id and secret not configured")
            return

        self._api = QQBotAPI(self.config.app_id, self.config.secret)
        self._running = True

        logger.info(f"[{self.name}] Starting QQ Bot gateway connection")

        while self._running:
            try:
                await self._connect_gateway()
            except Exception as e:
                logger.error(f"[{self.name}] Gateway error: {e}")

            if self._running:
                await asyncio.sleep(5)

    async def _connect_gateway(self) -> None:
        """连接 WebSocket 网关。"""
        if not self._api:
            return

        # 获取网关 URL
        try:
            gateway_url, shards, session_limit = await self._api.get_gateway_bot_url()
            logger.info(f"[{self.name}] Gateway URL: {gateway_url}, shards: {shards}")
        except Exception as e:
            logger.error(f"[{self.name}] Failed to get gateway URL: {e}")
            gateway_url = GATEWAY_URL

        # 计算 intents
        intents = INTENT_LEVELS[min(self._intent_level_index, len(INTENT_LEVELS) - 1)]["intents"]
        intent_name = INTENT_LEVELS[min(self._intent_level_index, len(INTENT_LEVELS) - 1)]["name"]
        logger.info(f"[{self.name}] Using intent level: {intent_name}")

        # WebSocket URL
        ws_url = f"{gateway_url}?v=2&intent={intents}"

        # 如果有保存的 session，尝试 resume
        if self._session_state and self._session_state.session_id:
            ws_url += f"&resume=true"

        try:
            async with ws_connect(ws_url, close_timeout=10, max_size=10 * 1024 * 1024) as ws:
                self._ws = ws
                logger.info(f"[{self.name}] WebSocket connected")

                # 监听消息
                await self._ws_message_loop()

        except websockets.ConnectionClosed as e:
            logger.warning(f"[{self.name}] WebSocket closed: {e.code} {e.reason}")
            self._ws = None
            raise
        except Exception as e:
            logger.error(f"[{self.name}] WebSocket error: {e}")
            self._ws = None
            raise

    async def _ws_message_loop(self) -> None:
        """WebSocket 消息接收循环。"""
        if not self._ws:
            return

        buffer = bytearray()

        async for message in self._ws:
            if not self._running:
                break

            # 处理 zlib 压缩
            if isinstance(message, bytes):
                if message[-4:] == b'\x00\x00\xff\xff':
                    buffer.extend(message[:-4])
                    continue
                else:
                    buffer.extend(message)
                    try:
                        decompressed = zlib.decompress(buffer, -15)
                        payload = json.loads(decompressed.decode('utf-8'))
                        buffer.clear()
                    except Exception:
                        logger.error(f"[{self.name}] Failed to decompress message")
                        buffer.clear()
                        continue
            else:
                try:
                    payload = json.loads(message)
                except json.JSONDecodeError:
                    logger.error(f"[{self.name}] Invalid JSON payload")
                    continue

            # 处理 payload
            await self._handle_payload(payload)

    async def _handle_payload(self, payload: dict) -> None:
        """处理 WebSocket payload。"""
        op = payload.get("op", 0)
        data = payload.get("d", {})
        t = payload.get("t")
        s = payload.get("s", 0)

        # 更新 seq
        if s > 0:
            if self._session_state:
                self._session_state.last_seq = s
            else:
                self._session_state = SessionState(last_seq=s)

        if op == 0:  # Dispatch
            await self._handle_dispatch(t, data)
        elif op == 7:  # Reconnect
            logger.warning(f"[{self.name}] Received reconnect request")
            await self._reconnect()
        elif op == 9:  # Invalid Session
            logger.error(f"[{self.name}] Invalid session")
            await self._identify()
        elif op == 10:  # Hello
            self._heartbeat_interval = data.get("heartbeat_interval", 45000) / 1000
            logger.info(f"[{self.name}] Hello, heartbeat interval: {self._heartbeat_interval}s")
            await self._identify()
            await self._start_heartbeat()
        elif op == 11:  # Heartbeat ACK
            logger.debug(f"[{self.name}] Heartbeat ACK received")

    async def _handle_dispatch(self, event_type: str, data: dict) -> None:
        """处理 Dispatch 事件。"""
        if event_type == "READY":
            self._reconnect_attempts = 0
            session_id = data.get("session_id", "")
            user = data.get("user", {})

            if self._session_state:
                self._session_state.session_id = session_id
            else:
                self._session_state = SessionState(session_id=session_id)

            logger.info(f"[{self.name}] Ready! Session: {session_id[:16]}..., User: {user.get('username', 'unknown')}")

        elif event_type == "RESUMED":
            logger.info(f"[{self.name}] Session resumed successfully")

        elif event_type == "C2C_MESSAGE_CREATE":
            await self._handle_c2c_message(data)

        elif event_type == "GROUP_AT_MESSAGE_CREATE":
            await self._handle_group_message(data)

    async def _handle_c2c_message(self, data: dict) -> None:
        """处理 C2C 消息。"""
        msg_id = data.get("id", "")
        openid = data.get("author", {}).get("user_openid", "")
        content = data.get("content", "").strip()
        timestamp = data.get("timestamp", "")

        if not content or not openid:
            return

        # 去重
        if msg_id in self._processed_ids:
            return
        self._processed_ids.append(msg_id)

        # 发送输入通知
        try:
            await self._api.send_c2c_input_notify(openid, msg_id)
        except Exception as e:
            logger.debug(f"[{self.name}] Failed to send input notify: {e}")

        # 转发到消息总线
        await self._handle_message(
            sender_id=openid,
            chat_id=openid,
            content=content,
            metadata={"message_id": msg_id, "timestamp": timestamp},
        )

    async def _handle_group_message(self, data: dict) -> None:
        """处理群消息。"""
        msg_id = data.get("id", "")
        group_openid = data.get("group_openid", "")
        content = data.get("content", "").strip()
        timestamp = data.get("timestamp", "")

        if not content or not group_openid:
            return

        # 去重
        if msg_id in self._processed_ids:
            return
        self._processed_ids.append(msg_id)

        # 转发到消息总线
        await self._handle_message(
            sender_id=group_openid,
            chat_id=f"group:{group_openid}",
            content=content,
            metadata={"message_id": msg_id, "timestamp": timestamp},
        )

    async def _identify(self) -> None:
        """发送 Identify 或 Resume。"""
        if not self._ws or not self._api:
            return

        token = await self._api.get_access_token()

        identify_payload = {
            "op": 2,  # Identify
            "d": {
                "token": f"QQBot {token}",
                "intents": INTENT_LEVELS[min(self._intent_level_index, len(INTENT_LEVELS) - 1)]["intents"],
                "shard": [0, 1],  # 单分片
                "properties": {
                    "os": "linux",
                    "browser": "iflow-bot",
                    "device": "iflow-bot",
                },
            },
        }

        # 如果有 session，尝试 resume
        if self._session_state and self._session_state.session_id:
            identify_payload["d"]["resume"] = True
            identify_payload["d"]["session_id"] = self._session_state.session_id
            identify_payload["d"]["seq"] = self._session_state.last_seq

        await self._ws.send(json.dumps(identify_payload))
        logger.info(f"[{self.name}] Identify sent")

    async def _start_heartbeat(self) -> None:
        """启动心跳循环。"""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()

        async def heartbeat_loop():
            while self._running and self._ws:
                try:
                    seq = self._session_state.last_seq if self._session_state else 0
                    await self._ws.send(json.dumps({"op": 1, "d": seq}))
                    logger.debug(f"[{self.name}] Heartbeat sent, seq={seq}")
                except Exception as e:
                    logger.error(f"[{self.name}] Failed to send heartbeat: {e}")
                    break

                await asyncio.sleep(self._heartbeat_interval)

        self._heartbeat_task = asyncio.create_task(heartbeat_loop())

    async def _reconnect(self) -> None:
        """重连。"""
        self._reconnect_attempts += 1

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None

        if self._ws:
            await self._ws.close()
            self._ws = None

        delay = min(60, 2 ** self._reconnect_attempts)
        logger.info(f"[{self.name}] Reconnecting in {delay}s (attempt {self._reconnect_attempts})")
        await asyncio.sleep(delay)

    async def stop(self) -> None:
        """停止 QQ Bot。"""
        self._running = False

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None

        if self._api:
            await self._api.close()
            self._api = None

        if self._ws:
            await self._ws.close()
            self._ws = None

        logger.info(f"[{self.name}] QQ bot stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """发送 QQ 消息。"""
        if not self._api:
            logger.warning(f"[{self.name}] API not initialized")
            return

        chat_id = msg.chat_id
        content = msg.content
        # 获取回复的消息 ID（用于被动回复）
        reply_to_id = msg.metadata.get("reply_to_id") or msg.metadata.get("message_id")

        # 消息分块
        max_len = 2000
        chunks = self._chunk_message(content, max_len)

        for i, chunk in enumerate(chunks):
            msg_seq = i + 1
            try:
                if chat_id.startswith("group:"):
                    group_openid = chat_id[6:]
                    await self._api.send_group_message(
                        group_openid=group_openid,
                        content=chunk,
                        msg_seq=msg_seq,
                        msg_id=reply_to_id,  # 被动回复需要
                    )
                else:
                    await self._api.send_c2c_message(
                        openid=chat_id,
                        content=chunk,
                        msg_seq=msg_seq,
                        msg_id=reply_to_id,  # 被动回复需要
                    )
                logger.debug(f"[{self.name}] Message chunk {i+1}/{len(chunks)} sent to {chat_id}")
            except Exception as e:
                logger.error(f"[{self.name}] Error sending message: {e}")

    def _chunk_message(self, text: str, limit: int = 2000) -> list[str]:
        """分块长消息。"""
        if len(text) <= limit:
            return [text]

        chunks = []
        remaining = text

        while remaining:
            if len(remaining) <= limit:
                chunks.append(remaining)
                break

            # 尝试在换行处分割
            split_at = remaining.rfind("\n", 0, limit)
            if split_at < 0 or split_at < limit * 0.5:
                split_at = remaining.rfind(" ", 0, limit)
            if split_at < 0:
                split_at = limit

            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:].lstrip()

        return chunks
