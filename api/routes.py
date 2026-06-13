"""问答 API 路由定义"""

import os
import uuid
import asyncio
from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
import json as json_module

from api.schemas import AskTextRequest, AskResponse, ErrorResponse
from api.dependencies import get_pipeline, get_tts

router = APIRouter(prefix="/ask", tags=["问答"])

# TTS 输出目录
AUDIO_OUTPUT_DIR = os.path.join("tmp", "api_audio")
os.makedirs(AUDIO_OUTPUT_DIR, exist_ok=True)


# ───────────────────── POST /ask/text ─────────────────────

@router.post(
    "/text",
    response_model=AskResponse,
    summary="文本问答",
    description="输入文本提问，返回 LLM 文本回复，可选择同时合成语音",
)
async def ask_text(req: AskTextRequest):
    """纯文本问答（支持 SSE 流式输出）"""
    pipeline = get_pipeline(session_id=req.session_id)

    if req.stream:
        async def generate():
            try:
                for event in pipeline.ask_text_stream(req.text):
                    yield f"data: {json_module.dumps(event, ensure_ascii=False)}\n\n"
            except Exception as e:
                yield f"data: {json_module.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"X-Session-Id": pipeline.session_id},
        )

    # 非流式模式
    try:
        text = await asyncio.get_running_loop().run_in_executor(
            None, pipeline.ask_text, req.text
        )
        audio_url = None
        if req.voice_output and text:
            audio_url = await _synthesize_and_save(pipeline, text)
        return AskResponse(
            code=0,
            message="ok",
            text=text,
            audio_url=audio_url,
            session_id=pipeline.session_id,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"问答失败: {str(e)}")


# ───────────────────── POST /ask/voice ─────────────────────

@router.post(
    "/voice",
    response_model=AskResponse,
    summary="语音问答",
    description="上传 WAV 音频文件，经 ASR 识别后由 LLM 回复，可选择返回合成语音",
)
async def ask_voice(
    audio: UploadFile = File(..., description="WAV 音频文件 (16kHz 单声道推荐)"),
    voice_output: bool = Form(False, description="是否返回语音回复"),
    session_id: str = Form("", description="会话 ID（空=新会话）"),
):
    """语音问答"""
    if audio.content_type and "audio" not in audio.content_type:
        pass

    pipeline = get_pipeline(session_id=session_id)
    try:
        audio_bytes = await audio.read()
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="上传的音频文件为空")

        result = await pipeline.ask_voice(audio_bytes, return_audio=voice_output)

        if not result["asr_text"]:
            return AskResponse(
                code=1,
                message="ASR 未能识别到有效语音内容",
                text="",
                asr_text="",
                session_id=pipeline.session_id,
            )

        audio_url = None
        if voice_output and result.get("audio"):
            audio_url = _save_audio_bytes(result["audio"])

        return AskResponse(
            code=0,
            message="ok",
            text=result["text"],
            asr_text=result["asr_text"],
            audio_url=audio_url,
            session_id=pipeline.session_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"语音问答失败: {str(e)}")


# ───────────────────── POST /ask/voice/stream ─────────────────────

@router.post(
    "/voice/stream",
    summary="语音问答（流式）",
    description="上传 WAV 音频，返回 SSE 流：ASR → LLM逐字 → TTS逐块音频",
)
async def ask_voice_stream(
    audio: UploadFile = File(..., description="WAV 音频文件 (16kHz 单声道推荐)"),
    session_id: str = Form("", description="会话 ID（空=新会话）"),
):
    pipeline = get_pipeline(session_id=session_id)
    try:
        audio_bytes = await audio.read()
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="上传的音频文件为空")

        async def generate():
            async for event in pipeline.ask_voice_stream(audio_bytes):
                yield f"data: {json_module.dumps(event, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"X-Session-Id": pipeline.session_id},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"流式语音问答失败: {str(e)}")


# ───────────────────── POST /ask/vision ─────────────────────

@router.post(
    "/vision",
    response_model=AskResponse,
    summary="图片问答",
    description="上传图片，输入问题（可选），由视觉语言模型分析并返回文本回复",
)
async def ask_vision(
    image: UploadFile = File(..., description="图片文件 (JPEG/PNG)"),
    question: str = Form("描述这张图片", description="关于图片的问题"),
    voice_output: bool = Form(False, description="是否返回 TTS 语音"),
    session_id: str = Form("", description="会话 ID"),
):
    """图片问答（接入 QAPipeline，支持记忆）"""
    pipeline = get_pipeline(session_id=session_id)
    try:
        image_bytes = await image.read()
        if not image_bytes:
            raise HTTPException(status_code=400, detail="上传的图片为空")

        import base64
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        text = pipeline.ask_vision(b64, question)

        audio_url = None
        if voice_output and text:
            tts = get_tts()
            if tts:
                from core.utils.tts import MarkdownCleaner
                try:
                    cleaned = MarkdownCleaner.clean_markdown(text)
                    audio_bytes = await tts.text_to_speak(cleaned, None)
                    if audio_bytes:
                        audio_url = _save_audio_bytes(audio_bytes)
                except Exception:
                    pass

        return AskResponse(
            code=0,
            message="ok",
            text=text,
            audio_url=audio_url,
            session_id=pipeline.session_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"图片分析失败: {str(e)}")


# ───────────────────── GET /ask/audio/{filename} ─────────────────────

@router.get(
    "/audio/{filename}",
    summary="下载合成语音",
    description="下载由 /ask/text 或 /ask/voice 生成的语音文件",
)
async def download_audio(filename: str):
    """下载生成的音频文件"""
    # 防止路径遍历
    safe_name = os.path.basename(filename)
    filepath = os.path.join(AUDIO_OUTPUT_DIR, safe_name)

    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="音频文件不存在或已过期")

    return FileResponse(
        filepath,
        media_type="audio/wav",
        filename=safe_name,
    )


# ───────────────────── 辅助函数 ─────────────────────

async def _synthesize_and_save(pipeline, text: str) -> Optional[str]:
    """合成语音并保存到文件，返回下载 URL"""
    audio_bytes = await pipeline._text_to_speech(text)
    if audio_bytes:
        return _save_audio_bytes(audio_bytes)
    return None


def _save_audio_bytes(audio_bytes: bytes) -> Optional[str]:
    """将音频 bytes 写入文件，返回相对 URL 路径"""
    filename = f"{uuid.uuid4().hex}.wav"
    filepath = os.path.join(AUDIO_OUTPUT_DIR, filename)
    try:
        with open(filepath, "wb") as f:
            f.write(audio_bytes)
        return f"/ask/audio/{filename}"
    except Exception:
        return None
