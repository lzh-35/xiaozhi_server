# XiaoZhi 语音问答 API — 部署指南

> FastAPI REST API 服务，支持文本 / 语音 / 图片三模问答，SSE 流式输出。

---

## 系统架构

```
客户端 (浏览器 / Postman / curl / App)
       │
       │  HTTP (REST)
       ▼
┌──────────────────────────────────────────┐
│         api_server.py  (FastAPI :8080)    │
│                                           │
│  POST /ask/text      文本问答 (SSE流式)   │
│  POST /ask/voice     语音问答 (ASR→LLM)   │
│  POST /ask/voice/stream 流式语音          │
│  POST /ask/vision    图片问答 (VLLM)      │
│  GET  /ask/audio/    语音下载              │
│  GET  /health        健康检查              │
└──────────┬───────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────┐
│           QAPipeline (核心管道)            │
│                                           │
│  Memory → 对话 → LLM → 工具执行 → TTS    │
└──┬──────┬──────┬──────┬──────────────────┘
   │      │      │      │
   ▼      ▼      ▼      ▼
┌─────┐┌─────┐┌─────┐┌────────┐
│ ASR ││ LLM ││ TTS ││Memory  │
│FunASR│DeepSeek│豆包 ││本地文件│
└─────┘└─────┘└─────┘└────────┘
   │      │      │      │
   ▼      ▼      ▼      ▼
┌──────────────────────────────────────────┐
│         外部 API 服务                      │
│  DeepSeek API  │  豆包 TTS  │  GLM VLLM  │
└──────────────────────────────────────────┘
```

---

## 环境要求

| 项目 | 要求 |
|------|------|
| Python | 3.10+ |
| 内存 | 2 GB（FunASR 本地模型需 ~500MB） |
| 磁盘 | 2 GB（含 SenseVoiceSmall 模型 ~200MB） |
| 网络 | 需访问 DeepSeek / 豆包 / 智谱 API |

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
pip install fastapi uvicorn python-multipart jinja2
```

### 2. 配置

编辑 `data/.config.yaml`，至少配置一个 LLM 的 API key：

```yaml
LLM:
  DeepSeekLLM:
    api_key: sk-your-key-here
```

完整配置项参考 `data/.config.yaml`。

### 3. 启动

```bash
python api_server.py
```

输出：
```
╔══════════════════════════════════════╗
║  XiaoZhi 语音问答 API Server         ║
║  Swagger:  http://0.0.0.0:8080/docs  ║
║  健康检查: http://0.0.0.0:8080/health║
╚══════════════════════════════════════╝
```

### 4. 验证

```bash
# 健康检查
curl http://localhost:8080/health

# 文本问答（流式）
curl -X POST http://localhost:8080/ask/text \
  -H "Content-Type: application/json" \
  -d '{"text":"你好"}'
```

---

## 技术栈

| 模块 | 引擎 | 说明 |
|------|------|------|
| ASR | FunASR (SenseVoiceSmall) | 本地模型，免费 |
| LLM | DeepSeek (deepseek-chat) | 付费，效果好 |
| LLM 备用 | ChatGLM (glm-4-flash) | 免费 |
| TTS | 豆包 TTS (火山引擎) | 付费，台湾女声 |
| TTS 备用 | EdgeTTS | 免费，微软接口 |
| VLLM | 智谱 glm-4v-flash | 免费视觉模型 |
| Memory | mem_local_short | 本地文件存储 |
| Tools | web_search / get_weather / get_news / get_lunar | |

---

## 配置说明

所有配置集中在 `data/.config.yaml`，修改后服务自动热加载。

### 切换 LLM

```yaml
selected_module:
  LLM: DeepSeekLLM    # 改为 ChatGLMLLM 使用免费模型
```

### 切换 TTS

```yaml
selected_module:
  TTS: EdgeTTS        # 改为 EdgeTTS 使用免费 TTS
```

### 自定义 Prompt

```yaml
prompt: |
  你是一个专业的客服助手...
```

---

## 文件结构

```
xiaozhi_server/
├── api_server.py          # FastAPI 入口
├── api/                   # API 层
│   ├── routes.py          # 路由定义
│   ├── schemas.py         # 数据模型
│   └── dependencies.py    # 依赖注入
├── core/                  # 核心逻辑
│   ├── qa_pipeline.py     # 问答管道
│   ├── tool_handler.py    # 工具处理器
│   ├── providers/         # Provider 层 (ASR/LLM/TTS/VLLM/Memory)
│   └── utils/             # 工具函数
├── plugins_func/          # 工具插件
├── config/                # 配置加载
├── data/                  # 配置 + 数据
│   ├── .config.yaml       # 主配置文件
│   ├── .memory.yaml       # 记忆存储
│   └── .agent-base-prompt.txt  # Prompt 模板
└── docs/                  # 文档
    ├── api.md             # 接口文档
    ├── deployment-guide.md # 部署指南（本文件）
    └── postman_collection.json  # Postman 集合
```

---

## API 速查

```bash
# 文本问答（SSE 流式，默认）
curl -X POST http://localhost:8080/ask/text \
  -H "Content-Type: application/json" \
  -d '{"text":"你好"}'

# 文本问答 + TTS 语音
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
  -F "image=@photo.png" -F "question=描述这张图片"

# 图片问答 + TTS
curl -X POST http://localhost:8080/ask/vision \
  -F "image=@photo.png" -F "voice_output=true"
```

---

## 常见问题

**Q: 首次启动为什么慢？**
A: FunASR 加载 SenseVoiceSmall 模型需要 ~10 秒，后续请求秒回。

**Q: 如何查看详细日志？**
A: `data/.config.yaml` 中 `log.log_level: DEBUG`。

**Q: 支持并发吗？**
A: 支持。FastAPI 异步处理，本地 FunASR 模型受 GIL 限制，高并发建议用云端 ASR。
