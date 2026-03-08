"""QQ channel implementation using qq-botpy SDK.

使用 qq-botpy SDK 通过 WebSocket 连接 QQ 频道机器人。
支持 C2C 私聊消息、QQ 群消息、图片、语音富文本。
"""

import asyncio
import base64
import logging
import os
from collections import deque
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

import aiohttp

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

# QQ 媒体类型
class MediaType:
    IMAGE = "image"
    VOICE = "voice"
    FILE = "file"
    VIDEO = "video"


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
        self._media_cache: dict[str, dict] = {}  # 媒体文件信息缓存 (file_info)

        # AccessToken 缓存
        self._access_token: Optional[str] = None
        self._token_expires_at: int = 0

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

        # 加载持久化的 msg_seq 状态
        await self._load_msg_seq_state()

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
            finally:
                # 连接断开时保存 msg_seq 状态
                await self._save_msg_seq_state()
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
        
        # 保存 msg_seq 状态
        await self._save_msg_seq_state()
        
        logger.info(f"[{self.name}] QQ bot stopped")

    async def _load_msg_seq_state(self):
        """从文件加载 msg_seq 计数器状态"""
        state_file = Path.home() / ".iflow-bot" / "qq_msg_seq_state.json"
        try:
            if state_file.exists():
                import json
                with open(state_file, 'r', encoding='utf-8') as f:
                    loaded_data = json.load(f)

                # 迁移旧格式：如果加载的数据是纯数字字典，转换为新格式
                # 旧格式：{"D35E1F44...": 5} 直接存储群 ID
                # 新格式：{"group_D35E1F44...": 5, "group_D35E1F44..._thinking": 1005}
                self._group_msg_seq = {}
                for key, value in loaded_data.items():
                    if not key.startswith("group_"):
                        # 旧格式，转换为新格式
                        self._group_msg_seq[f"group_{key}"] = value
                        logger.info(f"[{self.name}] Migrated old seq key '{key}' -> 'group_{key}' = {value}")
                    else:
                        self._group_msg_seq[key] = value

                logger.info(f"[{self.name}] Loaded msg_seq state: {len(self._group_msg_seq)} counters")
                for k, v in self._group_msg_seq.items():
                    logger.debug(f"[{self.name}]   {k}: {v}")
            else:
                logger.info(f"[{self.name}] No msg_seq state file found, starting fresh")
        except Exception as e:
            logger.warning(f"[{self.name}] Failed to load msg_seq state: {e}")
            self._group_msg_seq = {}
    
    async def _save_msg_seq_state(self):
        """保存 msg_seq 计数器状态到文件"""
        state_file = Path.home() / ".iflow-bot" / "qq_msg_seq_state.json"
        try:
            state_file.parent.mkdir(parents=True, exist_ok=True)
            import json
            with open(state_file, 'w', encoding='utf-8') as f:
                json.dump(self._group_msg_seq, f, ensure_ascii=False, indent=2)
            logger.info(f"[{self.name}] Saved msg_seq state: {len(self._group_msg_seq)} groups")
        except Exception as e:
            logger.warning(f"[{self.name}] Failed to save msg_seq state: {e}")

    # ========== AccessToken 管理 ==========

    async def _get_access_token(self) -> str:
        """获取 AccessToken（带缓存）。"""
        if self._access_token and asyncio.get_event_loop().time() < self._token_expires_at:
            return self._access_token

        # 获取新 Token
        token_url = "https://bots.qq.com/app/getAppAccessToken"
        payload = {"appId": self.config.app_id, "clientSecret": self.config.secret}

        async with aiohttp.ClientSession() as session:
            async with session.post(token_url, json=payload) as resp:
                data = await resp.json()
                if not data.get("access_token"):
                    raise RuntimeError(f"Failed to get access_token: {data}")

                self._access_token = data["access_token"]
                # 提前 5 分钟过期
                expires_in = int(data.get("expires_in", 7200))
                self._token_expires_at = asyncio.get_event_loop().time() + expires_in - 300
                logger.debug(f"[{self.name}] AccessToken refreshed, expires in {expires_in}s")
                return self._access_token

    # ========== 媒体上传 API ==========

    async def _upload_c2c_media(
        self,
        access_token: str,
        openid: str,
        media_type: str,
        file_url: Optional[str] = None,
        file_data: Optional[str] = None,
        file_name: Optional[str] = None,
    ) -> dict:
        """上传 C2C 媒体文件。

        Args:
            access_token: API 访问令牌
            openid: 用户 openid
            media_type: 媒体类型 (image, voice, file, video)
            file_url: 公网 URL
            file_data: Base64 数据
            file_name: 文件名（文件类型需要）
        """
        api_url = f"https://api.sgroup.qq.com/v2/users/{openid}/c2c/files"
        headers = {"Authorization": f"QQBot {access_token}", "Content-Type": "application/json"}

        # 构建 payload
        payload = {"file_type": media_type}
        if file_url:
            payload["url"] = file_url
        elif file_data:
            payload["file_data"] = file_data
        if file_name:
            payload["file_name"] = file_name

        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, headers=headers, json=payload) as resp:
                result = await resp.json()
                if resp.status != 200:
                    raise RuntimeError(f"Upload C2C media failed: {result}")
                return result

    async def _upload_group_media(
        self,
        access_token: str,
        group_openid: str,
        media_type: str,
        file_url: Optional[str] = None,
        file_data: Optional[str] = None,
        file_name: Optional[str] = None,
    ) -> dict:
        """上传群媒体文件。

        Args:
            access_token: API 访问令牌
            group_openid: 群 openid
            media_type: 媒体类型 (image, voice, file, video)
            file_url: 公网 URL
            file_data: Base64 数据
            file_name: 文件名（文件类型需要）
        """
        api_url = f"https://api.sgroup.qq.com/v2/groups/{group_openid}/files"
        headers = {"Authorization": f"QQBot {access_token}", "Content-Type": "application/json"}

        payload = {"file_type": media_type}
        if file_url:
            payload["url"] = file_url
        elif file_data:
            payload["file_data"] = file_data
        if file_name:
            payload["file_name"] = file_name

        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, headers=headers, json=payload) as resp:
                result = await resp.json()
                if resp.status != 200:
                    raise RuntimeError(f"Upload group media failed: {result}")
                return result

    # ========== 媒体消息发送 API ==========

    async def _send_c2c_media_message(
        self,
        access_token: str,
        openid: str,
        file_info: str,
        msg_id: Optional[str] = None,
        content: Optional[str] = None,
        media_type: str = "image",
    ) -> dict:
        """发送 C2C 媒体消息。

        Args:
            access_token: API 访问令牌
            openid: 用户 openid
            file_info: 上传后返回的 file_info
            msg_id: 回复的消息 ID
            content: 附带的文本内容
            media_type: 媒体类型
        """
        api_url = f"https://api.sgroup.qq.com/v2/users/{openid}/messages"
        headers = {"Authorization": f"QQBot {access_token}", "Content-Type": "application/json"}

        payload = {
            "msg_type": 7,  # 富媒体消息
            "media": {"file_info": file_info},
        }
        if msg_id:
            payload["msg_id"] = msg_id
            payload["msg_seq"] = 1
        if content:
            payload["content"] = content

        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, headers=headers, json=payload) as resp:
                result = await resp.json()
                if resp.status not in (200, 202):
                    logger.error(f"Send C2C media message failed: {result}")
                return result

    async def _send_group_media_message(
        self,
        access_token: str,
        group_openid: str,
        file_info: str,
        msg_id: Optional[str] = None,
        msg_seq: int = 1,
        content: Optional[str] = None,
        media_type: str = "image",
    ) -> dict:
        """发送群媒体消息。

        Args:
            access_token: API 访问令牌
            group_openid: 群 openid
            file_info: 上传后返回的 file_info
            msg_id: 回复的消息 ID
            msg_seq: 消息序号
            content: 附带的文本内容
            media_type: 媒体类型
        """
        api_url = f"https://api.sgroup.qq.com/v2/groups/{group_openid}/messages"
        headers = {"Authorization": f"QQBot {access_token}", "Content-Type": "application/json"}

        payload = {
            "msg_type": 7,  # 富媒体消息
            "media": {"file_info": file_info},
            "msg_id": msg_id,
            "msg_seq": msg_seq,
        }
        if content:
            payload["content"] = content

        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, headers=headers, json=payload) as resp:
                result = await resp.json()
                if resp.status not in (200, 202):
                    logger.error(f"Send group media message failed: {result}")
                return result

    # ========== 富媒体发送封装 ==========

    async def _send_image(
        self,
        access_token: str,
        chat_id: str,
        image_url: str,
        msg_id: Optional[str] = None,
        msg_seq: Optional[int] = None,
        is_group: bool = False,
        content: Optional[str] = None,
    ) -> None:
        """发送图片消息。

        Args:
            access_token: API 访问令牌
            chat_id: 用户 openid 或群 openid
            image_url: 图片 URL 或 Base64 Data URL
            msg_id: 回复的消息 ID
            msg_seq: 群消息序号
            is_group: 是否群聊
            content: 附带的文本内容
        """
        try:
            # 检查是否是 Base64
            file_data = None
            file_url = None
            if image_url.startswith("data:"):
                # Base64: data:image/png;base64,xxxxx
                match = image_url.match(r'^data:([^;]+);base64,(.+)$')
                if match:
                    file_data = match.group(2)
                else:
                    file_data = image_url.split(",", 1)[1] if "," in image_url else image_url
            else:
                file_url = image_url

            # 上传
            if is_group:
                result = await self._upload_group_media(
                    access_token, chat_id, MediaType.IMAGE, file_url, file_data
                )
            else:
                result = await self._upload_c2c_media(
                    access_token, chat_id, MediaType.IMAGE, file_url, file_data
                )

            file_info = result.get("file_info", "")

            # 发送
            if is_group:
                await self._send_group_media_message(
                    access_token, chat_id, file_info, msg_id, msg_seq, content, MediaType.IMAGE
                )
            else:
                await self._send_c2c_media_message(
                    access_token, chat_id, file_info, msg_id, content, MediaType.IMAGE
                )

            logger.info(f"[{self.name}] Image sent to {chat_id}")
        except Exception as e:
            logger.error(f"[{self.name}] Failed to send image: {e}")
            # 降级发送文本
            if content:
                await self._send_text(access_token, chat_id, content, msg_id, msg_seq, is_group)

    async def _send_voice(
        self,
        access_token: str,
        chat_id: str,
        voice_data: str,
        msg_id: Optional[str] = None,
        msg_seq: Optional[int] = None,
        is_group: bool = False,
    ) -> None:
        """发送语音消息。

        Args:
            access_token: API 访问令牌
            chat_id: 用户 openid 或群 openid
            voice_data: Base64 编码的语音数据（SILK 格式）
            msg_id: 回复的消息 ID
            msg_seq: 群消息序号
            is_group: 是否群聊
        """
        try:
            if is_group:
                result = await self._upload_group_media(
                    access_token, chat_id, MediaType.VOICE, None, voice_data
                )
                await self._send_group_media_message(
                    access_token, chat_id, result.get("file_info", ""), msg_id, msg_seq, None, MediaType.VOICE
                )
            else:
                result = await self._upload_c2c_media(
                    access_token, chat_id, MediaType.VOICE, None, voice_data
                )
                await self._send_c2c_media_message(
                    access_token, chat_id, result.get("file_info", ""), msg_id, None, MediaType.VOICE
                )

            logger.info(f"[{self.name}] Voice sent to {chat_id}")
        except Exception as e:
            logger.error(f"[{self.name}] Failed to send voice: {e}")

    async def _send_text(
        self,
        access_token: str,
        chat_id: str,
        content: str,
        msg_id: Optional[str] = None,
        msg_seq: Optional[int] = None,
        is_group: bool = False,
    ) -> None:
        """发送纯文本消息（底层方法）。"""
        if is_group:
            api_url = f"https://api.sgroup.qq.com/v2/groups/{chat_id}/messages"
            payload = {
                "msg_type": 0,
                "content": content,
                "msg_id": msg_id,
                "msg_seq": msg_seq or 1,
            }
        else:
            api_url = f"https://api.sgroup.qq.com/v2/users/{chat_id}/messages"
            payload = {
                "msg_type": 0,
                "content": content,
            }
            if msg_id:
                payload["msg_id"] = msg_id
                payload["msg_seq"] = 1

        headers = {"Authorization": f"QQBot {access_token}", "Content-Type": "application/json"}
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, headers=headers, json=payload) as resp:
                if resp.status not in (200, 202):
                    logger.error(f"Send text message failed: {await resp.text()}")

    async def send(self, msg: OutboundMessage) -> None:
        """通过 QQ 发送消息。

        Args:
            msg: 出站消息对象
                - chat_id: 用户 openid 或群 ID
                - content: 消息内容
                - media: 媒体文件列表（图片、语音等）
                - metadata: 包含 group_id(群聊) 或 openid(私聊)
        """
        logger.debug(f"[{self.name}] send() called - chat_id={msg.chat_id}, content_len={len(msg.content)}, media_count={len(msg.media)}, metadata={msg.metadata}")

        if not self._client:
            logger.warning(f"[{self.name}] QQ client not initialized")
            return

        try:
            metadata = msg.metadata or {}
            content = msg.content
            media_files = msg.media or []
            is_group = metadata.get("is_group", False)
            group_id = metadata.get("group_id") if is_group else None
            msg_id = metadata.get("reply_to_id") or metadata.get("message_id")

            # 获取 AccessToken（用于媒体上传）
            access_token = await self._get_access_token() if media_files else None

            # 群聊 msg_seq 管理
            msg_seq = None
            if is_group and group_id:
                seq_key = f"group_{group_id}"
                if seq_key not in self._group_msg_seq:
                    self._group_msg_seq[seq_key] = 1
                msg_seq = self._group_msg_seq[seq_key]
                self._group_msg_seq[seq_key] += 1

            # 优先处理媒体消息（图片、语音等）
            if media_files:
                for media_path in media_files:
                    await self._send_media_file(
                        access_token=access_token,
                        chat_id=msg.chat_id,
                        media_path=media_path,
                        msg_id=msg_id,
                        msg_seq=msg_seq,
                        is_group=is_group,
                        content=content if media_path == media_files[0] else None,
                    )
                return

            # 纯文本/Markdown 消息
            if is_group:
                if self.config.markdown_support:
                    logger.debug(f"[{self.name}] Sending group Markdown to {group_id}, msg_seq={msg_seq}")
                    payload = {
                        "msg_type": 2,
                        "msg_id": msg_id,
                        "msg_seq": msg_seq,
                        "markdown": {"content": content}
                    }
                    from botpy.http import Route
                    route = Route("POST", f"/v2/groups/{group_id}/messages", group_openid=group_id)
                    await self._client.api._http.request(route, json=payload)
                else:
                    logger.debug(f"[{self.name}] Sending group text to {group_id}, msg_seq={msg_seq}")
                    await self._client.api.post_group_message(
                        group_openid=group_id,
                        msg_type=0,
                        msg_id=msg_id,
                        msg_seq=msg_seq,
                        content=content,
                    )
            else:
                # 私聊消息
                openid = msg.chat_id
                if self.config.markdown_support:
                    logger.debug(f"[{self.name}] Sending C2C Markdown to {openid}")
                    payload = {
                        "msg_type": 2,
                        "markdown": {"content": content}
                    }
                    c2c_msg_id = metadata.get("reply_to_id") or metadata.get("message_id")
                    if c2c_msg_id:
                        payload["msg_id"] = c2c_msg_id
                        payload["msg_seq"] = 1
                    from botpy.http import Route
                    route = Route("POST", f"/v2/users/{openid}/messages")
                    await self._client.api._http.request(route, json=payload)
                else:
                    logger.debug(f"[{self.name}] Sending C2C text to {openid}")
                    await self._client.api.post_c2c_message(
                        openid=openid,
                        msg_type=0,
                        content=content,
                    )

            logger.debug(f"[{self.name}] Message sent to {msg.chat_id}")
        except Exception as e:
            logger.error(f"[{self.name}] Error sending message: {e}")
            import traceback
            logger.debug(traceback.format_exc())

    async def _send_media_file(
        self,
        access_token: str,
        chat_id: str,
        media_path: str,
        msg_id: Optional[str] = None,
        msg_seq: Optional[int] = None,
        is_group: bool = False,
        content: Optional[str] = None,
    ) -> None:
        """发送媒体文件（图片、语音、文件等）。

        Args:
            access_token: API 访问令牌
            chat_id: 用户 openid 或群 openid
            media_path: 本地文件路径或 URL
            msg_id: 回复的消息 ID
            msg_seq: 群消息序号
            is_group: 是否群聊
            content: 附带的文本内容
        """
        try:
            # 判断文件类型
            lower_path = media_path.lower()
            if any(ext in lower_path for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"]):
                media_type = MediaType.IMAGE
            elif any(ext in lower_path for ext in [".amr", ".silk", ".slk", ".wav", ".mp3"]):
                media_type = MediaType.VOICE
            elif any(ext in lower_path for ext in [".mp4", ".avi", ".mov", ".mkv"]):
                media_type = MediaType.VIDEO
            else:
                media_type = MediaType.FILE

            # 读取文件为 Base64
            if media_path.startswith(("http://", "https://")):
                # URL 直接使用
                file_url = media_path
                file_data = None
            elif os.path.exists(media_path):
                # 本地文件读取为 Base64
                with open(media_path, "rb") as f:
                    file_data = base64.b64encode(f.read()).decode("utf-8")
                file_url = None
            else:
                logger.error(f"[{self.name}] Media file not found: {media_path}")
                return

            # 根据类型发送
            if media_type == MediaType.IMAGE:
                await self._send_image(
                    access_token, chat_id, file_url or f"data:image/jpeg;base64,{file_data}",
                    msg_id, msg_seq, is_group, content
                )
            elif media_type == MediaType.VOICE:
                await self._send_voice(access_token, chat_id, file_data, msg_id, msg_seq, is_group)
            elif media_type == MediaType.VIDEO:
                # TODO: 视频消息
                logger.warning(f"[{self.name}] Video sending not yet implemented, falling back to text")
                if content:
                    await self._send_text(access_token, chat_id, content, msg_id, msg_seq, is_group)
            else:
                # 文件类型
                file_name = os.path.basename(media_path)
                if is_group:
                    result = await self._upload_group_media(
                        access_token, chat_id, MediaType.FILE, file_url, file_data, file_name
                    )
                    await self._send_group_media_message(
                        access_token, chat_id, result.get("file_info", ""), msg_id, msg_seq, None, MediaType.FILE
                    )
                else:
                    result = await self._upload_c2c_media(
                        access_token, chat_id, MediaType.FILE, file_url, file_data, file_name
                    )
                    await self._send_c2c_media_message(
                        access_token, chat_id, result.get("file_info", ""), msg_id, None, MediaType.FILE
                    )

            logger.info(f"[{self.name}] Media sent: {media_path}")
        except Exception as e:
            logger.error(f"[{self.name}] Failed to send media: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            # 降级发送文本
            if content:
                await self._send_text(access_token, chat_id, content, msg_id, msg_seq, is_group)

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
                metadata={"is_group": False},
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

            # 发送 "Thinking..." 提示（被动回复模式）
            try:
                if self._client:
                    # 使用独立的 thinking 消息计数器，不和回复消息共用
                    # 从 1000 开始，避免和回复消息（从 1 开始）冲突
                    seq_key = f"group_{group_id}_thinking"
                    if seq_key not in self._group_msg_seq:
                        self._group_msg_seq[seq_key] = 1000
                    thinking_msg_seq = self._group_msg_seq[seq_key]
                    self._group_msg_seq[seq_key] += 1

                    await self._client.api.post_group_message(
                        group_openid=group_id,
                        msg_type=0,
                        content="🤔 Thinking...",
                        msg_id=data.id,
                        msg_seq=thinking_msg_seq,
                    )
            except Exception as e:
                logger.debug(f"[{self.name}] Failed to send thinking: {e}")

            # 转发到消息总线
            chat_id = f"group_{group_id}"
            await self._handle_message(
                sender_id=user_id,
                chat_id=chat_id,
                content=content,
                metadata={
                    "message_id": data.id,  # 保存消息ID用于回复
                    "is_group": True,
                    "group_id": group_id,
                    "username": username,
                },
            )

        except Exception:
            logger.exception(f"[{self.name}] Error handling group message")
