# XiaoZhi 语音问答 API — 项目说明文档

## 一、项目概述

XiaoZhi 语音问答 API 是一个独立的语音交互 AICRM 系统，从 ESP32 WebSocket 服务解耦而来。提供 REST API 接口，支持**文本问答**、**语音问答**、**图片分析**，集成 **CRM 用户画像管理**和 **RAG 知识库检索**。

### 核心能力

- 🎤 **语音→文字** — FunASR 本地语音识别（SenseVoiceSmall）
- 🧠 **智能对话** — DeepSeek / ChatGLM 大模型
- 🔊 **文字→语音** — 火山引擎豆包 TTS / Edge TTS
- 📷 **图片分析** — 智谱 glm-4v-flash 视觉理解
- 👤 **用户画像** — AICRM：SQLite + LLM 自动画像提取
- 📚 **知识库** — RAG：LangChain + ChromaDB 向量检索
- 🔧 **工具调用** — 天气/新闻/搜索/农历/知识库检索

---

## 二、系统架构

```
┌────────────────────────────────────────────────────────────┐
│                      客户端 (HTTP/SSE)                       │
└──────────────────────────┬─────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│                   api_server.py (FastAPI)                    │
│                                                              │
│  /ask/text    /ask/voice    /ask/vision    /crm/*           │
└──────────────────────────┬─────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│                    QAPipeline (核心管道)                      │
│                                                              │
│  ask_text() → ask_text_stream() →                           │
│    _query_memory() → _chat_with_tools() →                   │
│    _handle_tool_calls() → _save_memory() → _save_to_crm()  │
└──────┬──────────┬──────────┬──────────┬───────────────────┘
       │          │          │          │
       ▼          ▼          ▼          ▼
┌──────────┐ ┌──────┐ ┌──────┐ ┌──────────┐
│   ASR    │ │ LLM  │ │ TTS  │ │   CRM    │
│ FunASR   │ │DeepSeek│ │Doubao│ │ SQLite   │
└──────────┘ └──────┘ └──────┘ └──────────┘
       │          │          │          │
       ▼          ▼          ▼          ▼
┌──────────────────────────────────────────────────────────┐
│                    Provider 抽象层                          │
│  ASRProviderBase / LLMProviderBase / TTSProviderBase /    │
│  CRMProviderBase / MemoryProviderBase                     │
└──────────────────────────────────────────────────────────┘
```

---

## 三、技术栈

| 模块 | 引擎 | 说明 |
|------|------|------|
| **Web 框架** | FastAPI + Uvicorn | REST API + SSE 流式 |
| **ASR** | FunASR (SenseVoiceSmall) | 本地模型，支持情绪识别 |
| **LLM** | DeepSeek-V4 / ChatGLM-4 | OpenAI 兼容 API |
| **TTS** | 豆包 TTS / Edge TTS | 流式 + 非流式 |
| **VLLM** | 智谱 glm-4v-flash | 图片视觉分析 |
| **Memory** | 本地 YAML + LLM 摘要 | 跨会话记忆 |
| **CRM** | SQLite + LLM 画像提取 | 用户管理闭环 |
| **RAG** | LangChain + ChromaDB | DashScope text-embedding-v4 |
| **Tools** | qweather / newsnow / Tavily / cnlunar | 天气/新闻/搜索/农历 |

---

## 四、项目结构

```
xiaozhi_server/
├── api_server.py              # FastAPI 入口
├── api/
│   ├── routes.py              # /ask 问答接口
│   ├── routes_crm.py          # /crm 用户管理接口
│   ├── schemas.py             # 请求/响应模型
│   └── dependencies.py        # Provider 单例 + Pipeline 工厂
├── core/
│   ├── qa_pipeline.py         # 核心管道（ASR→LLM→TTS→CRM）
│   ├── tool_handler.py        # 工具调度器
│   └── providers/
│       ├── asr/               # 语音识别
│       ├── llm/openai/        # 大模型
│       ├── tts/               # 语音合成
│       ├── memory/mem_local_short/  # 记忆
│       ├── crm/crm_sqlite/    # 客户管理
│       └── vllm/              # 视觉模型
├── plugins_func/functions/    # 工具函数
│   ├── get_weather.py         # 天气查询
│   ├── get_news_from_newsnow.py  # 新闻
│   ├── web_search.py          # 联网搜索
│   ├── get_time.py            # 农历
│   └── search_knowledge_base.py  # RAG 检索
├── config/
│   ├── config_loader.py       # 配置加载
│   └── logger.py              # 日志
├── data/
│   ├── .config.yaml           # 主配置
│   ├── .agent-base-prompt.txt # 提示词模板
│   ├── crm.db                 # CRM 数据库
│   ├── .memory.yaml           # 记忆持久化
│   └── knowledge_base/        # RAG 文档
└── docs/
    ├── crm-guide.md           # CRM 说明文档
    ├── project-summary.md     # 项目说明文档
    ├── test-report.md         # 测试记录
    └── learning-guide.md      # 学习路线
```

---

## 五、部署运行

### 环境要求

- Python 3.10+
- 内存 ≥ 4GB（FunASR 模型需要）
- 依赖安装：`pip install -r requirements.txt`

### 配置

```bash
cp data/config.example.yaml data/.config.yaml
# 编辑 data/.config.yaml，填入 API Key
```

### 启动

```bash
python api_server.py
# 或
uvicorn api_server:app --host 0.0.0.0 --port 8080 --reload
```

### 访问

- Swagger 文档：http://localhost:8080/docs
- 健康检查：http://localhost:8080/health

---

## 六、Provider 模式

所有外部能力通过 Provider 抽象层接入，支持热替换：

```python
# 配置文件中切换（不需要改代码）
selected_module:
  LLM: ChatGLMLLM     # 从 DeepSeekLLM 切换到 ChatGLM
  TTS: EdgeTTS        # 从 DoubaoTTS 切换到 EdgeTTS
```

每个 Provider 遵循统一接口：

```python
class ASRProviderBase(ABC):
    @abstractmethod
    async def speech_to_text(self, audio_data, session_id, ...): ...

class LLMProviderBase(ABC):
    def response(self, session_id, dialogue): ...         # 流式
    def response_with_functions(self, ...): ...           # 带 function calling
```

---

## 七、数据流

### 文本问答

```
用户文字 → QAPipeline.ask_text()
  → _query_memory()        查历史记忆
  → _chat_with_tools()     LLM 思考（可能调工具）
  → _save_memory()         保存记忆
  → _save_to_crm()         保存 CRM 记录 + 更新画像
  → 返回文本
```

### 语音问答

```
音频文件 → WAV→PCM 解码
  → ASR 语音识别（FunASR）
  → 同文本问答流程
  → (可选) TTS 合成语音
```

### 图片问答

```
图片 → base64 编码
  → VLLM 视觉分析（glm-4v-flash）
  → 保存到对话 + CRM
  → 返回文本
```

---

## 八、配置说明

主配置文件：`data/.config.yaml`

```yaml
selected_module:          # 模块选择
  ASR: FunASR
  LLM: DeepSeekLLM
  TTS: DoubaoTTS
  Memory: mem_local_short
  Intent: function_call
  VLLM: ChatGLMVLLM
  CRM: crm_sqlite

plugins:                  # 工具配置
  get_weather: {...}
  get_news_from_newsnow: {...}
  web_search: {...}

rag:                      # RAG 知识库
  dashscope_api_key: "sk-xxx"
  knowledge_dir: "data/knowledge_base"
  persist_dir: "data/chroma_db"
```
