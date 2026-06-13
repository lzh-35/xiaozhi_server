"""API 请求/响应数据模型"""

from typing import Optional
from fastapi import UploadFile
from pydantic import BaseModel, Field


# ───────────────────── 请求模型 ─────────────────────

class AskTextRequest(BaseModel):
    """文本问答请求"""
    text: str = Field(..., description="用户输入文本", min_length=1, max_length=10000)
    voice_output: bool = Field(False, description="是否同时返回语音")
    session_id: str = Field("", description="会话 ID（空=新会话，已有 ID=继续对话）")
    stream: bool = Field(True, description="是否使用 SSE 流式输出（默认开启）")


class AskVoiceRequest(BaseModel):
    """语音问答请求（元数据部分，音频文件通过 multipart 上传）"""
    voice_output: bool = Field(False, description="是否返回语音回复")


# ───────────────────── 响应模型 ─────────────────────

class AskResponse(BaseModel):
    """问答响应"""
    code: int = Field(0, description="状态码，0=成功")
    message: str = Field("ok", description="状态消息")
    text: str = Field("", description="LLM 回复文本")
    asr_text: Optional[str] = Field(None, description="ASR 识别文本（仅语音输入时返回）")
    audio_url: Optional[str] = Field(None, description="语音回复下载地址（voice_output=true 时返回）")
    session_id: str = Field("", description="会话 ID（用于多轮对话）")


class ErrorResponse(BaseModel):
    """错误响应"""
    code: int = Field(..., description="错误码")
    message: str = Field(..., description="错误消息")
    detail: Optional[str] = Field(None, description="详细信息")
