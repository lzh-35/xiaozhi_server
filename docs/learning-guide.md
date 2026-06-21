# XiaoZhi 语音问答 AICRM — 学习路线

> 5 天拿下整个项目。跟着数据流走，一次只看一层。

---

## 项目是干嘛的

```
你说话 → 手机录音 → 发到服务器 → ASR 转文字 → LLM 思考 → TTS 转语音 → 播给你听
同时自动: 记录对话 → 提取用户画像 → 存入 CRM → 下次个性化回复
```

拆成 REST API，核心接口：

| 接口 | 输入 | 输出 | 场景 |
|------|------|------|------|
| `POST /ask/text` | 文字 | 文字（+语音） | 打字聊天 |
| `POST /ask/voice` | 音频文件 | 文字（+语音） | 语音消息 |
| `POST /ask/voice/stream` | 音频文件 | SSE 流（逐字+逐块音频） | 实时语音对话 |
| `POST /ask/vision` | 图片 | 文字（+语音） | 拍照问问题 |
| `GET /ask/audio/{filename}` | 文件名 | wav 文件 | 下载合成的语音 |

CRM 管理接口：`/crm/users`、`/crm/knowledge` 等 6 个。

---

## Day 1：门面层 — 请求怎么进来，响应怎么出去

**阅读时长：** 30-45 分钟

### 1.1 先跑起来

```bash
cd /home/chen/projects/xiaozhi_server
python api_server.py
```

浏览器打开 **http://localhost:8080/docs**，在 Swagger 里直接点 "Try it out" 发请求。

### 1.2 入口：`api_server.py`（228 行）

**阅读顺序：**

1. 启动检查：切工作目录、自动生成配置文件、恢复提示词模板
2. `FastAPI(...)` 应用创建 + CORS 中间件
3. `app.include_router(ask_router)` + `app.include_router(crm_router)` — 挂载路由
4. 后台线程：每 10 分钟清理旧音频文件 + RAG 知识库预加载
5. 启动入口：`uvicorn.run(...)` 带热重载

**关键认知：** `api_server.py` 只做启动和配置，不处理任何业务逻辑。它像一个"插线板"。

### 1.3 请求/响应模型：`api/schemas.py`

用 Pydantic 定义，FastAPI 自动校验、自动生成 Swagger 文档：

```
AskTextRequest  → { text, voice_output, session_id, stream, user_id }
AskResponse     → { code, message, text, asr_text, audio_url, session_id }
CRM 相关模型     → CRMUserProfile / CRMConversationItem 等
```

### 1.4 路由：`api/routes.py` + `api/routes_crm.py`

**不逐行读，先看结构：**

`api/routes.py` — 核心问答路由（/ask）：
`api/routes_crm.py` — CRM 管理路由（/crm）

**每个接口做的事一模一样：**
```
1. 从请求中取参数
2. get_pipeline(session_id) → 拿到 pipeline 实例
3. 调 pipeline 的方法干活
4. 把结果包装成响应返回
```

### 1.5 依赖注入：`api/dependencies.py`

**Provider 单例 + Pipeline 工厂：**

```
get_config()   ─┐
get_llm()      ─┤
get_asr()      ─┼── @lru_cache(maxsize=1) 缓存，进程内只创建一次
get_tts()      ─┤
get_crm()      ─┘

get_memory()   ─── 每次新建（不同 session 记忆隔离）

get_pipeline() ─── 每次请求新建 Pipeline，注入上面的单例
```

**为什么这样设计？**
- LLM/ASR/TTS 创建开销大（加载模型、建立连接），全局复用
- Pipeline 包含对话状态（dialogue），每次请求独立
- Memory 不同 session 不能共享

**Day 1 自测：**
- [ ] 能说出核心接口的输入输出
- [ ] 流式 vs 非流式的代码路径区别
- [ ] `run_in_executor` 是干嘛的
- [ ] `get_pipeline()` 每次调用但 LLM 只创建一次，怎么做到的

---

## Day 2：核心管道 — LLM 怎么思考的

**阅读时长：** 1-1.5 小时

### 2.1 类图（心里有个地图）

```
QAPipeline (~804 行)
├── ask_text()          ★ 文本入口 → 调 ask_text_stream() 取最终结果
├── ask_text_stream()   ★ 流式文本：查记忆→LLM→存记忆→存CRM
├── ask_voice()         语音：ASR → ask_text() → 可选 TTS
├── ask_voice_stream()  流式语音：ASR → LLM流式 → TTS流式
├── ask_vision()        图片：VLLM 分析 + 记忆/CRM
│
├── _chat_simple() / _chat_simple_stream()  简单 LLM 对话
├── _chat_with_tools() / _chat_with_tools_stream()  带工具调用
├── _handle_tool_calls()     执行工具 → 可能递归调 LLM
│
├── _query_memory() / _save_memory()   记忆系统
├── _save_to_crm() / _get_user_profile()  CRM 闭环
└── _speech_to_text() / _text_to_speech()   ASR / TTS 辅助
```

### 2.2 从最简单路径开始：`ask_text()`

```python
def ask_text(self, question: str) -> str:
    for event in self.ask_text_stream(question):   # ← 直接调 stream 版
        if event.get("done"):
            return event.get("text", "")
```

**设计模式：非流式 = 对流式的包装。** 遍历流式生成器，丢弃中间的 token，只取最后 done。

### 2.3 核心流程：`ask_text_stream()`

```
用户问题
  → ① _query_memory()  查历史记忆
  → ② dialogue.put()  写入对话历史
  → ③ _chat_with_tools_stream()  调 LLM（可能调工具）
  → ④ _save_memory()  后台存记忆（异步）
  → ⑤ _save_to_crm()  存对话记录 + LLM 提取画像（异步）
  → 返回回复
```

### 2.4 对话管理：`core/utils/dialogue.py`

`Dialogue.get_llm_dialogue_with_memory()` 构建发给 LLM 的 messages：

```json
[
  {"role": "system", "content": "你是小智..."},      ← 静态角色
  {"role": "system", "content": "时间:14:30..."},     ← 动态上下文
  {"role": "user", "content": "今天天气怎么样"},
  {"role": "assistant", "content": "让我查一下..."},
  {"role": "tool", "tool_call_id": "xxx", "content": "晴天 25°C"},
  {"role": "assistant", "content": "今天晴天，25度！"}
]
```

### 2.5 工具调用流程

```
LLM 收到问题
  ├── "我知道答案" → 返回文字 ✓
  └── "我需要查天气" → 返回 function_call
        └── 执行 get_weather("亳州")
              ├── 工具直接回复 → 返回 ✓
              └── 工具返回数据，需 LLM 总结 → 递归调 _chat_with_tools
```

**Day 2 自测：**
- [ ] `ask_text()` 和 `ask_text_stream()` 的关系
- [ ] `ask_text_stream()` 分几步
- [ ] LLM 调工具 → 执行 → 返回后，代码路径怎么走

---

## Day 3：Provider 层 — 可插拔的外部服务

**阅读时长：** 1 小时

### 3.1 Provider 模式

每个能力定义一个抽象基类，从配置文件切换实现：

```
core/providers/
├── llm/
│   ├── base.py         ← LLMProviderBase
│   └── openai/openai.py ← 调 DeepSeek/ChatGLM（OpenAI 兼容）
├── asr/
│   ├── base.py（198行） ← ASRProviderBase（精简后）
│   └── fun_local.py    ← FunASR 本地模型
├── tts/
│   ├── base.py（140行） ← TTSProviderBase（精简后）
│   ├── doubao.py       ← 火山引擎豆包 TTS
│   └── edge.py         ← Edge TTS（免费）
├── memory/
│   ├── base.py         ← MemoryProviderBase
│   └── mem_local_short/ ← 本地文件 + LLM 叙事总结
├── crm/
│   ├── base.py         ← CRMProviderBase
│   └── crm_sqlite/     ← SQLite 用户画像
└── vllm/
    ├── base.py         ← VLLMProviderBase
    └── openai.py       ← 智谱 glm-4v-flash
```

**好处：** 想换 LLM？改配置文件就行。想加新的 TTS？写个子类就行。

### 3.2 LLM Provider

`core/providers/llm/openai/openai.py` — 核心只是往 OpenAI 兼容 API 发 HTTP。

```python
class OpenAILLM(LLMProviderBase):
    def response(self, session_id, dialogue):        # 流式
    def response_with_functions(self, ...):          # 带 function calling
    def response_no_stream(self, ...):               # 非流式（后台任务）
```

### 3.3 ASR：语音转文字

`core/providers/asr/fun_local.py` — 本地 FunASR SenseVoiceSmall。  
返回带标签的文本：`<|zh|><|HAPPY|>今天天气真好`

`core/providers/asr/utils.py` 里的 `lang_tag_filter()` 负责解析标签。

### 3.4 TTS：文字转语音

所有 TTS 都实现 `text_to_speak(text, output_file)`。流式版额外实现 `text_to_speak_stream(text)`。

### 3.5 Memory：记忆系统

```
对话历史 → LLM 叙事总结 → 存 data/.memory.yaml → 下次注入上下文
```

**Day 3 自测：**
- [ ] Provider 模式的好处
- [ ] 把 DeepSeek 换成 GPT-4，改哪里
- [ ] 记忆系统存了什么、取的时候怎么用

---

## Day 4：工具和插件 — LLM 怎么"动手"

**阅读时长：** 45 分钟

### 4.1 插件注册

```python
@register_function("get_weather", GET_WEATHER_FUNCTION_DESC, ToolType.SYSTEM_CTL)
def get_weather(conn, location=None, lang="zh_CN"):
    ...
```

- 函数存入全局 `all_function_registry`
- 函数描述（OpenAI function calling schema）告诉 LLM 工具签名
- `ToolType` 决定执行时是否传入 context

### 4.2 工具处理器：`core/tool_handler.py`

```
get_functions()  → 从配置读启用的工具列表 → 从 registry 取出描述 → 返回给 LLM
handle_llm_function_call() → LLM 说"调 get_weather(亳州)" → 执行并返回
```

### 4.3 当前可用的工具

| 工具 | 文件 | 作用 |
|------|------|------|
| `get_weather` | `get_weather.py` | 查天气（qweather API） |
| `get_news_from_newsnow` | `get_news_from_newsnow.py` | 查新闻（newsnow API） |
| `web_search` | `web_search.py` | 联网搜索（Tavily/秘塔） |
| `get_lunar` | `get_time.py` | 查农历 |
| `search_knowledge_base` | `search_knowledge_base.py` | RAG 知识库检索 |

**Day 4 自测：**
- [ ] 想加新工具（比如查快递），需要改哪几个文件
- [ ] `Action.RESPONSE` 和 `Action.REQLLM` 的区别
- [ ] LLM 怎么知道有哪些工具可用

---

## Day 5：配置、CRM、RAG 和辅助模块

**阅读时长：** 30 分钟

### 5.1 配置：`config/config_loader.py`（79 行）

从 `data/.config.yaml` 读 YAML → dict，带缓存。自动创建输出目录。

### 5.2 提示词管理：`core/utils/prompt_manager.py`

```
data/.agent-base-prompt.txt (Jinja2 模板)
  + data/.config.yaml 的 prompt (角色设定)
  + 当前时间/日期/农历（实时注入）
  = 最终 system prompt → 发给 LLM
```

### 5.3 CRM：用户画像闭环

```
对话结束 → save_conversation() 存对话记录
         → LLM 提取画像（身份/兴趣/意图/情感）
         → update_user_from_conversation() 增量合并到 profile
下次对话 → get_user_profile() 读取画像 → 注入 system prompt → 个性化回复
```

详见 `docs/crm-guide.md`。

### 5.4 RAG：知识库检索

```
文档(PDF/TXT/MD) → langchain 加载 → 分块 → DashScope 向量化 → 存入 ChromaDB
用户提问 → 向量检索 → 相关文档片段 → 注入 LLM 上下文 → 引用知识库回答
```

### 5.5 项目文件树总览

```
xiaozhi_server/
├── api_server.py              ← FastAPI 入口
├── api/
│   ├── routes.py              ← /ask 问答接口
│   ├── routes_crm.py          ← /crm 用户管理接口
│   ├── schemas.py             ← 请求/响应 Pydantic 模型
│   └── dependencies.py        ← Provider 单例 + Pipeline 工厂
├── core/
│   ├── qa_pipeline.py         ← 核心管道（最重要，~804 行）
│   ├── tool_handler.py        ← 工具调度器
│   ├── providers/
│   │   ├── llm/openai/        ← DeepSeek/ChatGLM
│   │   ├── asr/               ← FunASR（base 精简至 198 行）
│   │   ├── tts/               ← 豆包/Edge（base 精简至 140 行）
│   │   ├── vllm/              ← 智谱视觉模型
│   │   ├── memory/mem_local_short/  ← 叙事记忆
│   │   └── crm/crm_sqlite/    ← SQLite 用户画像
│   └── utils/
│       ├── prompt_manager.py  ← 提示词模板渲染
│       ├── dialogue.py        ← 对话历史管理
│       ├── util.py（8行）     ← check_model_key（精简后）
│       └── rag.py             ← RAG 知识库管理器
├── plugins_func/functions/    ← 工具插件（5个）
├── config/                    ← 配置 + 日志
├── data/                      ← 配置/数据库/知识库文档
└── docs/                      ← 项目文档（4份）
```

**Day 5 自测：**
- [ ] 提示词模板的 `{{today_date}}` 最终变成什么，谁负责替换
- [ ] CRM 闭环：对话→画像→个性化 的完整链路
- [ ] RAG：文档→向量→检索→回答 的完整链路

---

## 防困秘诀

1. **带着问题看代码。** "我想知道天气工具是怎么被调用的" → 搜 `get_weather` → 跟调用链

2. **加 print 调试。** `print(f">>> ask_text 被调用，question={question[:50]}")` → 跑请求看终端

3. **画调用链。** 从 routes 接口 → pipeline → LLM API，拿张纸画箭头

4. **改配置看效果。** 改角色 prompt、换 TTS、改工具列表，看效果立竿见影

5. **一次只看一层。** routes 是门卫，pipeline 是大脑，providers 是手脚。看一层时其他都是黑盒

---

## 动手练习

**Day 1：** Swagger 里发 `/ask/text`，找 `stream=True` vs `stream=False` 的代码分支

**Day 2：** 在 `ask_text_stream()` 加 print，用同一 session_id 发两条消息观察 dialogue

**Day 3：** 把 LLM 从 DeepSeek 换成 ChatGLM（改 `selected_module.LLM`），重启验证

**Day 4：** 跟踪"问天气"的完整调用链：routes → pipeline → LLM → tool_handler → get_weather

**Day 5：** 改 `data/.agent-base-prompt.txt`，把角色从"小智"改成"大学教授"，看效果
