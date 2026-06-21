# XiaoZhi 语音问答 AICRM — API 文档

## 问答接口

### `POST /ask/text` — 文本问答

**请求：**
```json
{
  "text": "今天天气怎么样",
  "user_id": "",
  "voice_output": false,
  "session_id": "",
  "stream": true
}
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| text | string | ✅ | 用户输入文本 (1-10000 字符) |
| user_id | string | | 用户标识（用于 CRM 画像） |
| voice_output | bool | | 是否同时返回 TTS 语音 |
| session_id | string | | 会话 ID（空=新会话） |
| stream | bool | | SSE 流式输出（默认 true） |

**响应（非流式）：**
```json
{
  "code": 0,
  "message": "ok",
  "text": "亳州今天多云，31°C...",
  "asr_text": null,
  "audio_url": null,
  "session_id": "abc123"
}
```

**响应（流式 SSE）：**
```
data: {"token":"今"}
data: {"token":"天"}
data: {"done":true,"text":"今天天气...","session_id":"abc123"}
```

---

### `POST /ask/voice` — 语音问答

上传 WAV 音频文件（16kHz 单声道推荐），经 ASR 识别后由 LLM 回复。

**请求：** `multipart/form-data`

| 参数 | 类型 | 说明 |
|------|------|------|
| audio | file | WAV 音频文件 |
| voice_output | bool | 是否返回 TTS 语音 |
| session_id | string | 会话 ID |
| user_id | string | 用户标识 |

**响应：**
```json
{
  "code": 0,
  "message": "ok",
  "text": "LLM 回复文本",
  "asr_text": "ASR 识别的文本",
  "audio_url": "/ask/audio/xxx.wav",
  "session_id": "abc123"
}
```

---

### `POST /ask/voice/stream` — 流式语音问答

上传 WAV 音频，SSE 流式返回。

**SSE 事件类型：**

| type | 说明 |
|------|------|
| `asr` | ASR 识别完成，`text` 字段为识别文本 |
| `token` | LLM 逐字输出，`data` 字段为单个字符 |
| `text_done` | LLM 文本完成 |
| `audio` | TTS 音频块（base64 编码） |
| `done` | 流结束，包含 `session_id` |

---

### `POST /ask/vision` — 图片问答

**请求：** `multipart/form-data`

| 参数 | 类型 | 说明 |
|------|------|------|
| image | file | 图片文件 (JPEG/PNG) |
| question | string | 关于图片的问题（可选） |
| session_id | string | 会话 ID |
| user_id | string | 用户标识 |

---

### `GET /ask/audio/{filename}` — 下载 TTS 语音

下载由 `/ask/text` 或 `/ask/voice` 生成的语音文件。

---

## CRM 接口

### `GET /crm/health`
CRM 健康检查。

### `POST /crm/users`
创建/更新用户。

**请求：**
```json
{
  "user_id": "13800138000",
  "name": "张三",
  "phone": "13800138000",
  "tags": ["VIP", "科技爱好者"],
  "profile": {"preferences": "扫地机器人"}
}
```

### `GET /crm/users/{user_id}`
查询用户完整档案（画像 + 最近 20 条对话历史）。

### `GET /crm/users/{user_id}/conversations?limit=20`
查询用户对话历史（正序）。

### `GET /crm/knowledge`
RAG 知识库索引状态（文档块数、向量模型等）。

### `POST /crm/knowledge/reload`
强制重建知识库向量索引。

---

## 系统接口

### `GET /health`
服务健康检查。

### `GET /api.md`
返回本文档。
