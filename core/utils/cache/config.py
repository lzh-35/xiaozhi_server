"""缓存配置"""

from enum import Enum


class CacheType(Enum):
    """缓存类型（只保留标签，实际仅 CONFIG 在核心链路使用）"""
    CONFIG = "config"
    # 以下为插件/工具兼容保留
    LOCATION = "location"
    WEATHER = "weather"
    LUNAR = "lunar"
    INTENT = "intent"
    IP_INFO = "ip_info"
    DEVICE_PROMPT = "device_prompt"
    AUDIO_DATA = "audio_data"
