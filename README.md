# XiaoZhi 语音问答 AICRM 系统

独立的语音交互 AICRM 系统，从 XiaoZhi ESP32 Server 解耦重构。

**语音交互 · LLM 对话 · CRM 用户画像 · RAG 知识库 · 工具调用**

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置
cp data/config.example.yaml data/.config.yaml
# 编辑 data/.config.yaml，填入 API key

# 3. 下载 ASR 模型（首次运行需要）
# 从 modelscope 下载 SenseVoiceSmall 模型到 models/SenseVoiceSmall/
mkdir -p models/SenseVoiceSmall

# 4. 启动
python api_server.py
```

浏览器打开 `http://localhost:8080/docs` 查看 Swagger 交互文档。

## API 端点

### 问答接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/ask/text` | 文本问答（SSE 流式 / JSON 非流式） |
| `POST` | `/ask/voice` | 语音问答（上传 WAV → ASR → LLM → 可选 TTS） |
| `POST` | `/ask/voice/stream` | 流式语音（SSE: ASR→LLM 逐字→TTS 逐块） |
| `POST` | `/ask/vision` | 图片问答（上传图片 → VLLM 分析） |
| `GET` | `/ask/audio/{filename}` | 下载 TTS 合成语音 |

### CRM 用户管理接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/crm/health` | CRM 健康检查 |
| `POST` | `/crm/users` | 创建/更新用户（含标签和画像） |
| `GET` | `/crm/users/{user_id}` | 查询用户完整档案（画像 + 对话历史） |
| `GET` | `/crm/users/{user_id}/conversations` | 查询用户对话历史 |
| `GET` | `/crm/knowledge` | RAG 知识库索引状态 |
| `POST` | `/crm/knowledge/reload` | 强制重建知识库向量索引 |

### 系统接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 服务健康检查 |
| `GET` | `/api.md` | API 文档 (Markdown) |

## 技术栈

| 模块 | 引擎 | 说明 |
|------|------|------|
| Web 框架 | FastAPI + Uvicorn | REST API + SSE 流式 |
| ASR | FunASR (SenseVoiceSmall) | 本地模型，支持语种/情绪识别 |
| LLM | DeepSeek / ChatGLM | OpenAI 兼容 API，支持 function calling |
| TTS | 豆包 TTS / EdgeTTS | 流式 + 非流式语音合成 |
| VLLM | 智谱 glm-4v-flash | 图片视觉分析 |
| Memory | 本地文件 + LLM 叙事总结 | 跨会话记忆持久化 |
| CRM | SQLite + LLM 智能画像提取 | 用户管理闭环 |
| RAG | LangChain + ChromaDB | DashScope text-embedding-v4 |
| Tools | 天气 / 新闻 / 搜索 / 农历 / 知识库 | LLM function calling 自动调用 |

## 项目结构

```
xiaozhi_server/
├── api_server.py              # FastAPI 入口
├── api/                       # API 层
│   ├── routes.py              # /ask 问答路由
│   ├── routes_crm.py          # /crm 用户管理路由
│   ├── schemas.py             # 请求/响应 Pydantic 模型
│   └── dependencies.py        # Provider 单例 + Pipeline 工厂
├── core/
│   ├── qa_pipeline.py         # 核心问答管道 (ASR→LLM→TTS→CRM)
│   ├── tool_handler.py        # 工具调度器
│   ├── providers/             # Provider 抽象层
│   │   ├── asr/               # FunASR 语音识别
│   │   ├── llm/openai/        # DeepSeek/ChatGLM 大模型
│   │   ├── tts/               # 豆包/Edge 语音合成
│   │   ├── vllm/              # 智谱 视觉模型
│   │   ├── memory/            # 叙事记忆系统
│   │   └── crm/crm_sqlite/    # SQLite 用户画像
│   └── utils/                 # 工具 (RAG/提示词/对话/缓存)
├── plugins_func/functions/    # 工具插件
│   ├── get_weather.py         # 天气查询
│   ├── get_news_from_newsnow.py  # 新闻
│   ├── web_search.py          # 联网搜索
│   ├── get_time.py            # 农历查询
│   └── search_knowledge_base.py  # RAG 知识库检索
├── config/                    # 配置 + 日志
├── data/                      # 配置文件/数据库/知识库文档
└── docs/                      # 项目文档
```

## 文档

| 文档 | 说明 |
|------|------|
| [CRM 说明文档](docs/crm-guide.md) | CRM 架构/API/数据库/画像提取 |
| [项目说明文档](docs/project-summary.md) | 系统架构/技术栈/部署/数据流 |
| [测试记录](docs/test-report.md) | 全接口测试用例及结果（21 项全部通过） |
| [学习路线](docs/learning-guide.md) | 5 天从入门到掌握 |

## 特性

- **Provider 模式** — ASR/LLM/TTS 通过配置文件切换，支持热替换
- **多模态输入** — 文本 / 语音 / 图片统一会话入口，共享 session_id
- **SSE 流式** — LLM 逐字 + TTS 逐块实时推送
- **Function Calling** — LLM 自动调用天气/新闻/搜索/农历/知识库工具
- **CRM 闭环** — 对话自动记录 → LLM 提取画像 → 下次注入个性化上下文
- **RAG 知识库** — 文档向量化检索，LLM 引用知识库回答问题
- **Memory 记忆** — 跨会话叙事摘要，支持长期记忆
