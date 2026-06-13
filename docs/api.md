# XiaoZhi 语音问答 API 文档

> REST API 服务，支持文本 / 语音 / 图片三模输入，SSE 流式输出。

## 基础信息

| 项目 | 说明 |
|------|------|
| Base URL | `http://localhost:8080` |
| Content-Type | `application/json`（文本）/ `multipart/form-data`（语音/图片） |
| 在线文档 | `http://localhost:8080/docs`（Swagger UI） |

---

## 接口列表

### 1. 健康检查

```
GET /health
```

```json
{"status": "ok", "version": "0.1.0"}
```

---

### 2. 文本问答

```
POST /ask/text
Content-Type: application/json
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| text | string | 是 | 用户输入文本 |
| voice_output | boolean | 否 | 是否返回 TTS 合成语音 |
| session_id | string | 否 | 会话 ID（空=新会话，已有 ID=继续对话） |
| stream | boolean | 否 | 是否 SSE 流式输出（默认开启） |

**流式响应（stream=true）：**
```
data: {"token": "你"}
data: {"token": "好"}
...
data: {"done": true, "text": "你好世界", "session_id": "xxx"}
```

**非流式响应（stream=false）：**
```json
{
    "code": 0,
    "message": "ok",
    "text": "哈喽～你好哇！我是小智啦！",
    "audio_url": "/ask/audio/abc123.wav",
    "asr_text": null,
    "session_id": "xxx"
}
```

---

### 3. 语音问答

```
POST /ask/voice
Content-Type: multipart/form-data
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| audio | file | 是 | WAV 音频文件（16kHz 单声道推荐） |
| voice_output | boolean | 否 | 是否返回 TTS 语音 |
| session_id | string | 否 | 会话 ID（空=新会话，已有 ID=继续对话） |

---

### 4. 流式语音问答

```
POST /ask/voice/stream
Content-Type: multipart/form-data
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| audio | file | 是 | WAV 音频文件 |
| session_id | string | 否 | 会话 ID（空=新会话） |

SSE 事件格式：`asr` → `token`（LLM逐字） → `text_done` → `audio`（TTS逐块） → `done`（含 session_id）

---

### 5. 图片问答

```
POST /ask/vision
Content-Type: multipart/form-data
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| image | file | 是 | 图片文件（JPEG/PNG） |
| question | string | 否 | 关于图片的问题（默认"描述这张图片"） |
| voice_output | boolean | 否 | 是否返回 TTS 语音 |
| session_id | string | 否 | 会话 ID（空=新会话） |

---

### 6. 音频下载

```
GET /ask/audio/{filename}
```

---

## 错误码

| code | 说明 |
|------|------|
| 0 | 成功 |
| 1 | ASR 未能识别 |
| 400 | 请求参数错误 |
| 404 | 音频文件不存在 |
| 500 | 服务器内部错误 |

---

## curl 示例

```bash
# 流式文本（默认）
curl -X POST http://localhost:8080/ask/text \
  -H "Content-Type: application/json" \
  -d '{"text":"你好"}'

# 非流式 + TTS
curl -X POST http://localhost:8080/ask/text \
  -H "Content-Type: application/json" \
  -d '{"text":"早安","stream":false,"voice_output":true}'

# 语音问答
curl -X POST http://localhost:8080/ask/voice \
  -F "audio=@question.wav"

# 流式语音
curl -X POST http://localhost:8080/ask/voice/stream \
  -F "audio=@question.wav"

# 图片问答
curl -X POST http://localhost:8080/ask/vision \
  -F "image=@photo.png" \
  -F "question=描述这张图片"

# 多轮对话
curl -X POST http://localhost:8080/ask/text \
  -H "Content-Type: application/json" \
  -d '{"text":"继续","session_id":"上次返回的session_id"}'
```
