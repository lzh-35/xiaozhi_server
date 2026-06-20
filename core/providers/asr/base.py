"""
ASR Provider 抽象基类

定义语音识别 Provider 的统一接口。
当前 REST API 中只使用 speech_to_text_wrapper → speech_to_text 这一条链路。
"""

import io
import os
import uuid
import wave
import shutil
import tempfile
import opuslib_next

from abc import ABC, abstractmethod
from config.logger import setup_logging
from typing import Optional, Tuple, List, NamedTuple

TAG = __name__
logger = setup_logging()


class ASRProviderBase(ABC):
    """ASR Provider 基类 — 供 fun_local 等具体实现继承"""

    # 音频分帧: 60ms * 16kHz * 2bytes = 1920
    FRAME_SIZE = 1920

    # ------------------------------------------------------------------
    # 抽象方法（子类必须实现）
    # ------------------------------------------------------------------

    @abstractmethod
    async def speech_to_text(
        self,
        opus_data: List[bytes],
        session_id: str,
        audio_format: str = "opus",
        artifacts: Optional["ASRProviderBase.AudioArtifacts"] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        """语音转文本

        Args:
            opus_data: 音频数据帧列表
            session_id: 会话 ID
            audio_format: 音频格式 (pcm / opus)
            artifacts: 预处理后的音频工件

        Returns:
            (识别文本, 文件路径)
        """
        ...

    # ------------------------------------------------------------------
    # 音频预处理 & 工具方法
    # ------------------------------------------------------------------

    class AudioArtifacts(NamedTuple):
        """ASR 预处理结果"""
        pcm_frames: List[bytes]
        pcm_bytes: bytes
        file_path: Optional[str] = None
        temp_path: Optional[str] = None

    async def speech_to_text_wrapper(
        self, opus_data: List[bytes], session_id: str, audio_format: str = "opus"
    ) -> Tuple[Optional[str], Optional[str]]:
        """统一的语音识别入口 — REST API 调用此方法"""
        file_path = None
        temp_path = None
        try:
            if audio_format == "pcm":
                pcm_data = opus_data
            else:
                pcm_data = self.decode_opus(opus_data)
            combined_pcm_data = b"".join(pcm_data)

            free_space = shutil.disk_usage(self.output_dir).free
            if free_space < len(combined_pcm_data) * 2:
                raise OSError("磁盘空间不足")

            if self.requires_file() and self.prefers_temp_file():
                temp_path = self.build_temp_file(combined_pcm_data)

            if (hasattr(self, "delete_audio_file") and not self.delete_audio_file) or (
                self.requires_file() and not self.prefers_temp_file()
            ):
                file_path = self.save_audio_to_file(pcm_data, session_id)

            if len(combined_pcm_data) == 0:
                artifacts = None
            else:
                artifacts = ASRProviderBase.AudioArtifacts(
                    pcm_frames=pcm_data,
                    pcm_bytes=combined_pcm_data,
                    file_path=file_path,
                    temp_path=temp_path,
                )

            text, _ = await self.speech_to_text(
                opus_data, session_id, audio_format, artifacts
            )
            return text, file_path
        except OSError as e:
            logger.bind(tag=TAG).error(f"文件操作错误: {e}")
            return None, None
        except Exception as e:
            logger.bind(tag=TAG).error(f"语音识别失败: {e}")
            return None, None
        finally:
            try:
                if temp_path and os.path.exists(temp_path):
                    os.unlink(temp_path)
                if (
                    hasattr(self, "delete_audio_file")
                    and self.delete_audio_file
                    and file_path
                    and os.path.exists(file_path)
                ):
                    os.remove(file_path)
            except OSError:
                pass

    def requires_file(self) -> bool:
        """是否需要文件输入（默认不需要）"""
        return False

    def prefers_temp_file(self) -> bool:
        """是否优先使用临时文件（默认不需要）"""
        return False

    def build_temp_file(self, pcm_bytes: bytes) -> Optional[str]:
        """将 PCM 数据写入临时 WAV 文件"""
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                temp_path = tmp.name
            with wave.open(temp_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(pcm_bytes)
            return temp_path
        except OSError as e:
            logger.bind(tag=TAG).error(f"临时音频文件生成失败: {e}")
            return None

    def save_audio_to_file(self, pcm_data: List[bytes], session_id: str) -> str:
        """PCM 数据保存为 WAV 文件"""
        module_name = __name__.split(".")[-1]
        file_name = f"asr_{module_name}_{session_id}_{uuid.uuid4()}.wav"
        file_path = os.path.join(self.output_dir, file_name)

        with wave.open(file_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"".join(pcm_data))

        return file_path

    @staticmethod
    def decode_opus(opus_data: List[bytes]) -> List[bytes]:
        """Opus → PCM 解码"""
        decoder = None
        try:
            decoder = opuslib_next.Decoder(16000, 1)
            pcm_data = []
            buffer_size = 960

            for i, opus_packet in enumerate(opus_data):
                try:
                    if not opus_packet:
                        continue
                    pcm_frame = decoder.decode(opus_packet, buffer_size)
                    if pcm_frame:
                        pcm_data.append(pcm_frame)
                except opuslib_next.OpusError as e:
                    logger.bind(tag=TAG).warning(f"Opus 解码跳过数据包 {i}: {e}")
                except Exception as e:
                    logger.bind(tag=TAG).error(f"音频处理错误, 数据包 {i}: {e}")

            return pcm_data
        except Exception as e:
            logger.bind(tag=TAG).error(f"音频解码失败: {e}")
            return []
        finally:
            if decoder is not None:
                try:
                    del decoder
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def close(self):
        """释放资源（子类可重写）"""
        pass
