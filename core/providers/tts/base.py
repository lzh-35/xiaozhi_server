"""
TTS Provider 抽象基类

定义语音合成 Provider 的统一接口。
当前 REST API 只使用 text_to_speak / text_to_speak_stream / close 三个方法。
"""

import os
import re
import uuid
from datetime import datetime
from abc import ABC, abstractmethod

from config.logger import setup_logging
from core.utils.tts import convert_percentage_to_range

TAG = __name__
logger = setup_logging()


class TTSProviderBase(ABC):
    """TTS Provider 基类 — 供 doubao / edge 等具体实现继承"""

    def __init__(self, config: dict, delete_audio_file: bool):
        self.delete_audio_file = delete_audio_file
        self.output_file = config.get("output_dir", "tmp/")
        self.tts_timeout = int(config.get("tts_timeout", 15))

        # 同音词/替换词
        raw_words = config.get("correct_words", [])
        self.correct_words: dict[str, str] = {}
        for item in raw_words:
            parts = item.split("|", 1)
            if len(parts) == 2:
                self.correct_words[parts[0]] = parts[1]

        if self.correct_words:
            sorted_keys = sorted(self.correct_words.keys(), key=len, reverse=True)
            pattern_str = "|".join(re.escape(k) for k in sorted_keys)
            self._correct_words_pattern = re.compile(pattern_str)

            self._words_by_first_char: dict[str, list[str]] = {}
            for key in sorted_keys:
                first_char = key[0] if key else ""
                if first_char not in self._words_by_first_char:
                    self._words_by_first_char[first_char] = []
                self._words_by_first_char[first_char].append(key)
        else:
            self._correct_words_pattern = None
            self._words_by_first_char = {}

        self._pending_prefix = ""

    # ------------------------------------------------------------------
    # 抽象方法（子类必须实现）
    # ------------------------------------------------------------------

    @abstractmethod
    async def text_to_speak(self, text: str, output_file: str | None):
        """文字转语音

        Args:
            text: 要合成的文本
            output_file: 输出文件路径（None 则返回 bytes）
        """
        ...

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def generate_filename(self, extension: str = ".wav") -> str:
        """生成输出文件路径"""
        return os.path.join(
            self.output_file,
            f"tts-{datetime.now().date()}@{uuid.uuid4().hex}{extension}",
        )

    def _apply_percentage_params(self, config: dict):
        """根据 TTS_PARAM_CONFIG 批量设置百分比参数（子类在 __init__ 中调用）"""
        for config_key, attr_name, min_val, max_val, base_val, transform in self.TTS_PARAM_CONFIG:
            if config_key in config:
                val = convert_percentage_to_range(
                    config[config_key], min_val, max_val, base_val
                )
                setattr(self, attr_name, transform(val) if transform else val)

    def _match_stream_text(self, text: str) -> tuple[list[str], str]:
        """流式文本滑动窗口匹配 — 处理跨分片的替换词

        Returns:
            (确定的文本列表, 剩余待匹配前缀)
        """
        if not self.correct_words or not text:
            return [text] if text else [], ""

        result: list[str] = []
        pending = self._pending_prefix
        i = 0

        while i < len(text):
            char = text[i]
            test_text = pending + char
            matched = False

            candidates = (
                self._words_by_first_char.get(pending[0], [])
                if pending
                else self._words_by_first_char.get(char, [])
            )
            for key in candidates:
                if test_text == key:
                    result.append(self.correct_words[key])
                    pending = ""
                    matched = True
                    break
                elif key.startswith(test_text):
                    pending = test_text
                    matched = True
                    break

            if matched:
                i += 1
                continue

            if pending:
                result.append(pending)
                pending = ""

            if char in self._words_by_first_char:
                pending = char
            else:
                result.append(char)

            i += 1

        return result, pending

    def reset_stream_state(self):
        """重置流式状态"""
        self._pending_prefix = ""

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def close(self):
        """释放资源"""
        pass
