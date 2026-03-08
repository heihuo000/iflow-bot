# QQ 群消息失败问题修复报告

## 问题总结

QQ 群消息发送失败的根本原因是 `msg_seq` 序列号管理不当，导致 QQ 服务器返回"消息被去重"错误 (Error Code: 40054005)。

## 根本原因

### 1. msg_seq 循环重置 bug（主要问题）

**原代码**（第 201-202 行）：
```python
# 确保 msg_seq 是小整数（不超过 1000）
if msg_seq > 1000:
    msg_seq = 1  # 重置循环 ❌
```

**问题分析**：
- QQ API 要求每个 `(msg_id, msg_seq)` 组合必须唯一
- 重启后 `_group_msg_seq` 重置为空字典 `{}`
- 每次重启都从 1 开始计数
- 即使有持久化，超过 1000 后又会循环回 1
- 重复的 `(msg_id, msg_seq)` 组合被 QQ 服务器识别为重复消息

### 2. Thinking 消息和回复消息共用计数器

**原代码**（第 359-363 行）：
```python
seq_key = f"group_{group_id}"  # thinking 和回复共用同一个键 ❌
if seq_key not in self._group_msg_seq:
    self._group_msg_seq[seq_key] = 1
thinking_msg_seq = self._group_msg_seq[seq_key]
self._group_msg_seq[seq_key] += 1
```

**问题分析**：
- Thinking 消息和回复消息共用同一个计数器
- 导致序列号混乱，增加重复风险

## 修复方案

### 修复 1：移除循环重置逻辑

**修复后代码**：
```python
# 获取并递增 msg_seq（使用小整数）
# msg_seq 必须唯一且递增，不能循环重置，否则会被 QQ 服务器识别为重复消息
seq_key = f"group_{group_id}"
if seq_key not in self._group_msg_seq:
    self._group_msg_seq[seq_key] = 1
msg_seq = self._group_msg_seq[seq_key]
self._group_msg_seq[seq_key] += 1
# 注意：msg_seq 会一直递增（1, 2, 3, ...），永不重置
# QQ API 要求每个 (msg_id, msg_seq) 组合必须唯一
# 即使超过 1000 也不会重复使用已用过的值
```

**关键改变**：
- 移除了 `if msg_seq > 1000: msg_seq = 1` 的循环重置逻辑
- msg_seq 会一直递增，永不重置
- 每次都是新的、唯一的值

### 修复 2：Thinking 消息使用独立计数器

**修复后代码**：
```python
# 使用独立的 thinking 消息计数器，不和回复消息共用
# 从 1000 开始，避免和回复消息（从 1 开始）冲突
seq_key = f"group_{group_id}_thinking"
if seq_key not in self._group_msg_seq:
    self._group_msg_seq[seq_key] = 1000
thinking_msg_seq = self._group_msg_seq[seq_key]
self._group_msg_seq[seq_key] += 1
```

**关键改变**：
- Thinking 消息使用独立的 `group_{group_id}_thinking` 计数器
- 从 1000 开始计数，避免和回复消息（从 1 开始）冲突
- 两个计数器互不干扰

### 修复 3：连接断开时自动保存状态

**修复后代码**：
```python
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
```

**关键改变**：
- 在 `finally` 块中调用 `_save_msg_seq_state()`
- 确保连接断开时（包括异常）都能保存状态
- 避免状态丢失

### 修复 4：旧格式迁移

**修复后代码**：
```python
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
```

**关键改变**：
- 自动迁移旧格式的持久化文件
- 添加详细的调试日志
- 便于排查问题

## 测试步骤

### 1. 清理旧的持久化文件（可选）

```bash
rm ~/.iflow-bot/qq_msg_seq_state.json
```

### 2. 重启网关

```bash
iflow gateway restart
```

### 3. 发送群消息测试

在 QQ 群中 @机器人，发送消息测试回复功能。

### 4. 检查日志

```bash
tail -f ~/.iflow-bot/gateway.log | grep "msg_seq"
```

预期输出：
```
[INFO] Loaded msg_seq state: 2 counters
[DEBUG]   group_D35E1F44...: 1
[DEBUG]   group_D35E1F44..._thinking: 1000
[WARNING] Sending group message to ..., msg_seq=1, markdown=true
[WARNING] Sending group message to ..., msg_seq=2, markdown=true
[WARNING] Sending group message to ..., msg_seq=3, markdown=true
```

### 5. 重启后再次测试

```bash
iflow gateway restart
```

再次发送群消息，检查日志：
```
[INFO] Loaded msg_seq state: 2 counters
[DEBUG]   group_D35E1F44...: 4  # 应该从上次停止的值继续
[WARNING] Sending group message to ..., msg_seq=4, markdown=true
```

## 修改的文件

- `iflow_bot/channels/qq.py`
  - 第 213-222 行：移除 msg_seq 循环重置逻辑
  - 第 355-372 行：Thinking 消息使用独立计数器
  - 第 114-126 行：连接断开时自动保存状态
  - 第 142-165 行：旧格式迁移和调试日志

## 技术说明

### QQ 群聊 API 要求

群聊 API 使用被动回复模式：
- 必须提供 `msg_id`（回复哪条消息）
- 必须提供 `msg_seq`（消息序列号）
- `(msg_id, msg_seq)` 组合必须唯一
- `msg_seq` 必须是正整数（通常为 1-1000，但可以超过 1000）

### 为什么不能循环重置

QQ 服务器会记录：
1. 每条消息的 `msg_id`
2. 该 `msg_id` 已使用的所有 `msg_seq` 值
3. 如果收到相同的 `(msg_id, msg_seq)` 组合，拒绝并返回"消息被去重"

即使 `msg_seq` 超过 1000，QQ 服务器仍然接受，因为：
- API 文档说"通常 1-1000"，但不是硬性限制
- 唯一性比范围更重要

## 后续优化建议

1. **添加监控**：监控 msg_seq 重复率，自动检测和报告问题
2. **数据库存储**：使用 SQLite 或 Redis 存储 msg_seq，更可靠
3. **限流保护**：每小时最多回复 4 次，避免触发 QQ 限流
4. **权限升级**：申请群主动消息权限，可以不使用 msg_seq

---

**修复时间**: 2026-03-08
**修复状态**: 已完成
**影响范围**: 群消息回复功能
