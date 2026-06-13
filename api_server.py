"""
XiaoZhi 语音问答 REST API 服务

基于 FastAPI 的解耦版本，复用 ASR / LLM / TTS Provider 层，
提供 /ask 接口支持文本和语音问答。

启动方式:
    python api_server.py
    uvicorn api_server:app --host 0.0.0.0 --port 8080 --reload

API 文档:
    http://localhost:8080/docs      (Swagger UI)
    http://localhost:8080/redoc     (ReDoc)
    http://localhost:8080/api.md    (Markdown)
"""

import os

# ───────────────────── 0. 确保运行时目录 ─────────────────────

_workdir = os.path.dirname(os.path.abspath(__file__))
os.chdir(_workdir)  # 切换到项目根目录，保证相对路径一致

# 没有 data/.config.yaml 时自动创建（fallback 到 config.yaml 默认配置）
_data_dir = os.path.join(_workdir, "data")
os.makedirs(_data_dir, exist_ok=True)
_config_override = os.path.join(_data_dir, ".config.yaml")
if not os.path.exists(_config_override):
    # 写入最小覆盖配置（全部使用 config.yaml 的默认值）
    with open(_config_override, "w", encoding="utf-8") as f:
        f.write("# 由 api_server 自动生成\n")
    print(f"[api_server] 已生成配置文件: {_config_override}")

# 没有 data/.agent-base-prompt.txt 时从示例文件自动创建
_prompt_tmpl = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", ".agent-base-prompt.txt")
_prompt_example = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "agent-base-prompt.example.txt")
if not os.path.exists(_prompt_tmpl) and os.path.exists(_prompt_example):
    _ = __import__("shutil").copy(_prompt_example, _prompt_tmpl)
    print(f"[api_server] 已恢复提示词模板: {_prompt_tmpl}")

# ───────────────────── 1. FastAPI 应用 ─────────────────────

import os as _os
import time as _time
import threading as _threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router as ask_router

app = FastAPI(
    title="XiaoZhi 语音问答 API",
    description="""
独立的语音问答 REST API 服务，从 XiaoZhi Server 解耦而来。

## 功能

- **文本问答** `POST /ask/text` — 输入文本 → LLM 流式/非流式回复（支持 TTS 语音输出）
- **语音问答** `POST /ask/voice` — 上传音频 → ASR → LLM → (TTS)
- **流式语音** `POST /ask/voice/stream` — 上传音频 → SSE 流式：ASR→LLM逐字→TTS逐块
- **图片问答** `POST /ask/vision` — 上传图片 → VLLM 视觉分析
- **音频下载** `GET /ask/audio/{filename}` — 下载 TTS 语音文件

## 技术栈

- ASR: FunASR 本地模型 (SenseVoiceSmall)
- LLM: DeepSeek (ChatGLM 免费备用)
- TTS: 火山引擎豆包 TTS (EdgeTTS 免费备用)
- VLLM: 智谱 glm-4v-flash
- Memory: 本地文件 + LLM 总结 (mem_local_short)
- Tools: 天气 / 新闻 / 搜索 / 农历

## 配置

配置文件 `data/.config.yaml`，修改后自动热加载。
    """,
    version="0.1.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 路由
app.include_router(ask_router)


# ───────────────────── 1.5 音频文件自动清理 ─────────────────────

def _cleanup_old_audio():
    """后台线程：每 10 分钟清理超过 1 小时的 TTS 音频文件"""
    audio_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "tmp", "api_audio")
    while True:
        _time.sleep(600)  # 10 分钟
        try:
            if not _os.path.exists(audio_dir):
                continue
            now = _time.time()
            for fname in _os.listdir(audio_dir):
                fpath = _os.path.join(audio_dir, fname)
                if _os.path.isfile(fpath) and (now - _os.path.getmtime(fpath)) > 3600:
                    _os.remove(fpath)
        except Exception:
            pass

_cleanup_thread = _threading.Thread(target=_cleanup_old_audio, daemon=True)
_cleanup_thread.start()


# ───────────────────── 2. 健康检查 ─────────────────────

@app.get("/health", summary="健康检查", tags=["系统"])
async def health():
    return {"status": "ok", "version": app.version}


# ───────────────────── 3. API 文档（Markdown） ─────────────────────

@app.get("/api.md", summary="API 文档 (Markdown)", tags=["系统"])
async def api_markdown():
    """返回 docs/api.md 原始内容"""
    from fastapi.responses import PlainTextResponse
    doc_path = os.path.join(_workdir, "docs", "api.md")
    if not os.path.exists(doc_path):
        return PlainTextResponse("# docs/api.md 尚未创建", status_code=404)
    with open(doc_path, "r", encoding="utf-8") as f:
        return PlainTextResponse(f.read())


# ───────────────────── 4. 全局异常处理 ─────────────────────

from fastapi import Request
from fastapi.responses import JSONResponse
from api.schemas import ErrorResponse


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常兜底"""
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            code=500,
            message="服务器内部错误",
            detail=str(exc),
        ).model_dump(),
    )


# ───────────────────── 5. 启动入口 ─────────────────────

if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("API_HOST", "0.0.0.0")
    port = int(os.environ.get("API_PORT", "8080"))

    print(f"""
╔═══════════════════════════════════════════════════════╗
║     XiaoZhi 语音问答 API Server                       ║
║                                                       ║
║     Swagger:  http://{host}:{port}/docs               ║
║     ReDoc:    http://{host}:{port}/redoc              ║
║     API 文档: http://{host}:{port}/api.md             ║
║     健康检查: http://{host}:{port}/health             ║
╚═══════════════════════════════════════════════════════╝
    """)

    uvicorn.run(
        "api_server:app",
        host=host,
        port=port,
        reload=True,
        log_level="info",
    )
