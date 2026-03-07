# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

QQ Bot Channel Plugin for OpenClaw - QQ 开放平台 Bot API 的 OpenClaw 渠道插件。

## 构建与运行

```bash
# 安装依赖
npm install

# 构建 (TypeScript -> JavaScript)
npm run build

# 开发模式 (监听编译)
npm run dev

# 安装插件到 OpenClaw
openclaw plugins install .

# 配置 QQBot 通道
openclaw config set channels.qqbot.appId "你的 AppID"
openclaw config set channels.qqbot.clientSecret "你的 AppSecret"
openclaw config set channels.qqbot.enabled true

# 启动网关
openclaw gateway
```

## 架构结构

```
qqbot/
├── index.ts              # 插件入口，导出插件定义和公共 API
├── src/
│   ├── channel.ts        # Channel 插件核心实现 (onboarding/config/setup/outbound/gateway)
│   ├── gateway.ts        # WebSocket 网关，处理 QQ Bot API 长连接和事件订阅
│   ├── outbound.ts       # 出站消息发送 (文本/媒体/图片/Silk 语音)
│   ├── api.ts            # QQ Bot REST API 封装
│   ├── config.ts         # 配置解析与账户管理
│   ├── types.ts          # TypeScript 类型定义
│   ├── runtime.ts        # 运行时状态管理
│   ├── session-store.ts  # 会话存储
│   ├── onboarding.ts     # CLI 向导适配
│   ├── known-users.ts    # 已知用户管理
│   ├── image-server.ts   # 图床服务器
│   ├── proactive.ts      # 主动消息推送
│   └── utils/            # 工具函数
├── skills/
│   ├── qqbot-cron/       # 定时任务技能
│   └── qqbot-media/      # 媒体处理技能
├── bin/
│   └── qqbot-cli.js      # CLI 工具
└── scripts/
    └── upgrade.sh        # 升级脚本
```

## 核心模块说明

### channel.ts
实现 OpenClaw Channel 插件接口，包含：
- `onboarding`: CLI 配置向导
- `config`: 账户配置解析（支持多账户、环境变量、密钥文件）
- `setup`: 账户初始化和凭证验证
- `outbound`: 消息发送（支持文本分块，限制 2000 字符）
- `gateway`: WebSocket 连接管理
- `messaging`: 目标地址解析（支持 `qqbot:c2c:openid`、`qqbot:group:groupid`、`qqbot:channel:channelid`）

### gateway.ts
实现 QQ Bot WebSocket 网关：
- 长连接事件订阅机制
- 心跳保活 (Heartbeat)
- 消息事件处理 (C2C/群聊/频道)
- 音频格式转换 (SILK ↔ WAV)

### outbound.ts
消息发送模块：
- 文本消息（自动分块）
- 媒体消息（图片/文件）
- 语音消息（TTS，OpenAI 兼容 API）
- Markdown 消息支持

### config.ts
配置管理：
- 支持多账户配置 (`channels.qqbot.accounts`)
- 支持密钥文件 (`clientSecretFile`)
- 支持环境变量 (`QQBOT_CLIENT_SECRET`)
- 默认账户 ID: `default`

## 音频格式策略

```typescript
interface AudioFormatPolicy {
  sttDirectFormats?: string[];     // STT 可直接处理的格式（跳过 SILK→WAV）
  uploadDirectFormats?: string[];  // QQ 平台支持直传的格式（跳过→SILK）
}
```

## 技能 (Skills)

- **qqbot-cron**: 定时任务管理（CRON 表达式调度）
- **qqbot-media**: 媒体消息处理（图片上传、下载）

## 配置文件结构

```json
{
  "channels": {
    "qqbot": {
      "enabled": true,
      "appId": "你的 AppID",
      "clientSecret": "你的 AppSecret",
      "accounts": {
        "default": {
          "appId": "...",
          "clientSecret": "..."
        }
      },
      "tts": {
        "provider": "openai",
        "model": "tts-1",
        "voice": "alloy"
      }
    }
  }
}
```
