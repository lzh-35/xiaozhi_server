# XiaoZhi 语音问答 API — 学习路线

> 5 天拿下整个项目。跟着数据流走，一次只看一层。

---

## 项目是干嘛的

```
你说话 → 手机录音 → 发到服务器 → ASR 转文字 → LLM 思考 → TTS 转语音 → 播给你听
```

拆成 REST API 就是 5 个接口：

| 接口 | 输入 | 输出 | 场景 |
|------|------|------|------|
| `POST /ask/text` | 文字 | 文字（+语音） | 打字聊天 |
| `POST /ask/voice` | 音频文件 | 文字（+语音） | 语音消息 |
| `POST /ask/voice/stream` | 音频文件 | SSE 流（逐字+逐块音频） | 实时语音对话 |
| `POST /ask/vision` | 图片 | 文字（+语音） | 拍照问问题 |
| `GET /ask/audio/{filename}` | 文件名 | wav 文件 | 下载合成的语音 |

---

## Day 1：门面层 — 请求怎么进来，响应怎么出去

**目标：** 能说清楚一个 HTTP 请求从头到尾经过了什么。

**阅读时长：** 30-45 分钟

### 1.1 先跑起来

```bash
cd /home/chen/projects/xiaozhi_server
python api_server.py
```

浏览器打开 **http://localhost:8080/docs**，在 Swagger 界面里直接点 "Try it out" 发请求。先感受一下输入输出，比读代码直观 10 倍。

### 1.2 入口：`api_server.py`

**阅读顺序：**

1. **第 17-38 行** — 启动检查：切工作目录、自动生成配置文件、恢复提示词模板
2. **第 52-79 行** — `FastAPI(...)` 应用创建：title、description、版本号
3. **第 82-88 行** — CORS 中间件（让浏览器能跨域访问）
4. **第 91 行** — `app.include_router(ask_router)` — 把 routes 挂到 app 上
5. **第 96-113 行** — 后台线程：每 10 分钟清理超过 1 小时的旧音频文件
6. **第 158-181 行** — 启动入口：`uvicorn.run(...)` 带热重载

**关键认知：** `api_server.py` 只做启动和配置，不处理任何业务逻辑。它像一个"插线板"，把各个模块接好然后通电。

### 1.3 请求/响应模型：`api/schemas.py`

这个文件定义"请求长什么样、响应长什么样"。

```
AskTextRequest  →  { text, voice_output, session_id, stream, user_id }
AskResponse     →  { code, message, text, asr_text, audio_url, session_id }
ErrorResponse   →  { code, message, detail }
CRM 相关模型     →  用户画像和对话记录的数据结构
```

用 Pydantic 定义，FastAPI 会自动校验请求格式、生成 Swagger 文档。你不需要手动写校验逻辑。

### 1.4 路由：`api/routes.py`

这是今天的重头戏。**不要逐行读，先看结构：**

```
/router 定义（第15行）
    ├── POST /ask/text          (第24行)  文本问答
    ├── POST /ask/voice         (第69行)  语音问答
    ├── POST /ask/voice/stream  (第122行) 流式语音
    ├── POST /ask/vision        (第155行) 图片问答
    ├── GET  /ask/audio/{fn}    (第207行) 下载音频
    └── 辅助函数（第230行）      _synthesize_and_save / _save_audio_bytes
```

**每个接口做的事情一模一样：**

```
1. 从请求中取参数
2. get_pipeline(session_id) → 拿到 pipeline 实例
3. 调 pipeline 的方法干活
4. 把结果包装成 AskResponse 返回
```

**重点看两个接口来理解模式：**

#### `/ask/text`（最简单的入口）

```python
async def ask_text(req: AskTextRequest):
    pipeline = get_pipeline(session_id=req.session_id, user_id=req.user_id)

    if req.stream:
        # 流式路径：返回 SSE，一个字一个字往外蹦
        async def generate():
            for event in pipeline.ask_text_stream(req.text):
                yield f"data: {json.dumps(event)}\n\n"
        return StreamingResponse(generate(), media_type="text/event-stream")

    # 非流式路径：等 LLM 想完了再返回
    text = await asyncio.get_running_loop().run_in_executor(
        None, pipeline.ask_text, req.text   # ← 为什么用 run_in_executor？
    )
    return AskResponse(code=0, text=text, session_id=pipeline.session_id)
```

**两个分支：**
- `stream=True`（默认）→ `StreamingResponse` + SSE 格式 → 逐字输出
- `stream=False` → `run_in_executor` → 线程池里跑同步代码 → 一次性返回

**为什么非流式要用 `run_in_executor`？** 因为 `pipeline.ask_text()` 是同步函数（里面会调 `requests`、`time.sleep` 等阻塞操作），如果在 async 函数里直接调用，会卡住整个事件循环，其他请求全部排队。`run_in_executor` 把它扔到线程池里，不挡路。

#### `/ask/voice/stream`（SSE 流式模式）

```python
async def ask_voice_stream(audio, session_id):
    pipeline = get_pipeline(session_id=session_id)
    audio_bytes = await audio.read()

    async def generate():
        async for event in pipeline.ask_voice_stream(audio_bytes):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
```

和上面一样，但 `pipeline.ask_voice_stream()` 返回的是**异步生成器**，所以用 `async for`。

**SSE 事件流大概长这样：**
```
data: {"type":"asr","text":"今天天气怎么样"}

data: {"type":"token","data":"今"}

data: {"type":"token","data":"天"}

data: {"type":"token","data":"天"}    ← 逐字蹦出来

...

data: {"type":"text_done","text":"今天天气不错..."}   ← LLM 完成

data: {"type":"audio","data":"<base64编码的音频块>"}  ← TTS 逐块

data: {"type":"done","session_id":"abc123"}           ← 结束
```

### 1.5 依赖注入：`api/dependencies.py`

routes 自己不创建 pipeline，而是调用 `get_pipeline()`。这个函数在 `dependencies.py` 里。

**核心模式：Provider 单例 + Pipeline 工厂**

```
get_config()   ─┐
get_llm()      ─┤
get_asr()      ─┼── 全部用 @lru_cache(maxsize=1) 缓存，进程内只创建一次
get_tts()      ─┤
get_crm()      ─┘

get_memory()   ─── 每次新建（因为不同 session 记忆要隔离）

get_pipeline(session_id) ─── 每次请求新建 Pipeline，注入上面的单例
```

**为什么这样设计？**
- LLM/ASR/TTS 创建开销大（加载模型、建立连接），全局复用
- Pipeline 包含对话状态（dialogue），每次请求要独立
- Memory 不同 session 不能共享，每次新建

---

**Day 1 自测：**
- [ ] 能说出 5 个接口的输入输出分别是什么
- [ ] 流式 vs 非流式的代码路径有什么区别
- [ ] `run_in_executor` 是干嘛的
- [ ] `get_pipeline()` 每次请求都调用，但 LLM 只创建一次，怎么做到的

---

## Day 2：核心管道 — LLM 怎么思考的

**目标：** 理解 `QAPipeline` 的完整流程，能追踪一次文本问答的数据流。

**阅读时长：** 1-1.5 小时

### 2.1 先看类图（心里有个地图）

```
QAPipeline
├── __init__()          组装零件：asr, llm, tts, memory, dialogue, tool_handler
├── ask_text()          ★ 文本问答入口 → 调 ask_text_stream() 取最终结果
├── ask_text_stream()   ★ 流式文本问答：记忆检索 → LLM → 记忆保存
├── ask_voice()         语音问答：ASR → ask_text() → 可选 TTS
├── ask_voice_stream()  流式语音：ASR → LLM流式 → TTS流式
├── ask_vision()        图片问答：VLLM 分析 + 记忆保存
│
├── _chat_simple()      简单 LLM 对话（不调工具）
├── _chat_simple_stream()    同上，流式版
├── _chat_with_tools()       带工具调用的 LLM 对话
├── _chat_with_tools_stream()同上，流式版
├── _handle_tool_calls()     执行工具 → 可能递归调用 LLM
│
├── _query_memory()     查记忆
├── _save_memory()      存记忆（后台线程）
│
└── _speech_to_text() / _text_to_speech()   ASR / TTS 辅助
```

### 2.2 从最简单的路径开始：`ask_text()`

```python
def ask_text(self, question: str) -> str:
    result = None
    for event in self.ask_text_stream(question):   # ← 注意！直接调 stream 版
        if event.get("done"):
            result = event.get("text", "")
    return result or ""
```

**设计模式：非流式 = 对流式的包装。** `ask_text()` 遍历流式生成器，丢弃中间的 token，只取最后的 `done` 事件。

### 2.3 核心流程：`ask_text_stream()`

这是整个项目最重要的方法。一步一步来：

```python
def ask_text_stream(self, question: str):
    # 第 1 步：查记忆
    memory_str = self._query_memory(question)
    # → 从 mem_local_short 读之前保存的对话摘要，注入到 LLM 上下文

    # 第 2 步：写入对话历史
    self.dialogue.put(Message(role="user", content=question))
    # → dialogue 是一个列表，存着整个对话：system→user→assistant→user→...

    # 第 3 步：调 LLM
    if self.intent_type == "function_call" and self.tool_handler:
        for token in self._chat_with_tools_stream(memory_str):
            yield ...                              # 带工具调用路径
    else:
        for token in self._chat_simple_stream(memory_str):
            yield ...                              # 简单对话路径

    # 第 4 步：保存记忆
    self._save_memory()
    # → 后台线程，不阻塞

    # 第 5 步：最终事件
    yield {"done": True, "text": full_text, "session_id": self.session_id}
```

**数据流：**
```
用户问题 → 查记忆 → 拼对话历史 → 调 LLM API → 逐字返回 → 存记忆
```

### 2.4 对话历史管理：`core/utils/dialogue.py`

```python
class Message:
    role, content, tool_calls, tool_call_id, is_temporary

class Dialogue:
    dialogue: List[Message]    ← 就是消息列表
    put(message)               ← 往里加消息
    get_llm_dialogue_with_memory(memory_str)  ← 转成 OpenAI API 格式
```

`get_llm_dialogue_with_memory()` 做的事情：
1. 把 system prompt 拆成"静态部分"+"动态部分"
2. 把 few-shot 示例插在中间
3. 动态部分填充时间、记忆
4. 最后拼上用户对话历史

这形成最终的 messages 数组发给 LLM API：
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

### 2.5 LLM 调用：`_chat_with_tools()`

当 LLM 支持 function calling 时走这条路径：

```python
def _chat_with_tools(self, memory_str, depth=0):
    if depth >= 5:
        return self._chat_simple(memory_str)   # 防止无限循环

    # 1. 构建对话 + 工具列表
    llm_dialogue = self._build_llm_dialogue(memory_str)
    functions = list(self.tool_handler.get_functions())
    # functions 长这样：
    # [{"type": "function", "function": {"name": "get_weather", ...}}, ...]

    # 2. 调 LLM（带 tools）
    for chunk in self.llm.response_with_functions(session_id, dialogue, functions):
        content, tools_call = self._parse_chunk(chunk)
        # 可能既返回文字又返回工具调用

    # 3. 没有工具调用 → 直接返回文字
    if not tool_calls_list:
        return text

    # 4. 有工具调用 → 执行 → 可能递归
    return self._handle_tool_calls(tool_calls_list, depth)
```

**流程图：**
```
LLM 收到问题
  ├── "我知道答案" → 返回文字 ✓
  └── "我需要查天气" → 返回 function_call
        └── 执行 get_weather("亳州")
              ├── 工具直接回复 → 返回结果 ✓
              └── 工具说需要 LLM 再总结 → 再调一次 _chat_with_tools (递归)
```

### 2.6 工具执行：`_handle_tool_calls()`

```python
def _handle_tool_calls(self, tool_calls_list, depth):
    # 1. 写入 assistant(tool_calls) 消息
    self.dialogue.put(Message(role="assistant", tool_calls=[...]))

    # 2. 逐个执行工具
    for tc in tool_calls_list:
        # 处理 async/sync 混用问题
        try:
            loop = asyncio.get_running_loop()
            result = asyncio.run_coroutine_threadsafe(tool_handler.handle(tc), loop)
        except RuntimeError:
            result = asyncio.run(tool_handler.handle(tc))

        # 3. 根据工具返回的 Action 决定下一步
        if result.action == Action.RESPONSE:
            # 工具自己回答了，写入 assistant 消息
            self.dialogue.put(Message(role="assistant", content=...))
        elif result.action == Action.REQLLM:
            # 工具返回了原始数据，需要 LLM 再总结
            need_llm = True

    # 4. 需要的话递归
    if need_llm:
        return self._chat_with_tools(None, depth + 1)
```

---

**Day 2 自测：**
- [ ] `ask_text()` 和 `ask_text_stream()` 的关系是什么
- [ ] `ask_text_stream()` 分哪 5 步
- [ ] dialogue 最后发给 LLM API 的 messages 数组长什么样
- [ ] LLM 说要调工具 → 执行工具 → 工具返回后，代码路径怎么走

---

## Day 3：供应商层 — LLM/ASR/TTS 怎么和外部服务交互

**目标：** 理解 Provider 模式，能看懂一个 LLM API 调用是如何发出去的。

**阅读时长：** 1 小时

### 3.1 Provider 模式

项目用一种叫"策略模式"的设计：每个能力定义一个抽象基类，不同实现互相替换。

```
core/providers/
├── llm/
│   ├── base.py         ← LLMProviderBase（抽象类）
│   └── openai/
│       └── openai.py   ← 调 DeepSeek/智谱 等 OpenAI 兼容 API
├── asr/
│   ├── base.py         ← ASRProviderBase
│   └── fun_local.py    ← 本地 FunASR 模型
├── tts/
│   ├── base.py         ← TTSProviderBase
│   ├── doubao.py       ← 火山引擎豆包 TTS
│   └── edge.py         ← 微软 Edge TTS（免费）
└── memory/
    ├── base.py         ← MemoryProviderBase
    └── mem_local_short/
        └── mem_local_short.py  ← 本地文件 + LLM 总结
```

**好处：** 想换 LLM？改配置文件就行，不用改代码。想加新的 TTS？写个子类就行。

### 3.2 深入 LLM Provider

看 `core/providers/llm/openai/openai.py`（路径就是 `openai` 目录下的 `openai.py`）。

关键方法：

```python
class OpenAILLM(LLMProviderBase):
    def response(self, session_id, dialogue):
        """流式调用 OpenAI 兼容 API"""
        # POST /v1/chat/completions
        # stream=True
        # yield 每个 chunk

    def response_with_functions(self, session_id, dialogue, functions):
        """同上，但带上 tools 参数，支持 function calling"""
        # POST /v1/chat/completions
        # 请求体里加 "tools": functions

    def response_no_stream(self, system_prompt, user_prompt):
        """非流式调用（用于画像提取等后台任务）"""
```

**核心就是往 OpenAI 兼容的 API 发 HTTP 请求。** 不管是 DeepSeek 还是 ChatGLM，只要 API 格式兼容 OpenAI，用同一个类，换 url 和 api_key 就行。

### 3.3 ASR：语音转文字

`core/providers/asr/fun_local.py` — 本地 FunASR 模型。

```python
async def speech_to_text_wrapper(self, frames, session_id, audio_format):
    # frames: PCM 音频数据分片列表
    # 调 FunASR 模型（SenseVoiceSmall）
    # 返回识别结果（包含文本和情绪标签）
```

ASR 返回的文本带标签，例如：
```
<|zh|><|HAPPY|><|Speech|><|withitn|>今天天气真好
```

`core/providers/asr/utils.py` 里的 `lang_tag_filter()` 负责解析这些标签，提取纯文本、语言、情绪。

### 3.4 TTS：文字转语音

不同 TTS provider 的接口不同，但都实现 `text_to_speak(text, ...)` → 返回音频 bytes。

豆包 TTS 支持流式 (`text_to_speak_stream`)，逐块返回音频，适合实时播放。

### 3.5 Memory：记忆系统

`core/providers/memory/mem_local_short/mem_local_short.py`：

```
对话历史 → LLM 总结 → 存本地 YAML 文件 → 下次对话时注入上下文
```

流程：
1. `save_memory(dialogue)` — 被调用时，把所有对话发给 LLM，让它总结成一段摘要
2. `short_memory` 属性 — 读取上次保存的摘要
3. 下次 `_query_memory()` — 把摘要拼到 LLM 对话里

---

**Day 3 自测：**
- [ ] Provider 模式的好处是什么
- [ ] 想把 DeepSeek 换成 GPT-4，需要改哪些地方
- [ ] ASR 识别结果带情绪标签，是谁负责解析的
- [ ] 记忆系统的工作流程：存的时候做了什么，取的时候做了什么

---

## Day 4：工具和插件 — LLM 怎么"动手"

**目标：** 理解工具注册、工具执行、插件函数的完整链路。

**阅读时长：** 45 分钟

### 4.1 插件是怎么注册的

每个插件文件用装饰器注册：

```python
# plugins_func/functions/get_weather.py

@register_function("get_weather", GET_WEATHER_FUNCTION_DESC, ToolType.SYSTEM_CTL)
def get_weather(conn, location=None, lang="zh_CN"):
    ...
```

`@register_function` 做了什么：
1. 把函数存到全局字典 `all_function_registry`
2. 同时存入函数描述（给 LLM 看的 function calling schema）
3. 标记工具类型（决定执行时是否传入 context）

### 4.2 工具处理器：`core/tool_handler.py`

```python
class SimplifiedToolHandler:
    def get_functions(self):
        """从配置读取启用的函数列表 → 从 registry 取出描述 → 返回给 LLM"""

    async def handle_llm_function_call(self, function_call_data):
        """LLM 说'帮我调 get_weather(location=亳州)' → 我执行并返回结果"""

    async def execute_tool(self, tool_name, arguments):
        """实际执行：从 registry 拿函数 → 根据类型决定传不传 context → 调用"""
```

### 4.3 一个完整的工具例子：`get_weather`

```python
def get_weather(conn, location=None, lang="zh_CN"):
    # 1. 没指定城市 → 用默认城市（亳州）
    if not location:
        location = config["plugins"]["get_weather"]["default_location"]

    # 2. 查缓存
    cached = cache_manager.get(...)
    if cached:
        return ActionResponse(Action.RESPONSE, cached, None)

    # 3. API 查城市 ID
    city_info = fetch_city_info(location, api_key, api_host)

    # 4. 爬天气页面
    soup = fetch_weather_page(city_info["fxLink"])

    # 5. 解析 HTML → 天气报告
    city_name, current, forecast = parse_weather_info(soup)

    # 6. 缓存 + 返回
    return ActionResponse(Action.RESPONSE, weather_report, weather_report)
```

### 4.4 当前可用的工具

| 工具 | 文件 | 作用 |
|------|------|------|
| `get_weather` | `get_weather.py` | 查天气（qweather API） |
| `get_news_from_newsnow` | `get_news_from_newsnow.py` | 查新闻（newsnow API） |
| `web_search` | `web_search.py` | 联网搜索（Tavily/秘塔） |
| `get_lunar` | `get_lunar.py` | 查农历 |

---

**Day 4 自测：**
- [ ] 想加一个新工具（比如查快递），需要改哪些文件
- [ ] `Action.RESPONSE` 和 `Action.REQLLM` 的区别是什么
- [ ] LLM 不知道有哪些工具可用——是谁告诉它的

---

## Day 5：配置和辅助模块

**目标：** 理解配置加载、提示词管理、对话管理。

**阅读时长：** 30 分钟

### 5.1 配置：`config/config_loader.py`

```python
def load_config():
    # 1. 读 data/.config.yaml → dict
    # 2. 返回配置字典
```

极其简单，就是从 YAML 文件读到 dict。

### 5.2 提示词管理：`core/utils/prompt_manager.py`

```python
class PromptManager:
    def __init__(self, config):
        # 加载 data/.agent-base-prompt.txt（Jinja2 模板）

    def build_enhanced_prompt(self, user_prompt, **kwargs):
        # 1. 获取当前时间、日期、农历
        # 2. Jinja2 渲染模板：{{base_prompt}} {{today_date}} {{lunar_date}} ...
        # 3. 返回最终 system prompt
```

**模板渲染流程：**
```
data/.agent-base-prompt.txt (Jinja2 模板)
    + data/.config.yaml 里的 prompt (角色设定)
    + 当前时间/日期/农历（实时注入）
    + Emoji 白名单
    = 最终的 system prompt，发给 LLM
```

### 5.3 对话管理：`core/utils/dialogue.py`

Day 2 已经讲过了，这里复习：
- `Message` — 一条消息（role + content + 可选的 tool_calls）
- `Dialogue` — 消息列表 + 导出为 OpenAI API 格式
- `_ensure_tool_calls_complete()` — 保证没有悬空的 tool_calls（防止 API 400 错误）

### 5.4 项目文件树总览

```
xiaozhi_server/
├── api_server.py              ← FastAPI 入口
├── api/
│   ├── routes.py              ← 5 个接口
│   ├── schemas.py             ← 请求/响应模型
│   └── dependencies.py        ← Provider 单例 + Pipeline 工厂
├── core/
│   ├── qa_pipeline.py         ← 核心管道（最重要！）
│   ├── tool_handler.py        ← 工具调度器
│   ├── providers/
│   │   ├── llm/openai/        ← DeepSeek/ChatGLM
│   │   ├── asr/fun_local.py   ← FunASR 本地模型
│   │   ├── tts/doubao.py      ← 火山引擎 TTS
│   │   └── memory/mem_local_short/ ← 文件+LLM 记忆
│   └── utils/
│       ├── prompt_manager.py  ← 提示词模板渲染
│       ├── dialogue.py        ← 对话历史管理
│       └── tts.py             ← Markdown 清洗
├── plugins_func/functions/    ← 工具函数
│   ├── get_weather.py
│   ├── get_news_from_newsnow.py
│   ├── get_lunar.py
│   └── web_search.py
├── config/
│   ├── config_loader.py       ← 读 YAML 配置
│   └── logger.py              ← 日志
└── data/
    ├── .config.yaml           ← 你的配置（API key 等）
    └── .agent-base-prompt.txt ← 提示词模板
```

---

**Day 5 自测：**
- [ ] 提示词模板里的 `{{today_date}}` 最终变成什么，谁负责替换的
- [ ] 想改角色设定（让 AI 变成"老师"而不是"小智"），改哪个文件的哪一行
- [ ] 能画出项目的文件依赖图吗

---

## 防困秘诀

1. **带着问题看代码，不要顺着读。** "我想知道天气工具是怎么被调用的" → 搜 `get_weather` → 跟踪调用链，而不是从第 1 行看到第 800 行。

2. **加 print 调试。** 在 `qa_pipeline.py` 的方法里加：
   ```python
   print(f">>> ask_text 被调用，question={question[:50]}")
   ```
   然后发一个请求，看终端输出，比干读快 3 倍。

3. **画调用链。** 拿张纸，从 `routes.py` 的接口开始，箭头指向下一个函数，一直画到 LLM API 调用。不用好看，自己看得懂就行。

4. **改配置看效果。** 把角色 prompt 改一改，把工具列表改一改，把 TTS 换成 EdgeTTS——改动后的效果立竿见影，理解更深。

5. **一次只看一层。** routes 是门卫，pipeline 是大脑，providers 是手脚。不要在看着 routes 的时候去想 pipeline 里面怎么实现的——就当它是个黑盒。

---

## 动手练习

每学完一天的内容，做对应的练习巩固：

**Day 1 练习：**
- 在 Swagger 里用不同参数发 `/ask/text`，观察响应差异
- 找到 `stream=True` vs `stream=False` 的代码分支

**Day 2 练习：**
- 在 `ask_text_stream()` 里加 print，看每一步输出了什么
- 手动发两条消息用同一个 session_id，观察 dialogue 是怎么串联的

**Day 3 练习：**
- 把 LLM 从 DeepSeek 换成 ChatGLM（改 `data/.config.yaml` 里的 `selected_module.LLM`）
- 重启服务，发请求，观察是否正常工作

**Day 4 练习：**
- 跟踪一次"问天气"的完整调用链：`routes → pipeline → _chat_with_tools → LLM → tool_handler → get_weather → 返回`
- 把天气工具的默认城市改成你的城市

**Day 5 练习：**
- 修改 `data/.agent-base-prompt.txt`，加一条新规则，重启看效果
- 修改 `data/.config.yaml` 里的 prompt，把角色改成"一个严谨的大学教授"
