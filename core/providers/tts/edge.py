import edge_tts
from core.providers.tts.base import TTSProviderBase


class TTSProvider(TTSProviderBase):
    def __init__(self, config, delete_audio_file):
        super().__init__(config, delete_audio_file)
        if config.get("private_voice"):
            self.voice = config.get("private_voice")
        else:
            self.voice = config.get("voice")

    async def text_to_speak(self, text, output_file):
        try:
            communicate = edge_tts.Communicate(text, voice=self.voice)
            if output_file:
                os.makedirs(os.path.dirname(output_file), exist_ok=True)
                with open(output_file, "wb") as f:
                    pass
                with open(output_file, "ab") as f:
                    async for chunk in communicate.stream():
                        if chunk["type"] == "audio":
                            f.write(chunk["data"])
            else:
                audio_bytes = b""
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_bytes += chunk["data"]
                return audio_bytes
        except Exception as e:
            raise Exception(f"Edge TTS请求失败: {e}")

    async def text_to_speak_stream(self, text):
        """流式生成 TTS 音频，逐块 yield bytes"""
        communicate = edge_tts.Communicate(text, voice=self.voice)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]