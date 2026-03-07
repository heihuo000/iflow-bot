"""QQ channel implementation using qq-botpy SDK.

使用 qq-botpy SDK 通过 WebSocket 连接 QQ 频道机器人。
支持 C2C 私聊消息和 QQ 群消息。
"""

import asyncio
import logging
from collections import deque
from typing import Any, Optional, TYPE_CHECKING

from iflow_bot.bus.events import OutboundMessage
from iflow_bot.bus.queue import MessageBus
from iflow_bot.channels.base import BaseChannel
from iflow_bot.channels.manager import register_channel
from iflow_bot.config.schema import QQConfig

try:
    import botpy
    from botpy.message import C2CMessage, GroupMessage
    QQ_AVAILABLE = True
except ImportError:
    QQ_AVAILABLE = False
    botpy = None  # type: ignore
    C2CMessage = None  # type: ignore
    GroupMessage = None  # type: ignore

if TYPE_CHECKING:
    from botpy.message import C2CMessage, GroupMessage


logger = logging.getLogger(__name__)


def _make_bot_class(channel: "QQChannel") -> Any:
    """创建绑定到指定 Channel 的 botpy.Client 子类。"""
    intents = botpy.Intents(public_messages=True, direct_message=True)

    class _Bot(botpy.Client):
        def __init__(self):
            super().__init__(intents=intents)

        async def on_ready(self):
            logger.info(f"[{channel.name}] QQ bot ready: {self.robot.name}")

        async def on_c2c_message_create(self, message: "C2CMessage"):
            await channel._on_c2c_message(message)

        async def on_group_at_message_create(self, message: "GroupMessage"):
            await channel._on_group_message(message)

    return _Bot


@register_channel("qq")
class QQChannel(BaseChannel):
    """QQ Channel - 使用 qq-botpy SDK 通过 WebSocket 连接。

    支持:
    - C2C 私聊消息
    - QQ 群 @机器人消息

    要求:
    - app_id: QQ 机器人 AppID
    - secret: QQ 机器人 Secret

    Attributes:
        name: 渠道名称 ("qq")
        config: QQ 配置对象
        bus: 消息总线实例
        _client: botpy Client 实例
        _processed_ids: 已处理消息 ID 队列 (去重)
        _group_msg_seq: 群消息序号计数器
    """

    name = "qq"

    def __init__(self, config: QQConfig, bus: MessageBus):
        """初始化 QQ Channel。

        Args:
            config: QQ 配置对象
            bus: 消息总线实例
        """
        super().__init__(config, bus)
        self.config: QQConfig = config
        self._client: Any = None
        self._processed_ids: deque = deque(maxlen=1000)
        self._group_msg_seq: dict[str, int] = {}  # 群消息序号计数器

    async def start(self) -> None:
        """启动 QQ Bot。"""
        if not QQ_AVAILABLE:
            logger.error(
                f"[{self.name}] QQ SDK not installed. Run: pip install qq-botpy"
            )
            return

        if not self.config.app_id or not self.config.secret:
            logger.error(f"[{self.name}] app_id and secret not configured")
            return

        self._running = True
        BotClass = _make_bot_class(self)
        self._client = BotClass()

        logger.info(f"[{self.name}] QQ bot started (C2C + Group)")
        await self._run_bot()

    async def _run_bot(self) -> None:
        """运行 Bot 连接，支持自动重连。"""
        while self._running:
            try:
                await self._client.start(
                    appid=self.config.app_id,
                    secret=self.config.secret
                )
            except Exception as e:
                logger.warning(f"[{self.name}] QQ bot error: {e}")
            if self._running:
                logger.info(f"[{self.name}] Reconnecting in 5 seconds...")
                await asyncio.sleep(5)

    async def stop(self) -> None:
        """停止 QQ Bot。"""
        self._running = False
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass
        logger.info(f"[{self.name}] QQ bot stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """通过 QQ 发送消息。

        Args:
            msg: 出站消息对象
                - chat_id: 用户 openid 或群 ID
                - content: 消息内容
                - metadata: 包含 group_id(群聊) 或 openid(私聊)
        """
        if not self._client:
            logger.warning(f"[{self.name}] QQ client not initialized")
            return

        try:
            metadata = msg.metadata or {}
            content = msg.content

            if metadata.get("is_group"):
                # 群聊消息 - 需要找到原始消息对象来回复
                group_id = metadata.get("group_id")
                msg_id = metadata.get("reply_to_id") or metadata.get("message_id")
                # 获取并递增 msg_seq（每个群独立计数）
                seq_key = f"group_{group_id}"
                if seq_key not in self._group_msg_seq:
                    self._group_msg_seq[seq_key] = 1
                msg_seq = self._group_msg_seq[seq_key]
                self._group_msg_seq[seq_key] += 1
                
                if self.config.markdown_support:
                    # Markdown 模式：使用底层 HTTP 客户端手动构建 payload
                    logger.debug(f"[{self.name}] Sending group message to {group_id}, msg_seq={msg_seq}, markdown=true")
                    logger.debug(f"[{self.name}] Content preview: {content[:100] if len(content) > 100 else content}")
                    try:
                        # 构建 payload，只包含必要字段（参考 qqbot-main）
                        payload = {
                            "msg_type": 2,
                            "msg_seq": msg_seq,
                            "markdown": {"content": content}
                        }
                        if msg_id:
                            payload["msg_id"] = msg_id
                        
                        # 使用底层 HTTP 客户端发送请求
                        from botpy.http import Route
                        route = Route("POST", f"/v2/groups/{group_id}/messages", group_openid=group_id)
                        await self._client.api._http.request(route, json=payload)
                    except Exception as e:
                        logger.error(f"[{self.name}] Error sending Markdown message: {e}")
                        raise
                else:
                    # 纯文本模式
                    logger.debug(f"[{self.name}] Sending group message to {group_id}, msg_seq={msg_seq}, markdown=false")
                    await self._client.api.post_group_message(
                        group_openid=group_id,
                        msg_type=0,  # 文本消息类型
                        msg_id=msg_id,
                        msg_seq=msg_seq,
                        content=content,
                    )
            else:
                # 私聊消息
                openid = msg.chat_id
                if self.config.markdown_support:
                    # Markdown 模式：使用底层 HTTP 客户端手动构建 payload
                    logger.debug(f"[{self.name}] Sending C2C message to {openid}, markdown=true")
                    try:
                        # 构建 payload，只包含必要字段
                        payload = {
                            "msg_type": 2,
                            "markdown": {"content": content}
                        }
                        # 私聊消息的 msg_id 和 msg_seq 从 metadata 获取
                        c2c_msg_id = metadata.get("reply_to_id") or metadata.get("message_id")
                        if c2c_msg_id:
                            payload["msg_id"] = c2c_msg_id
                            payload["msg_seq"] = 1  # 私聊消息的 msg_seq 从 1 开始
                        
                        # 使用底层 HTTP 客户端发送请求
                        from botpy.http import Route
                        route = Route("POST", f"/v2/users/{openid}/messages")
                        await self._client.api._http.request(route, json=payload)
                    except Exception as e:
                        logger.error(f"[{self.name}] Error sending Markdown message: {e}")
                        raise
                else:
                    # 纯文本模式
                    logger.debug(f"[{self.name}] Sending C2C message to {openid}, markdown=false")
                    await self._client.api.post_c2c_message(
                        openid=openid,
                        msg_type=0,
                        content=content,
                    )
            logger.debug(f"[{self.name}] Message sent to {msg.chat_id}")
        except Exception as e:
            logger.error(f"[{self.name}] Error sending message: {e}")

    async def _on_c2c_message(self, data: "C2CMessage") -> None:
        """处理来自 QQ 的 C2C 私聊消息。

        Args:
            data: QQ 消息对象
        """
        try:
            # 消息 ID 去重
            if data.id in self._processed_ids:
                return
            self._processed_ids.append(data.id)

            # 提取用户信息
            author = data.author
            user_id = str(
                getattr(author, 'id', None) or
                getattr(author, 'user_openid', 'unknown')
            )

            # 提取消息内容
            content = (data.content or "").strip()
            if not content:
                return

            # 先发送 "Thinking..." 提示（非阻塞，不影响主流程）
            try:
                if self._client:
                    await self._client.api.post_c2c_message(
                        openid=user_id,
                        msg_type=0,
                        content="🤔 Thinking...",
                    )
            except Exception as e:
                logger.debug(f"[{self.name}] Failed to send thinking: {e}")

            # 转发到消息总线
            await self._handle_message(
                sender_id=user_id,
                chat_id=user_id,  # 私聊：chat_id == user_id
                content=content,
                metadata={"message_id": data.id, "is_group": False},
            )

        except Exception:
            logger.exception(f"[{self.name}] Error handling C2C message")

    async def _on_group_message(self, data: "GroupMessage") -> None:
        """处理来自 QQ 群的 @机器人消息。

        Args:
            data: QQ 群消息对象
        """
        try:
            # 消息 ID 去重
            if data.id in self._processed_ids:
                return
            self._processed_ids.append(data.id)

            # 检查是否在允许的群列表中
            group_id = data.group_openid or ""
            if self.config.groups and group_id not in self.config.groups:
                logger.warning(f"[{self.name}] Message from unauthorized group: {group_id}")
                return

            # 提取用户信息
            author = data.author
            user_id = str(
                getattr(author, 'member_openid', None) or
                getattr(author, 'user_openid', 'unknown')
            )
            username = user_id

            # 提取消息内容
            content = (data.content or "").strip()
            if not content:
                return

            # 移除 @机器人 的部分
            bot_id = getattr(self._client.robot, 'id', '') if self._client else ''
            if bot_id:
                content = content.replace(f'<@!{bot_id}>', '').strip()
            if not content:
                return

            # 发送 "Thinking..." 提示（使用 API 发送，避免持有 data 对象引用）
            try:
                if self._client:
                    await self._client.api.post_group_message(
                        group_openid=group_id,
                        msg_type=0,
                        content="🤔 Thinking...",
                        msg_id=data.id,
                        msg_seq=1,
                    )
            except Exception as e:
                logger.debug(f"[{self.name}] Failed to send thinking: {e}")
            finally:
                # 确保 data 对象可以被垃圾回收
                del data

            # 转发到消息总线
            chat_id = f"group_{group_id}"
            await self._handle_message(
                sender_id=user_id,
                chat_id=chat_id,
                content=content,
                metadata={
                    "message_id": data.id,
                    "is_group": True,
                    "group_id": group_id,
                    "username": username,
                },
            )

        except Exception:
            logger.exception(f"[{self.name}] Error handling group message")
