# XiaoZhi 语音问答 API

独立的语音问答 REST API 服务，从 XiaoZhi ESP32 Server 解耦而来。

支持 **文本 / 语音 / 图片** 三模输入，**SSE 流式输出**，**Memory 记忆**，**Tools 工具调用**，**跨模态统一会话**。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt fastapi uvicorn python-multipart jinja2

# 2. 配置
cp data/config.example.yaml data/.config.yaml
# 编辑 data/.config.yaml，填入你的 API key

# 3. 下载 ASR 模型
mkdir -p models/SenseVoiceSmall
# 下载模型文件到 models/SenseVoiceSmall/
# 下载链接为：https://modelscope.cn/models/iic/SenseVoiceSmall/resolve/master/model.pt

# 4. 启动
python api_server.py
```

浏览器打开 `http://localhost:8080/docs` 查看 Swagger 文档。

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/ask/text` | 文本问答（SSE 流式 / JSON 非流式） |
| POST | `/ask/voice` | 语音问答（上传 WAV → ASR → LLM → TTS） |
| POST | `/ask/voice/stream` | 流式语音（SSE 推送 ASR→LLM→TTS） |
| POST | `/ask/vision` | 图片问答（上传图片 → VLLM 分析） |
| GET | `/ask/audio/{filename}` | 下载 TTS 语音 |
| GET | `/crm/users/{user_id}` | 查询用户画像 + 对话历史 |
| POST | `/crm/users` | 创建/更新 CRM 用户 |
| GET | `/crm/knowledge` | RAG 知识库状态 |
| GET | `/health` | 健康检查 |

## 技术栈

| 模块 | 引擎 |
|------|------|
| ASR | FunASR (SenseVoiceSmall) |
| LLM | DeepSeek / ChatGLM |
| TTS | 豆包 TTS / EdgeTTS |
| VLLM | 智谱 glm-4v-flash |
| Memory | 本地文件 + LLM 叙事总结 |
| CRM | SQLite 用户画像 + LLM 智能提取 |
| RAG | LangChain + ChromaDB + DashScope text-embedding-v4 |
| Tools | 天气 / 新闻 / 搜索 / 农历 / 知识库检索 |

## 项目结构

```
api_server.py          # FastAPI 入口
api/                   # API 层 (路由/模型/依赖注入)
core/
├── qa_pipeline.py     # 核心问答管道
├── tool_handler.py    # 工具处理器
├── providers/
│   ├── asr/           # ASR Provider (FunASR)
│   ├── llm/           # LLM Provider (DeepSeek/ChatGLM)
│   ├── tts/           # TTS Provider (豆包/Edge)
│   ├── vllm/          # VLLM Provider (智谱)
│   ├── memory/        # Memory Provider (叙事记忆)
│   └── crm/           # CRM Provider (用户画像)
└── utils/             # 工具函数 (RAG/提示词/对话管理)
plugins_func/          # 工具插件 (天气/新闻/搜索/RAG检索)
config/                # 配置加载
data/                  # 配置文件 + 知识库文档 + 数据库
docs/                  # 文档
```

## 文档

- [接口文档](docs/api.md)
- [部署指南](docs/deployment-guide.md)
- [Postman 集合](docs/postman_collection.json)

## 致谢

本项目基于 [XiaoZhi ESP32 Server](https://github.com/xinnan-tech/xiaozhi-esp32-server) 解耦重构，感谢原项目提供的 Provider 架构设计和多引擎支持。
